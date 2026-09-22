# P3 交付：照片细节层母版

日期：2026-09-22。

## 目的

P2/R3 的 1.5 mm 全局平滑能让表面满足坡度门，但也会擦除眼鼻、毛流和花瓣脉络等识别细节。本交付将母版高度场分成两层：深度图决定低频体块；照片亮度与原始深度的局部对比生成受限微浮雕。预览、CLI 和导出使用同一算法，母版修订保持可回退。

## 实现

- `detail_strength` 已从仅记录的占位参数变为有效参数，范围 `0–1`；GUI 和 CLI 默认值为 `0.60`，设为 `0` 可关闭。
- 细节层使用有效域感知的高通：深度残差始终参与；照片 `work.png` 存在时，与其灰度局部对比等权融合。无照片时不伪造照片细节。
- 微浮雕振幅受 `min(0.24 mm, 主起伏 × 0.12) × detail_strength` 限制。它用于眼鼻轮廓、毛流等浅层信息，不能被解释为照片中不存在的真实三维结构。
- 正向细节先受每个像素的高度余量限制，避免峰值被静默截平；对于起伏不超过 4 mm 的细节候选，再执行只降低尖峰的 45° 坡度保护。高比例母版不启用该保护，继续保留真实坡度警告。
- `manifest.detail` 记录算法、来源、振幅限制、实际 RMS/峰值、是否使用照片、余量裁剪点和坡度保护结果。

## 默认候选与验收

默认 GUI/CLI 候选为：显式起伏 `2.0 mm`、平滑 `1.5 mm`、过渡带 `3.0 mm`、细节强度 `0.60`。用三张本机样本运行：

```bash
scripts/dev.sh run --frozen python experiments/photo_relief/run_p3_detail_samples.py
```

本次重跑的 `p3-detail-samples/report_data.json` 记录：短毛犬全域/边界/域内最大坡度 `45.0° / 25.5° / 36.7°`；猫为 `39.8° / 31.0° / 32.0°`；长毛犬为 `44.7° / 35.5° / 41.6°`。三条母版均无 warnings，且都保存了细节层实际振幅。

代码验收结果：

```text
pytest tests -m 'not real_model'     176 passed, 2 deselected
pytest tests/integration/test_real_model_depth.py -q    2 passed
runtime/gui_p2_smoke.py              ok
ruff / format / mypy                 passed
```

## 边界

这不是单张照片生成高精度真实雕塑的模型。当前样本仅 148 px，细节层只能将照片中已有的局部对比转换成低幅度纹理；它不能可靠推断被遮挡的五官、长毛的真实空间层次或花瓣背面结构。进入阴阳模前仍应由操作者在 GUI 检查正面、侧面、斜视图，并对关键部位用局部调整工具复核。

`experiments/photo_relief/out/p3-detail-samples/` 是 gitignored 本机证据；脚本会追加修订而不覆盖历史母版，故可用既有版本回退。
