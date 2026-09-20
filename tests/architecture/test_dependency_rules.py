"""架构测试（PRD 4.1）：用 AST 检查依赖方向，禁止循环导入的基础约束。

规则（M0 生效子集）：
- domain/ 不得导入 Qt、VTK、PySide、pyvista、SQLite、Blender 相关模块；
- 任何模块不得从 pet_leather_studio 之外导入本项目未声明的内部包。
随里程碑推进逐步扩展（如禁止 UI 导入求解器）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "pet_leather_studio"

FORBIDDEN_IN_DOMAIN = (
    "PySide6",
    "PyQt5",
    "PyQt6",
    "vtk",
    "pyvista",
    "pyvistaqt",
    "sqlite3",
)

# 仅允许 domain 内部互相导入与标准库/三方数值库（数值库不含 UI/渲染）
# __future__ 是编译器指令，不是真实导入
ALLOWED_NONSTANDARD_PREFIXES_IN_DOMAIN = ("pet_leather_studio", "__future__")


def iter_python_files(package: Path):
    yield from sorted(package.rglob("*.py"))


def imported_top_levels(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_domain_imports_no_ui_or_storage_frameworks() -> None:
    violations: list[str] = []
    for path in iter_python_files(SRC / "domain"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tops = imported_top_levels(tree)
        for bad in FORBIDDEN_IN_DOMAIN:
            if bad in tops:
                violations.append(f"{path.relative_to(SRC)} 导入了 {bad}")
    assert not violations, "domain 层违反依赖规则：\n" + "\n".join(violations)


def test_domain_only_imports_known_prefixes() -> None:
    violations: list[str] = []
    for path in iter_python_files(SRC / "domain"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for top in imported_top_levels(tree):
            if top in sys.stdlib_module_names or top in ALLOWED_NONSTANDARD_PREFIXES_IN_DOMAIN:
                continue
            violations.append(f"{path.relative_to(SRC)} 导入了非白名单顶层包 {top}")
    assert not violations, "\n".join(violations)


def test_no_blanket_except_in_src() -> None:
    """禁止裸 except（PRD 11.2）。"""
    violations: list[str] = []
    for path in iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(f"{path.relative_to(SRC)}:{node.lineno} 裸 except")
    assert not violations, "\n".join(violations)


def imported_module_names(tree: ast.AST) -> set[tuple[str, ...]]:
    """返回 (顶层包, 完整模块路径) 集合，用于分层方向检查。"""
    names: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.name.split(".")[0], alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add((node.module.split(".")[0], node.module))
    return names


def test_no_reverse_layer_dependencies() -> None:
    """照片管线分层（实施路径文档）：禁止层反向依赖。

    - domain：只允许标准库与 pet_leather_studio.domain；
    - application：不得导入 infrastructure/presentation/algorithms；
    - presentation：不得导入推理库（torch/transformers/huggingface_hub）。
    """
    violations: list[str] = []

    for path in iter_python_files(SRC / "domain"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for _top, module in imported_module_names(tree):
            if _top in sys.stdlib_module_names or _top == "__future__":
                continue
            if module == "pet_leather_studio" or module.startswith("pet_leather_studio.domain"):
                continue
            violations.append(
                f"{path.relative_to(SRC)} 导入了 {module}（domain 只允许标准库与 domain 内部）"
            )

    for path in iter_python_files(SRC / "application"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for _top, module in imported_module_names(tree):
            forbidden = ("pet_leather_studio.infrastructure", "pet_leather_studio.presentation")
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(SRC)} 反向导入 {module}")
            elif module == "pet_leather_studio.algorithms" or module.startswith(
                "pet_leather_studio.algorithms."
            ):
                violations.append(f"{path.relative_to(SRC)} 导入了算法层 {module}（应由端口承接）")

    inference_tops = ("torch", "transformers", "huggingface_hub")
    for path in iter_python_files(SRC / "presentation"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for top, module in imported_module_names(tree):
            if top in inference_tops:
                violations.append(f"{path.relative_to(SRC)} 直接导入了推理库 {module}")

    assert not violations, "分层反向依赖：\n" + "\n".join(violations)
