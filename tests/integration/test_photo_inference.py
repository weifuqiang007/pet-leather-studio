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


def _write_model(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "weights.bin").write_bytes(b"model-bytes")
    digest = hashlib.sha256(b"model-bytes").hexdigest()
    (directory / "manifest.json").write_text(
        json.dumps({"files": {"weights.bin": {"sha256": digest}}}), encoding="utf-8"
    )
    return directory


def test_registry_missing_model_gives_setup_hint(tmp_path: Path) -> None:
    with pytest.raises(ResourceMissingError, match="setup_photo_models"):
        ModelRegistry(tmp_path / "models").locate(None)


def test_registry_verifies_hashes(tmp_path: Path) -> None:
    root = tmp_path / "models"
    revision = _write_model(root / "hf" / "stub-model" / "aaa")
    assert ModelRegistry(root).locate("stub-model") == revision  # 最新修订

    (revision / "weights.bin").write_bytes(b"tampered")
    with pytest.raises(ResourceMissingError, match="hash 不匹配"):
        ModelRegistry(root).locate("stub-model")

    (revision / "weights.bin").unlink()
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


def test_product_path_never_imports_inference_libraries() -> None:
    """正常产品路径（本包 infrastructure）不得触发 torch/transformers/huggingface_hub 导入。"""
    for name in ("torch", "transformers", "huggingface_hub"):
        assert name not in sys.modules, f"{name} 不应出现在产品进程内"
