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
    master = sub.add_parser("build-master")
    master.add_argument("--depth", required=True)
    master.add_argument("--width-mm", type=float, default=60.0)
    master.add_argument(
        "--height-mode", choices=["explicit_depth", "reference_ratio"], default="explicit_depth"
    )
    master.add_argument("--depth-mm", type=float, default=2.0)
    master.add_argument("--profile", default=None)
    master.add_argument("--smoothing-mm", type=float, default=1.5)
    master.add_argument(
        "--detail-strength", type=float, default=0.60, help="结构细节强度 0–1（0=关）"
    )
    master.add_argument("--base-mm", type=float, default=3.0)
    master.add_argument("--falloff-mm", type=float, default=2.5, help="蒙版边缘过渡带宽 mm（0=关）")
    master.add_argument(
        "--adjustment",
        action="append",
        default=None,
        metavar="PNG:OFFSET:TRANSITION[:LABEL]",
        help="局部调整，可重复；OFFSET/TRANSITION 单位 mm",
    )
    calibrate = sub.add_parser("calibrate-reference")
    calibrate.add_argument("--obj", type=Path, required=True)
    calibrate.add_argument("--percentile", type=float, default=99.0)
    calibrate.add_argument("--region", default=None, help="xmin,xmax,ymin,ymax（源单位）")
    calibrate.add_argument("--source-units", default="assumed_mm")
    calibrate.add_argument("--root", type=Path, default=None, help="标定存储目录")
    sub.add_parser("photo-profiles").add_argument("--root", type=Path, default=None)
    sub.add_parser("photo-history")
    leather = sub.add_parser("generate-leather-molds")
    leather.add_argument("--master", required=True)
    leather.add_argument("--leather-thickness-mm", type=float, default=2.0)
    leather.add_argument("--compression-allowance-mm", type=float, default=0.15)
    leather.add_argument("--min-clearance-mm", type=float, default=0.3)
    leather.add_argument("--backing-mm", type=float, default=5.0)
    leather.add_argument("--edge-margin-mm", type=float, default=4.0)
    leather.add_argument("--max-plate-mm", type=float, default=120.0)
    leather.add_argument("--sampling-feature-mm", type=float, default=0.2)
    leather.add_argument("--sampling-mode", choices=["native", "resample"], default="native")
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

    if args.command in {
        "photo",
        "import-photo",
        "save-mask",
        "estimate-depth",
        "build-master",
        "generate-leather-molds",
        "calibrate-reference",
        "photo-profiles",
        "photo-history",
    }:
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
            elif args.command == "build-master":
                from dataclasses import asdict

                from pet_leather_studio.domain.photo_relief import (
                    HeightMode,
                    LocalAdjustment,
                    ReliefParameters,
                )

                adjustments: list[LocalAdjustment] = []
                for index, spec in enumerate(args.adjustment or []):
                    parts = spec.split(":")
                    if len(parts) < 3:
                        raise ValueError(
                            f"--adjustment 需要 PNG:OFFSET:TRANSITION[:LABEL] 格式，收到 {spec!r}"
                        )
                    adjustments.append(
                        LocalAdjustment(
                            label=":".join(parts[3:]) or f"调整{index + 1}",
                            region_png=parts[0],
                            offset_mm=float(parts[1]),
                            transition_mm=float(parts[2]),
                        )
                    )
                output = asdict(
                    service.build_master(
                        args.depth,
                        ReliefParameters(
                            width_mm=args.width_mm,
                            depth_mm=args.depth_mm,
                            height_mode=HeightMode(args.height_mode),
                            profile_id=args.profile,
                            smoothing_radius_mm=args.smoothing_mm,
                            detail_strength=args.detail_strength,
                            base_thickness_mm=args.base_mm,
                            falloff_band_mm=args.falloff_mm,
                        ),
                        tuple(adjustments),
                    )
                )
            elif args.command == "generate-leather-molds":
                from dataclasses import asdict

                from pet_leather_studio.bootstrap.workbench import (
                    create_leather_mold_workbench,
                )
                from pet_leather_studio.domain.leather_molds import LeatherMoldParameters

                output = asdict(
                    create_leather_mold_workbench(project).generate(
                        args.master,
                        LeatherMoldParameters(
                            leather_thickness_mm=args.leather_thickness_mm,
                            compression_allowance_mm=args.compression_allowance_mm,
                            min_clearance_mm=args.min_clearance_mm,
                            backing_mm=args.backing_mm,
                            edge_margin_mm=args.edge_margin_mm,
                            max_plate_mm=args.max_plate_mm,
                            sampling_feature_mm=args.sampling_feature_mm,
                            sampling_mode=args.sampling_mode,
                        ),
                    )
                )
            elif args.command == "calibrate-reference":
                from pet_leather_studio.infrastructure.reference_profile import (
                    ReferenceProfileStore,
                    measure_reference,
                )

                region = None
                if args.region:
                    values = [float(value) for value in args.region.split(",")]
                    if len(values) != 4:
                        raise ValueError("--region 必须是 xmin,xmax,ymin,ymax 四个数")
                    region = (values[0], values[1], values[2], values[3])
                profile = measure_reference(args.obj, args.percentile, region, args.source_units)
                saved = ReferenceProfileStore(
                    args.root or environment.data_root() / "profiles"
                ).save(profile)
                output = {"saved": str(saved), "profile": profile.to_json_dict()}
            elif args.command == "photo-profiles":
                from pet_leather_studio.infrastructure.reference_profile import (
                    ReferenceProfileStore,
                )

                store = ReferenceProfileStore(args.root or environment.data_root() / "profiles")
                output = {"profiles": [item.to_json_dict() for item in store.list_profiles()]}
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
