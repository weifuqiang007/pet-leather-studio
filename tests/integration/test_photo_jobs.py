"""PH08：失败/崩溃不留成功修订、active 不回退、可重跑；残留 staging 显式清理。"""

import os
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
