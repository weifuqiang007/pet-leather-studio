"""第三轮评审 B：叠加图必须把红色按 ~31% 混合进原图 RGB，主体内部细节可辨。

旧实现 paste 用蒙版整片替换像素，输出纯红 RGB + alpha=80，主体内部依赖查看器
透明底合成、看不到原图内容。被测函数在 experiments 脚本内，从文件路径加载。
"""

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "run_p1_three_photos", _ROOT / "experiments" / "photo_relief" / "run_p1_three_photos.py"
)
run_p1 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(run_p1)

ALPHA = 80 / 255  # 蒙版主体处的红色不透明度


def test_overlay_blends_red_into_original_rgb(tmp_path: Path) -> None:
    original = np.full((8, 8, 3), (100, 150, 200), dtype=np.uint8)
    work = tmp_path / "work.png"
    Image.fromarray(original).save(work)
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[:, :4] = 255  # 左半为主体

    out = tmp_path / "overlay.png"
    run_p1.save_mask_overlay(work, mask, out)

    with Image.open(out) as image:  # 成品须为不带 alpha 的 RGB
        assert image.mode == "RGB"
        result = np.asarray(image.convert("RGB"), dtype=np.float32)
    assert result.shape == (32, 32, 3)  # 4× 放大

    inside = result[12, 4]  # 主体内部（远离边界黄线）
    expected = (1 - ALPHA) * original[3, 1] + ALPHA * np.array([255.0, 48.0, 48.0])
    assert np.allclose(inside, expected, atol=2), inside
    assert not np.allclose(inside, [255, 48, 48], atol=2)  # 不得是恒定纯红

    assert np.allclose(result[12, 28], original[3, 6], atol=1)  # 蒙版外保持原图

    boundary = result[12, 15]  # 蒙版边缘处应被黄色边界线覆盖
    assert np.allclose(boundary, [255, 214, 0], atol=2)
