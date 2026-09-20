"""Local desktop workbench and process-isolated CLI jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pet_leather_studio.bootstrap import environment
from pet_leather_studio.domain.errors import PetLeatherError
from pet_leather_studio.domain.photo_relief import MaskMethod


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
    photo = sub.add_parser("import-photo")
    photo.add_argument("source", type=Path)
    mask = sub.add_parser("save-mask")
    mask.add_argument("--photo", required=True)
    mask.add_argument("--mask", type=Path, required=True)
    mask.add_argument(
        "--method", choices=[m.value for m in MaskMethod], default=MaskMethod.MANUAL.value
    )
    mask.add_argument("--threshold-level", type=int, default=None)
    mask.add_argument("--notes", default=None)
    depth = sub.add_parser("estimate-depth")
    depth.add_argument("--photo", required=True)
    depth.add_argument("--mask", required=True)
    depth.add_argument("--model", default=None)
    sub.add_parser("photo-history")
    prune = sub.add_parser("prune-staging")
    prune.add_argument("--min-age-hours", type=float, default=1.0)
    sub.add_parser("photo")
    return result


def main() -> int:
    environment.apply_local_env()
    environment.ensure_local_dirs()
    args = parser().parse_args()
    if args.command == "doctor":
        print(json.dumps({"root": str(environment.app_root()), "offline": True}))
        return 0
    project = args.project or environment.data_root() / "workspace" / "mold-workbench"

    if args.command in {"photo", "import-photo", "save-mask", "estimate-depth", "photo-history"}:
        project = args.project or environment.data_root() / "workspace" / "photo-workbench"
        from pet_leather_studio.bootstrap.workbench import create_photo_workbench

        service = create_photo_workbench(project)

        if args.command == "photo":
            from PySide6.QtWidgets import QApplication

            from pet_leather_studio.presentation.photo_panel import PhotoWorkbenchWindow

            app = QApplication(sys.argv[:1])
            window = PhotoWorkbenchWindow(service, project)
            window.show()
            return app.exec()
        try:
            if args.command == "import-photo":
                output: object = service.import_photo(args.source)
            elif args.command == "save-mask":
                output = service.save_mask(
                    args.photo,
                    args.mask,
                    MaskMethod(args.method),
                    threshold_level=args.threshold_level,
                    notes=args.notes,
                )
            elif args.command == "estimate-depth":
                output = service.estimate_depth(args.photo, args.mask, args.model)
            else:
                output = {"revisions": service.store.history()}
            print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
            return 0
        except (ValueError, OSError, RuntimeError, PetLeatherError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1

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
        elif args.command == "prune-staging":
            output = {"removed": service.store.prune_staging(args.min_age_hours)}
        else:
            output = {"revisions": service.store.history()}
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0
    except (ValueError, OSError, RuntimeError, PetLeatherError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
