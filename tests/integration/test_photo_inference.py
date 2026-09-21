"""PH11：模型清单校验、隔离 worker 调用、输出组装拒绝；产品路径不导入推理库。"""

import hashlib
import json
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pet_leather_studio.domain.errors import ResourceMissingError, ToolUnavailableError
from pet_leather_studio.infrastructure.photo_inference import (
    DepthWorker,
    ModelRegistry,
    PhotoInference,
    assemble_depth_revision,
)


def _write_model(directory: Path, downloaded_at: str = "2026-09-20T10:00:00") -> Path:
    directory.mkdir(parents=True)
    (directory / "model.safetensors").write_bytes(b"model-bytes")
    digest = hashlib.sha256(b"model-bytes").hexdigest()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "files": {"model.safetensors": {"sha256": digest}},
                "downloaded_at": downloaded_at,
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_registry_missing_model_gives_setup_hint(tmp_path: Path) -> None:
    with pytest.raises(ResourceMissingError, match="setup_photo_models"):
        ModelRegistry(tmp_path / "models").locate(None)


def test_registry_verifies_hashes(tmp_path: Path) -> None:
    root = tmp_path / "models"
    revision = _write_model(root / "hf" / "stub-model" / "aaa")
    assert ModelRegistry(root).locate("stub-model") == revision  # 最新修订

    (revision / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ResourceMissingError, match="hash 不匹配"):
        ModelRegistry(root).locate("stub-model")

    (revision / "model.safetensors").unlink()
    with pytest.raises(ResourceMissingError, match="模型文件缺失"):
        ModelRegistry(root).locate("stub-model")


def test_worker_requires_venv_explicitly(tmp_path: Path) -> None:
    worker = DepthWorker(tmp_path / "missing" / "bin" / "python", tmp_path / "worker.py")
    with pytest.raises(ToolUnavailableError, match="bootstrap"):
        worker.run(tmp_path / "i.png", tmp_path / "m.png", tmp_path / "model", tmp_path / "out")


STUB_WORKER = textwrap.dedent(
    """
    import argparse, json
    from pathlib import Path
    import numpy as np
    from PIL import Image

    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command != "infer":
        raise SystemExit(2)
    with Image.open(args.mask) as mask_image:
        valid = np.asarray(mask_image.convert("L")) > 127
    height, width = valid.shape
    depth = np.repeat(
        np.linspace(0.2, 0.8, height, dtype=np.float32)[:, None], width, axis=1
    )
    np.save(args.out / "depth_raw.npy", depth)
    (args.out / "metadata.json").write_text(
        json.dumps(
            {
                "semantics": "relative_larger_nearer",
                "model": {"model_id": "stub-worker", "revision": "x"},
                "device": "cpu",
                "elapsed_s": 0.02,
                "torch": "stub",
                "implementation": "stub-worker",
                "mask_used_for_inference": False,
            }
        ),
        encoding="utf-8",
    )
    """
)


def _mask_png(path: Path) -> Path:
    arr = np.zeros((30, 40), dtype=np.uint8)
    arr[6:24, 8:32] = 255
    Image.fromarray(arr, mode="L").save(path)
    return path


def test_photo_inference_runs_isolated_worker_and_stages(tmp_path: Path) -> None:
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB_WORKER, encoding="utf-8")
    mask = _mask_png(tmp_path / "mask.png")
    stage = tmp_path / "stage"
    stage.mkdir()

    inference = PhotoInference(Path(sys.executable), script)
    metadata = inference.run_and_stage(
        tmp_path / "unused-image.png", mask, tmp_path / "model", stage
    )
    with np.load(stage / "depth.npz") as data:
        assert data["depth"].shape == (30, 40)
        assert data["valid"].sum() == 18 * 24
        assert data["depth"][~data["valid"]].max() == 0.0  # 无效区置零
    assert metadata["depth_semantics"] == "relative_larger_nearer"
    assert metadata["valid_coverage"] == pytest.approx(18 * 24 / 1200)
    assert metadata["runtime"]["device"] == "cpu"
    assert metadata["model"]["model_id"] == "stub-worker"


def test_worker_failure_surfaces_exit_and_stderr(tmp_path: Path) -> None:
    script = tmp_path / "failing_worker.py"
    script.write_text(
        "import sys; print('boom-traceback', file=sys.stderr); sys.exit(3)",
        encoding="utf-8",
    )
    worker = DepthWorker(Path(sys.executable), script)
    with pytest.raises(RuntimeError, match="推理进程失败（exit 3）") as excinfo:
        worker.run(tmp_path / "i.png", tmp_path / "m.png", tmp_path / "model", tmp_path / "out")
    assert "boom-traceback" in str(excinfo.value)  # stderr 尾部被带回主进程


def _base_metadata() -> dict:
    return {
        "semantics": "relative_larger_nearer",
        "model": {},
        "device": "cpu",
        "elapsed_s": 0.0,
        "torch": None,
        "implementation": "stub",
        "mask_used_for_inference": False,
    }


def test_assemble_rejects_bad_worker_output(tmp_path: Path) -> None:
    mask = _mask_png(tmp_path / "mask.png")
    stage = tmp_path / "stage"
    stage.mkdir()
    worker_out = tmp_path / "worker"
    worker_out.mkdir()

    np.save(worker_out / "depth_raw.npy", np.zeros((30, 40, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="二维"):
        assemble_depth_revision(worker_out, mask, stage, _base_metadata())

    np.save(worker_out / "depth_raw.npy", np.zeros((10, 10), dtype=np.float32))
    with pytest.raises(ValueError, match="不一致"):
        assemble_depth_revision(worker_out, mask, stage, _base_metadata())

    empty = tmp_path / "empty.png"
    Image.fromarray(np.zeros((30, 40), dtype=np.uint8), mode="L").save(empty)
    np.save(worker_out / "depth_raw.npy", np.linspace(0, 1, 1200).reshape(30, 40))
    with pytest.raises(ValueError, match="有效区域为空"):
        assemble_depth_revision(worker_out, empty, stage, _base_metadata())

    np.save(worker_out / "depth_raw.npy", np.full((30, 40), 0.5, dtype=np.float32))
    with pytest.raises(ValueError, match="恒定"):
        assemble_depth_revision(worker_out, mask, stage, _base_metadata())


def test_assemble_rejects_nan_inside_subject(tmp_path: Path) -> None:
    """主体域内 NaN 必须拒绝发布，不得静默改成背景缩小有效域（PH04）。"""
    mask = _mask_png(tmp_path / "mask.png")
    stage = tmp_path / "stage"
    stage.mkdir()
    worker_out = tmp_path / "worker"
    worker_out.mkdir()

    arr = np.linspace(0.0, 1.0, 30 * 40, dtype=np.float32).reshape(30, 40)
    arr[15, 20] = np.nan  # 主体内
    np.save(worker_out / "depth_raw.npy", arr)
    with pytest.raises(ValueError, match="NaN/Inf"):
        assemble_depth_revision(worker_out, mask, stage, _base_metadata())
    assert not (stage / "depth.npz").exists()  # 未发布任何文件

    arr[15, 20] = 0.5
    arr[0, 0] = np.inf  # 主体外（蒙版外）：允许存储层置零处理
    np.save(worker_out / "depth_raw.npy", arr)
    metadata = assemble_depth_revision(worker_out, mask, stage, _base_metadata())
    assert metadata["valid_coverage"] == pytest.approx(18 * 24 / 1200)


def test_assemble_rejects_tiny_coverage(tmp_path: Path) -> None:
    arr = np.linspace(0.0, 1.0, 30 * 40, dtype=np.float32).reshape(30, 40)
    tiny = tmp_path / "tiny.png"
    mask = np.zeros((30, 40), dtype=np.uint8)
    mask[10, 10] = 255  # 1/1200 ≈ 0.08%，低于 1% 工程下限
    Image.fromarray(mask, mode="L").save(tiny)
    worker_out = tmp_path / "worker"
    worker_out.mkdir()
    np.save(worker_out / "depth_raw.npy", arr)
    with pytest.raises(ValueError, match="低于工程下限"):
        assemble_depth_revision(worker_out, tiny, tmp_path / "stage2", _base_metadata())


def test_assemble_preserves_raw_float_output(tmp_path: Path) -> None:
    """原始浮点输出（未置零）必须随修订保存，供复用与诊断（评审补充建议）。"""
    mask = _mask_png(tmp_path / "mask.png")
    stage = tmp_path / "stage"
    stage.mkdir()
    worker_out = tmp_path / "worker"
    worker_out.mkdir()
    arr = np.linspace(0.0, 1.0, 30 * 40, dtype=np.float32).reshape(30, 40)
    np.save(worker_out / "depth_raw.npy", arr)
    metadata = {**_base_metadata(), "input_size": [40, 30], "output_shape": [30, 40]}
    assemble_depth_revision(worker_out, mask, stage, metadata)
    raw = np.load(stage / "depth_raw.npy")
    assert np.array_equal(raw, arr)  # 蒙版外数值未被置零
    with np.load(stage / "depth.npz") as data:
        assert data["depth"][~data["valid"]].max() == 0.0  # 发布数据仍置零
    assert metadata["input_size"] == [40, 30] and metadata["output_shape"] == [30, 40]


def test_registry_prefers_selected_then_download_time(tmp_path: Path) -> None:
    """hash 字典序不代表时间：无选择文件时按 downloaded_at 取最新，有则遵循。"""
    root = tmp_path / "models"
    # 目录名顺序与时间顺序相反："ffff…" 早于 "0000…" 下载
    _write_model(root / "hf" / "stub-model" / "ffff1111", "2026-09-01T00:00:00")
    newer = _write_model(root / "hf" / "stub-model" / "00009999", "2026-09-19T00:00:00")
    registry = ModelRegistry(root)
    assert registry.locate("stub-model") == newer  # 不取字典序最后的 ffff…

    (root / "hf" / "stub-model" / "selected.json").write_text(
        json.dumps({"revision": "ffff1111"}), encoding="utf-8"
    )
    assert registry.locate("stub-model").name == "ffff1111"  # 显式选择优先


def test_registry_selected_pointing_to_missing_revision_errors(tmp_path: Path) -> None:
    """F2：selected.json 指向缺失修订必须报错，不得静默回退到最新下载。"""
    root = tmp_path / "models"
    _write_model(root / "hf" / "stub-model" / "aaaa1111", "2026-09-01T00:00:00")
    newer = _write_model(root / "hf" / "stub-model" / "bbbb2222", "2026-09-19T00:00:00")
    selected = root / "hf" / "stub-model" / "selected.json"
    selected.write_text(json.dumps({"revision": "gone3333"}), encoding="utf-8")
    with pytest.raises(ResourceMissingError, match=r"selected\.json 指向修订 gone3333"):
        ModelRegistry(root).locate("stub-model")

    selected.unlink()
    assert ModelRegistry(root).locate("stub-model") == newer  # 无选择文件才回退最新


@pytest.mark.parametrize(
    "content,match",
    [
        ("{broken", r"无法解析"),
        (json.dumps({}), r"缺少有效 revision"),
        (json.dumps({"revision": ""}), r"缺少有效 revision"),
        (json.dumps(["aaaa1111"]), r"不是 JSON 对象"),
    ],
)
def test_registry_corrupted_selected_errors_not_fallback(
    tmp_path: Path, content: str, match: str
) -> None:
    """A（第三轮）：selected.json 存在但损坏必须报错，不得当作"没有选择"回退。

    文件不存在才允许回退最新下载（上一下用例已覆盖）。
    """
    root = tmp_path / "models"
    _write_model(root / "hf" / "stub-model" / "aaaa1111", "2026-09-01T00:00:00")
    (root / "hf" / "stub-model" / "selected.json").write_text(content, encoding="utf-8")
    with pytest.raises(ResourceMissingError, match=match):
        ModelRegistry(root).locate("stub-model")


def test_registry_verify_rejects_degenerate_manifests(tmp_path: Path) -> None:
    root = tmp_path / "models"

    empty = root / "hf" / "m-empty" / "rev"
    empty.mkdir(parents=True)
    (empty / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    with pytest.raises(ResourceMissingError, match="文件列表为空"):
        ModelRegistry(root).locate("m-empty")

    no_weights = root / "hf" / "m-noweights" / "rev"
    no_weights.mkdir(parents=True)
    (no_weights / "manifest.json").write_text(
        json.dumps({"files": {"config.json": {"sha256": "0" * 64}}}), encoding="utf-8"
    )
    with pytest.raises(ResourceMissingError, match="safetensors"):
        ModelRegistry(root).locate("m-noweights")

    nested = root / "hf" / "m-nested" / "rev"
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text(
        json.dumps({"files": {"sub/model.safetensors": {"sha256": "0" * 64}}}), encoding="utf-8"
    )
    with pytest.raises(ResourceMissingError, match="非顶层路径"):
        ModelRegistry(root).locate("m-nested")


def test_product_path_never_imports_inference_libraries() -> None:
    """正常产品路径（本包 infrastructure）不得触发 torch/transformers/huggingface_hub 导入。"""
    for name in ("torch", "transformers", "huggingface_hub"):
        assert name not in sys.modules, f"{name} 不应出现在产品进程内"


def _load_worker_module():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "photo_inference_worker.py"
    spec = importlib.util.spec_from_file_location("photo_inference_worker_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_threads_revision_to_hub(tmp_path: Path, monkeypatch) -> None:
    """R5：--revision 必须传给 model_info 与 snapshot_download，才能复现指定版本。"""
    import types
    from types import SimpleNamespace

    calls: dict[str, list] = {"model_info": [], "snapshot": []}
    fake_sha = "a" * 40

    class FakeApi:
        def __init__(self, endpoint: str | None = None) -> None:
            self.endpoint = endpoint

        def model_info(self, repo, files_metadata=False, revision=None):
            calls["model_info"].append({"repo": repo, "revision": revision})
            return SimpleNamespace(
                sha=fake_sha,
                siblings=[SimpleNamespace(rfilename="model.safetensors", size=16)],
            )

    def fake_snapshot(**kwargs):
        calls["snapshot"].append(kwargs)
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "model.safetensors").write_bytes(b"0123456789abcdef")
        return str(local_dir)

    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = FakeApi
    hub.snapshot_download = fake_snapshot
    requests_mod = types.ModuleType("requests")
    exceptions = types.ModuleType("requests.exceptions")

    class RequestException(Exception):
        pass

    exceptions.RequestException = RequestException
    requests_mod.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "requests", requests_mod)
    monkeypatch.setitem(sys.modules, "requests.exceptions", exceptions)

    worker = _load_worker_module()
    out = tmp_path / "models" / "hf" / "stub-model"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker.py",
            "download",
            "--repo",
            "org/stub",
            "--revision",
            "refs/old-tag",
            "--out",
            str(out),
            "--cache",
            str(tmp_path / "cache"),
        ],
    )
    assert worker.main() == 0
    assert calls["model_info"][0]["revision"] == "refs/old-tag"  # 查询带 revision
    assert calls["snapshot"][0]["revision"] == fake_sha  # 下载用解析后的提交
    manifest = json.loads((out / fake_sha / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == fake_sha
    selected = json.loads((out / "selected.json").read_text(encoding="utf-8"))
    assert selected["revision"] == fake_sha  # 记录选中版本，locate() 不再按 hash 猜


def test_download_reselect_updates_pointer_and_keeps_it_on_verify_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """F2：已存在修订重新 download 时重校验并把指针切回该版本；
    校验失败则保持原选中不变（先校验后切指针，不指向坏版本）。"""
    import types
    from types import SimpleNamespace

    shas = {"refs/old-tag": "a" * 40, "refs/new-tag": "b" * 40}

    class FakeApi:
        def __init__(self, endpoint: str | None = None) -> None:
            pass

        def model_info(self, repo, files_metadata=False, revision=None):
            return SimpleNamespace(
                sha=shas[revision],
                siblings=[SimpleNamespace(rfilename="model.safetensors", size=16)],
            )

    def fake_snapshot(**kwargs):
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "model.safetensors").write_bytes(b"0123456789abcdef")
        return str(local_dir)

    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = FakeApi
    hub.snapshot_download = fake_snapshot
    requests_mod = types.ModuleType("requests")
    exceptions = types.ModuleType("requests.exceptions")

    class RequestException(Exception):
        pass

    exceptions.RequestException = RequestException
    requests_mod.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "requests", requests_mod)
    monkeypatch.setitem(sys.modules, "requests.exceptions", exceptions)

    worker = _load_worker_module()
    out = tmp_path / "models" / "hf" / "stub-model"

    def download(tag: str) -> int:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "worker.py",
                "download",
                "--repo",
                "org/stub",
                "--revision",
                tag,
                "--out",
                str(out),
                "--cache",
                str(tmp_path / "cache"),
            ],
        )
        return worker.main()

    def selected_revision() -> str:
        return json.loads((out / "selected.json").read_text(encoding="utf-8"))["revision"]

    assert download("refs/old-tag") == 0
    assert selected_revision() == "a" * 40
    assert download("refs/new-tag") == 0
    assert selected_revision() == "b" * 40

    # 已存在的 A 再次显式 download：界面/定位应切回 A（旧实现不更新指针、仍指 B）
    assert download("refs/old-tag") == 0
    assert selected_revision() == "a" * 40

    # B 的权重被改坏后重新 download：校验失败退出，选中指针不得切到坏版本
    (out / ("b" * 40) / "model.safetensors").write_bytes(b"tampered-bytes")
    assert download("refs/new-tag") == 1
    assert selected_revision() == "a" * 40
