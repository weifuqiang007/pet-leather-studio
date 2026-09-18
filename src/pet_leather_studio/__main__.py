"""应用入口（M0：仅环境自检，无 GUI）。

从任意 cwd 启动均须成功（PRD M0 通过条件）；普通启动不联网、不加载 AI。
M1 将在此启动主窗口。
"""

from __future__ import annotations

import sys

from pet_leather_studio import __version__
from pet_leather_studio.bootstrap import environment
from pet_leather_studio.bootstrap.logging_setup import setup_logging


def main() -> int:
    environment.apply_local_env()
    root_paths = environment.ensure_local_dirs()
    setup_logging()
    print(f"Pet Leather Studio v{__version__}（M0 骨架，无 GUI）")
    print(f"APP_ROOT : {environment.app_root()}")
    print(f"DATA_ROOT: {environment.data_root()}")
    print(f"本地目录已就绪: {len(root_paths)} 个")
    print("普通启动不联网；未集成 AI、FreeCAD（按 PRD 属正常降级）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
