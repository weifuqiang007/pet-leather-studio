"""系统与依赖体检，结果写入 runtime/system_profile.json（PRD 3.2）。

检查项：OS/架构/CPU/内存/磁盘、Python 与关键依赖版本、Blender 探测、
FreeCAD 状态（未安装不算错误，PRD M0 通过条件）。
退出码：0 = 可继续；1 = 存在阻断项（当前仅当依赖缺失且无法导入时）。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pet_leather_studio.bootstrap import environment  # noqa: E402

KEY_DEPS = (
    "numpy",
    "scipy",
    "trimesh",
    "Pillow",
    "PySide6",
    "pyvista",
    "pyvistaqt",
    "vtk",
)

BLENDER_CANDIDATES_MACOS = ("/Applications/Blender.app/Contents/MacOS/Blender",)
FREECAD_CANDIDATES_MACOS = ("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD",)


def _disk_free_gb(path: Path) -> float:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize / 1e9


def _ram_gb() -> float:
    try:
        out = subprocess.run(  # noqa: S603 - 固定参数数组
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return int(out) / 1073741824
    except (OSError, subprocess.CalledProcessError, ValueError):
        return -1.0


def _probe_tool(name: str, candidates: tuple[str, ...]) -> dict[str, str | None]:
    """按候选路径与 PATH 探测外部工具，调用 --version 校验（PRD F04 方式）。"""
    found: str | None = shutil.which(name)
    if not found:
        for cand in candidates:
            if Path(cand).is_file():
                found = cand
                break
    if not found:
        return {"status": "not_found", "path": None, "version": None}
    try:
        out = subprocess.run(  # noqa: S603
            [found, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        first = (out.stdout or out.stderr).strip().splitlines()
        return {
            "status": "ok",
            "path": found,
            "version": first[0] if first else None,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "probe_failed", "path": found, "version": None, "error": str(exc)}


def main() -> int:
    environment.apply_local_env()
    environment.ensure_local_dirs()

    config_path = REPO_ROOT / "configs" / "defaults.toml"
    with config_path.open("rb") as fh:
        config = tomllib.load(fh)
    blender_cfg = config.get("blender", {})
    extra_blender = blender_cfg.get("executable_path", "")
    candidates = BLENDER_CANDIDATES_MACOS + ((extra_blender,) if extra_blender else ())

    deps: dict[str, str] = {}
    missing: list[str] = []
    for dist in KEY_DEPS:
        try:
            deps[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            missing.append(dist)

    profile: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "system": {
            "os": f"{platform.system()} {platform.release()}",
            "macos_version": platform.mac_ver()[0],
            "arch": platform.machine(),
            "cpu": platform.processor() or "unknown",
            "cores": os.cpu_count(),
            "ram_gb": round(_ram_gb(), 1),
            "disk_free_gb_data_root": round(_disk_free_gb(environment.data_root()), 1),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "in_project_venv": str(environment.data_root() / ".venv") in sys.executable,
        },
        "dependencies": deps,
        "dependencies_missing": missing,
        "blender": _probe_tool("blender", candidates),
        "freecad": _probe_tool("freecad", FREECAD_CANDIDATES_MACOS),
        "paths": {
            "app_root": str(environment.app_root()),
            "data_root": str(environment.data_root()),
            "uv_cache_dir": str(environment.data_root() / ".cache/uv"),
        },
    }

    out_path = environment.data_root() / "runtime" / "system_profile.json"
    out_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"系统画像已写入 {out_path}")
    print(json.dumps(profile["system"], ensure_ascii=False, indent=2))
    print(f"Python {profile['python']}")  # type: ignore[arg-type]
    print(f"依赖版本: {deps if deps else '（尚无）'}")
    print(f"Blender: {profile['blender']}")
    print(f"FreeCAD: {profile['freecad']}")
    if missing:
        print(f"缺失依赖（先运行 scripts/dev.sh sync）: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
