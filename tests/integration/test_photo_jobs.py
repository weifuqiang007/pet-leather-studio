"""PH08：失败/崩溃不留成功修订、active 不回退、可重跑；残留 staging 显式清理。"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from photo_stubs import StubInference, StubRegistry, make_mask_png, make_photo_png

from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.domain.photo_relief import MaskMethod
from pet_leather_studio.infrastructure.photo_io import PhotoIO
from pet_leather_studio.infrastructure.revisions import RevisionStore


def prepare_pair(tmp_path: Path, mode: str = "ok") -> tuple[RevisionStore, PhotoWorkbench, dict]:
    store = RevisionStore(tmp_path / "proj")
    service = PhotoWorkbench(store, PhotoIO(), StubInference(mode), StubRegistry())
    photo = service.import_photo(make_photo_png(tmp_path / "pet.png"))
    mask = service.save_mask(
        photo.revision_id, make_mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL
    )
    return store, service, {"photo": photo, "mask": mask}


@pytest.mark.parametrize(
    "mode,exc_type,match",
    [("fail", ValueError, "故意失败"), ("crash", RuntimeError, "中途崩溃")],
)
def test_failed_depth_publishes_nothing(
    tmp_path: Path, mode: str, exc_type: type[Exception], match: str
) -> None:
    store, service, pair = prepare_pair(tmp_path, mode)
    with pytest.raises(exc_type, match=match):
        service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    assert len(store.history()) == 2  # 无 depth 修订
    assert store.get()["id"] == pair["mask"].revision_id  # active 不变
    assert not list((store.root / "staging").iterdir())  # staging 已清理


def test_rerun_after_failure_succeeds(tmp_path: Path) -> None:
    store, service, pair = prepare_pair(tmp_path, "fail")
    with pytest.raises(ValueError, match="故意失败"):
        service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    service.inference.mode = "ok"  # type: ignore[attr-defined]
    depth = service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    assert store.get(depth.revision_id)["kind"] == "depth"
    assert store.get()["id"] == depth.revision_id
    assert len(store.history()) == 3


def test_tampered_mask_rejected_before_publish(tmp_path: Path) -> None:
    store, service, pair = prepare_pair(tmp_path, "ok")
    depth = service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    with (store.directory(pair["mask"].revision_id) / "mask.png").open("ab") as stream:
        stream.write(b"\x00tamper")
    with pytest.raises(ValueError, match="文件已变化"):
        service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    assert len(store.history()) == 3 and store.get()["id"] == depth.revision_id


def test_prune_staging_removes_only_stale_residue(tmp_path: Path) -> None:
    store, service, pair = prepare_pair(tmp_path, "ok")
    service.estimate_depth(pair["photo"].revision_id, pair["mask"].revision_id)
    before = len(store.history())

    stale = store.root / "staging" / "crash-leftover"
    stale.mkdir()
    (stale / "depth.npz").write_text("partial")
    fresh = store.root / "staging" / "running-job"
    fresh.mkdir()
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))

    removed = store.prune_staging(min_age_hours=1.0)
    assert removed == ["crash-leftover"]
    assert not stale.exists()  # 崩溃残留被清
    assert fresh.exists()  # 进行中任务不动
    assert len(store.history()) == before  # revisions 历史不受影响

    recent = store.root / "staging" / "just-now"
    recent.mkdir()
    assert store.prune_staging(min_age_hours=1.0) == []  # 未到时限不清理


@pytest.mark.skipif(os.name != "posix", reason="进程组回收仅在 POSIX 验证")
def test_sigterm_terminates_worker_process_tree(tmp_path: Path) -> None:
    """R1：父进程（CLI）收到 SIGTERM 必须整组回收推理 worker，不留孤儿子进程。"""
    root = Path(__file__).resolve().parents[2]
    stub_worker = tmp_path / "sleepy_worker.py"
    stub_worker.write_text(
        textwrap.dedent(
            """
            import os, sys, time
            out = sys.argv[sys.argv.index("--out") + 1]
            with open(os.path.join(out, "pid.txt"), "w") as stream:
                stream.write(str(os.getpid()))
            time.sleep(60)
            """
        ),
        encoding="utf-8",
    )
    harness = tmp_path / "harness.py"
    harness.write_text(
        textwrap.dedent(
            f"""
            import sys
            from pathlib import Path

            sys.path.insert(0, {str(root / "src")!r})
            from pet_leather_studio.infrastructure.photo_inference import DepthWorker

            python, stub, image, mask, model, out = sys.argv[1:7]
            DepthWorker(Path(python), Path(stub)).run(
                Path(image), Path(mask), Path(model), Path(out)
            )
            """
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "worker-out"

    harness_proc = subprocess.Popen(
        [
            sys.executable,
            str(harness),
            sys.executable,
            str(stub_worker),
            str(tmp_path / "image.png"),
            str(tmp_path / "mask.png"),
            str(tmp_path / "model"),
            str(out_dir),
        ]
    )
    try:
        pid_file = out_dir / "pid.txt"
        deadline = time.time() + 15
        while not pid_file.is_file():
            assert time.time() < deadline, "worker 未在时限内启动"
            if harness_proc.poll() is not None:
                pytest.fail("harness 提前退出")
            time.sleep(0.05)
        worker_pid = int(pid_file.read_text().strip())
        os.kill(worker_pid, 0)  # worker 存活

        harness_proc.terminate()  # SIGTERM，等同 GUI 取消路径
        assert harness_proc.wait(timeout=15) != 0

        gone = False
        for _ in range(100):
            try:
                os.kill(worker_pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                gone = True
                break
        assert gone, "推理 worker 未随父进程 SIGTERM 退出（进程树泄漏）"
    finally:
        if harness_proc.poll() is None:
            harness_proc.kill()
            harness_proc.wait(timeout=10)
