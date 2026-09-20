"""Local desktop workbench and process-isolated CLI jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pet_leather_studio.bootstrap import environment


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="精细母版与配套模具候选工作台")
    result.add_argument("--project", type=Path)
    sub = result.add_subparsers(dest="command")
    imp = sub.add_parser("import-master")
    imp.add_argument("source", type=Path)
    mold = sub.add_parser("generate")
    mold.add_argument("--width", type=float, default=60)
    mold.add_argument("--depth", type=float, default=2)
    mold.add_argument("--gap", type=float, default=1)
    mold.add_argument("--backing", type=float, default=3)
    mold.add_argument("--grid", type=int, default=128)
    mold.add_argument("--feature", type=float, default=0.5)
    mold.add_argument("--accept-top-projection", action="store_true")
    sub.add_parser("history")
    activate = sub.add_parser("activate")
    activate.add_argument("revision_id")
    sub.add_parser("doctor")
    return result


def main() -> int:
    environment.apply_local_env()
    environment.ensure_local_dirs()
    args = parser().parse_args()
    if args.command == "doctor":
        print(json.dumps({"root": str(environment.app_root()), "offline": True}))
        return 0
    project = args.project or environment.data_root() / "workspace" / "mold-workbench"
    from pet_leather_studio.bootstrap.workbench import create_workbench

    service = create_workbench(project)
    if args.command is None:
        from PySide6.QtWidgets import QApplication

        from pet_leather_studio.presentation.workbench import WorkbenchWindow

        app = QApplication(sys.argv[:1])
        window = WorkbenchWindow(service, project)
        window.show()
        return app.exec()
    try:
        if args.command == "import-master":
            output = service.import_master(args.source)
        elif args.command == "generate":
            from pet_leather_studio.domain.molds import MoldParameters

            output = service.generate(
                MoldParameters(
                    args.width,
                    args.depth,
                    args.gap,
                    args.backing,
                    args.grid,
                    args.feature,
                    args.accept_top_projection,
                )
            )
        elif args.command == "activate":
            service.store.activate(args.revision_id)
            output = service.store.get()
        else:
            output = {"revisions": service.store.history()}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
