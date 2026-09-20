"""真实模型推理冒烟（PH09 前置）：仅真机运行，缺权重时 skip。

标记 real_model：CI 与常规本机命令用 -m 'not real_model' 排除；
报告须注明是否实际运行。产品代码路径本身不依赖本文件。
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import MaskMethod

pytestmark = pytest.mark.real_model


def _model_installed() -> bool:
    from pet_leather_studio.bootstrap import environment
    from pet_leather_studio.infrastructure.photo_inference import ModelRegistry

    try:
        ModelRegistry(environment.app_root() / "models").locate(None)
        return True
    except Exception:  # noqa: BLE001 - 探测用：任何失败都视为未安装
        return False


@pytest.fixture(scope="module")
def synthetic_project(tmp_path_factory) -> Path:
    project = tmp_path_factory.mktemp("real-model-proj")
    arr = np.zeros((240, 320, 3), dtype=np.uint8)
    arr[40:200, 60:260] = (140, 110, 80)  # 中央“主体”
    photo_png = tmp_path_factory.mktemp("inputs") / "synthetic.png"
    Image.fromarray(arr).save(photo_png, format="PNG")
    mask_png = photo_png.parent / "mask.png"
    mask = np.zeros((240, 320), dtype=np.uint8)
    mask[40:200, 60:260] = 255
    Image.fromarray(mask, mode="L").save(mask_png)

    service = create_photo_workbench(project)
    photo = service.import_photo(photo_png)
    service.save_mask(photo.revision_id, mask_png, MaskMethod.MANUAL, notes="real_model 冒烟")
    return project


@pytest.mark.skipif(not _model_installed(), reason="模型未安装（先运行 setup_photo_models.py）")
def test_real_depth_inference_runs(synthetic_project: Path) -> None:
    service = create_photo_workbench(synthetic_project)
    photo = next(r for r in service.store.history() if r["kind"] == "photo")
    mask = next(r for r in service.store.history() if r["kind"] == "mask")
    depth = service.estimate_depth(photo["id"], mask["id"])

    manifest = service.store.get(depth.revision_id)
    runtime = manifest["runtime"]
    assert runtime["device"] in ("mps", "cpu", "cpu（MPS 不可用回退）")
    assert runtime["implementation"].startswith("transformers ")
    assert manifest["depth_semantics"] == "relative_larger_nearer"
    assert manifest["model"]["model_id"] == "depth-anything-v2-small-hf"
    assert manifest["valid_coverage"] > 0.3
    with np.load(service.store.directory(depth.revision_id) / "depth.npz") as data:
        region = data["depth"][data["valid"]]
        assert region.min() < region.max()  # 真实输出不是常数
        assert np.isfinite(region).all()
    print(f"[real_model] device={runtime['device']} elapsed={runtime['elapsed_s']}s")


@pytest.mark.skipif(not _model_installed(), reason="模型未安装（先运行 setup_photo_models.py）")
def test_worker_rejects_corrupt_model(synthetic_project: Path, tmp_path: Path) -> None:
    """损坏权重必须被 hash 校验拒绝；在临时副本上测试，不动正式权重。"""
    from pet_leather_studio.bootstrap import environment
    from pet_leather_studio.domain.errors import ResourceMissingError
    from pet_leather_studio.infrastructure.photo_inference import ModelRegistry

    real = ModelRegistry(environment.app_root() / "models").locate(None)
    fake_root = tmp_path / "models"
    target = fake_root / "hf" / real.parent.name / real.name
    target.parent.mkdir(parents=True)
    shutil.copytree(real, target)
    weights = target / "model.safetensors"
    with weights.open("ab") as stream:
        stream.write(b"\x00corrupt")
    with pytest.raises(ResourceMissingError, match="hash 不匹配"):
        ModelRegistry(fake_root).locate(None)
