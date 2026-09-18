# M0.5 Relief Spike（算法可行性短验证）

状态：**管线自测通过；相似度评审 pending（等待用户提供真实宠物照片）**。

## 目的

按 PRD 第 15 章 M0.5：纯脚本执行"标注 → 高度场 → 封闭 STL"，
验证区域基函数路线的工程可行性。本目录为一次性试验代码，
**生产代码不得导入此处模块**；通过后算法提炼进 `src/.../algorithms/relief/`。

## 运行方式

```bash
# 从仓库根目录
scripts/dev.sh run --frozen python experiments/relief_spike/relief_spike.py selftest
scripts/dev.sh run --frozen python experiments/relief_spike/relief_spike.py build \
    --annotation experiments/relief_spike/annotations/sample_a_head.json \
    --out runtime/spike/sample_a
```

## 算法（区域基函数高度场）

1. 每个 region = 多边形 + 高度(mm) + 平滑衰减半径(px)：栅格化掩码 →
   高斯模糊（σ=falloff）→ 峰值归一化 → 权重 w_i(x,y) ∈ [0,1]。
2. `H_base = Σ h_i · w_i`（加性组合，重叠区自然叠加）。
   改动某个 h_i 只影响该区域影响带（平滑带），满足局部性。
3. 高度场网格：`H(x,y)`，mm 网格间距 dx=sy=width_mm/图像宽（保持比例），
   图像坐标 Y 翻转为工件 Y 向上（PRD 6.1）。
4. 实体化：矩形有效域，顶面 z=base+H，底面 z=0，侧壁封边 → 封闭 STL。

## 自测覆盖（真实运行的检查，非占位）

- 无 NaN/Inf；STL 包围盒宽度误差 ≤0.01 mm（AC-F03-03 对应）
- 封闭、绕向一致、体积 > 0（trimesh 独立校验）
- 解析样本：平板块体积 == W×H×base（解析值对比）；单凸起中心高度 ≈ 设定值
- 局部性：鼻部高度 +0.5mm 时 |ΔH|>0.01mm 的像素只在影响带内（AC-F03-02 对应）
- 可复现：同参数重跑 STL/NPZ 字节级一致（sha256）
- 视图：正面/斜侧/侧视（1× 与 3× Z 夸大并明确标注），中性材质无贴图

## 与相似度评审的边界

本目录当前使用**抽象合成样本**，仅验证管线正确性；
**不得**据此宣称"照片→宠物浮雕"路线通过。需用户提供至少 3 张
真实宠物照片（猫、短毛狗、长吻狗，PRD 12.4）后手工标注生成评审包，
由负责人人工评审，此前一律 pending。
