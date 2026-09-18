# M0.5 spike 评审包说明（2026-09-18）

## 内容清单

每个样本目录（`sample_a_head` / `sample_b_bump` / `sample_c_flat`）包含：

| 文件 | 说明 |
| --- | --- |
| `relief_solid.stl` | 封闭实体网格（mm 单位，可直接送切片器检查） |
| `heightfield.npz` | 高度场数组 + dx/dy + 底厚 + 原点（重跑/复核用） |
| `params_snapshot.json` | 本次构建的完整参数快照（可据此逐字节重跑） |
| `validation.json` | 数值验收结果（封闭性/宽度误差/体积/Euler/哈希/耗时） |
| `views/front.png` `oblique.png` `side.png` | 真实比例多视图（中性灰、无贴图） |
| `views/*_zx3.png` | **Z×3 夸大**版本，仅便于观察起伏，非真实比例 |

> 注：`relief_solid.stl`（50–63MB/个）不进 git（见 .gitignore）。需要实体时
> 用 `relief_spike.py build --annotation … --out …` 重建——可复现性已验证，
> 同参数重建 STL sha256 一致。

## ⚠️ 相似度人工评审：待用户勾选（材料已就绪）

PRD §12.4 要求的评审材料是**真实宠物照片驱动的浮雕**，且评审人为用户本人。
合成样本（本目录 sample_a/b/c）只验证算法链路，**不能也不得**替代相似度评审。

### 2026-09-18 更新：真实照片样本已构建

用户提供 3 张照片（原文件在 `images/`，未修改）。因含用户宠物照片，全部
照片派生物放在 **workspace**（gitignored，不进 git）：

- 标注：`workspace/annotations/photo_{cat,short_hair_dog,long_hair_dog}.json`
- 产物：`workspace/spike_out/photo_*/`（STL/npz/快照/验证/视图，格式同合成样本）
- 评审包：`workspace/review/REVIEW-2026-09-18/`——含 `REVIEW-FORM.md`（勾选表）、
  每样本 `comparison.png`（原图 | 正面 Z×3 | 斜视 Z×3 三联图）与全部视图

几何验证：3 样本 watertight / winding / Euler=2 / 宽度误差 0.0mm 全过；
18 张视图本地数值 QC 非空白。

**如实记录的偏差（详见评审表）**：
1. 分辨率 148px / 205×148px，低于 §12.4 的 ≥800px 要求。
2. 第三张为长毛**短吻**西施犬，非要求的"长吻犬"——长吻类未覆盖（用户可在
   评审表勾选是否补拍）。
3. 标注由 AI 视觉辅助定位 + 人工核对生成（代理会话读图经云端视觉服务的工具
   机制偏差，如实披露）；几何管线完全本地。

评审结论以用户在 `REVIEW-FORM.md` 的勾选为准，代理不代评。

## 已完成且可复核的结论（合成样本）

- 封闭性 / 绕向 / 体积 / Euler：3 样本全部通过（见各 `validation.json`）
- 宽度误差：0.0mm（目标 ≤0.01mm，AC-F03-03）
- 局部性：鼻部 +0.5mm 扰动，影响带外泄漏 0 点
- 可复现性：同参数两次构建 STL sha256 完全一致
- 渲染：pyvista 离屏（VTK 9.7.0），无需回退 matplotlib
