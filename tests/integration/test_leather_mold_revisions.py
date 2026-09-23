"""MOLD-PAIR M1 集成（修订链）：mold_pair 发布、四上游防篡改、pending 继承。

照片工程同一 RevisionStore 内 kind="mold_pair"：parent=master、三级照片链 id
继承、发布前复验（篡改拒绝）、visual_review=pending 与母版警告继承、
几何失败/legacy 母版不发布；CLI generate-leather-molds 返回码同口径。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from photo_stubs import StubInference, StubRegistry, make_mask_png, make_photo_png

from pet_leather_studio.application.leather_mold_workbench import (
    PENDING_REVIEW_WARNING,
    LeatherMoldWorkbench,
)
from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.domain.leather_molds import (
    EXTERNAL_JIG_NOTE,
    LeatherMoldParameters,
)
from pet_leather_studio.domain.photo_relief import MaskMethod, ReliefParameters
from pet_leather_studio.infrastructure.leather_mold_geometry import LeatherMoldGeometry
from pet_leather_studio.infrastructure.photo_geometry import PhotoGeometry
from pet_leather_studio.infrastructure.photo_io import PhotoIO
from pet_leather_studio.infrastructure.reference_profile import ReferenceProfileStore
from pet_leather_studio.infrastructure.revisions import RevisionStore

MASTER_PARAMETERS = ReliefParameters(width_mm=40.0, depth_mm=1.5, base_thickness_mm=2.0)


def build_chain(tmp_path: Path) -> tuple[RevisionStore, PhotoWorkbench, dict]:
    store = RevisionStore(tmp_path / "proj")
    service = PhotoWorkbench(
        store,
        PhotoIO(),
        StubInference(),
        StubRegistry(),
        PhotoGeometry(),
        ReferenceProfileStore(tmp_path / "profiles"),
    )
    photo = service.import_photo(make_photo_png(tmp_path / "pet.png"))
    mask = service.save_mask(
        photo.revision_id, make_mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL
    )
    depth = service.estimate_depth(photo.revision_id, mask.revision_id)
    master = service.build_master(depth.revision_id, MASTER_PARAMETERS)
    return store, service, {"photo": photo, "mask": mask, "depth": depth, "master": master}


def _staging_empty(store: RevisionStore) -> bool:
    staging = store.root / "staging"
    return not staging.exists() or not any(staging.iterdir())


def test_generate_publishes_mold_pair_revision(tmp_path: Path) -> None:
    store, _, chain = build_chain(tmp_path)
    master_id = chain["master"].revision_id
    pair = LeatherMoldWorkbench(store, LeatherMoldGeometry()).generate(
        master_id, LeatherMoldParameters()
    )

    manifest = store.get(pair.revision_id)
    assert manifest["kind"] == "mold_pair"
    assert manifest["parent_id"] == master_id
    assert manifest["master_id"] == master_id
    assert manifest["photo_id"] == chain["photo"].revision_id
    assert manifest["mask_id"] == chain["mask"].revision_id
    assert manifest["depth_id"] == chain["depth"].revision_id
    assert manifest["input_method"] == "photo_reconstruction"
    assert manifest["visual_review"] == "pending"  # 几何验收不替代视觉复核
    assert manifest["manufacturing_validated"] is False
    assert manifest["master_visual_review"] == "pending"
    assert PENDING_REVIEW_WARNING in manifest["warnings"]
    assert EXTERNAL_JIG_NOTE in manifest["warnings"]
    assert {"male.stl", "female.obj", "mold_pair.npz", "README.txt"} <= set(manifest["files"])
    store.verify(pair.revision_id)  # 发布产物 hash 完整
    assert store.get()["id"] == pair.revision_id  # active 前移
    assert _staging_empty(store)


@pytest.mark.parametrize(
    "target,file_name",
    [("master", "heightfield.npz"), ("photo", "work.png"), ("depth", "depth.npz")],
)
def test_generate_rejects_tampered_upstream(tmp_path: Path, target: str, file_name: str) -> None:
    store, _, chain = build_chain(tmp_path)
    victim = chain[target].revision_id
    with (store.directory(victim) / file_name).open("ab") as stream:
        stream.write(b"\x00tamper")

    with pytest.raises(ValueError, match="文件已变化"):
        LeatherMoldWorkbench(store, LeatherMoldGeometry()).generate(
            chain["master"].revision_id, LeatherMoldParameters()
        )
    assert len(store.history()) == 4  # 校验失败不发布
    assert store.get()["id"] == chain["master"].revision_id
    assert _staging_empty(store)


def test_generate_rejects_legacy_source_import_master(tmp_path: Path) -> None:
    store = RevisionStore(tmp_path / "proj")

    class FakeMoldGeometry:
        def import_master(self, source, destination):
            (destination / "master.vtp").write_text("legacy")
            return {"algorithm": "fake-test-only"}

        def generate(self, source, destination, parameters):
            (destination / "male.stl").write_text("legacy")
            return {"algorithm": "fake-test-only"}

    molds = MoldWorkbench(store, FakeMoldGeometry())
    imported = molds.import_master(Path("unused"))  # kind=master, source_import

    with pytest.raises(ValueError, match="photo_reconstruction"):
        LeatherMoldWorkbench(store, LeatherMoldGeometry()).generate(
            imported["id"], LeatherMoldParameters()
        )
    assert len(store.history()) == 1


def test_generate_discards_staging_on_geometry_failure(tmp_path: Path) -> None:
    store, _, chain = build_chain(tmp_path)

    class ExplodingGeometry:
        def generate_leather_molds(self, heightfield_npz, master_metadata, parameters, stage):
            (stage / "partial.txt").write_text("boom")
            raise ValueError("几何校验故意失败")

    with pytest.raises(ValueError, match="几何校验故意失败"):
        LeatherMoldWorkbench(store, ExplodingGeometry()).generate(
            chain["master"].revision_id, LeatherMoldParameters()
        )
    assert len(store.history()) == 4  # 失败不发布
    assert _staging_empty(store)  # staging 已整目录回收


def test_approved_master_omits_pending_warning_but_inherits_master_warnings(
    tmp_path: Path,
) -> None:
    store, _, chain = build_chain(tmp_path)
    master_id = chain["master"].revision_id
    with store.connect() as con:  # 模拟用户在 GUI 勾选通过 + 母版自带警告
        data = store.get(master_id)
        data["visual_review"] = "approved"
        data["warnings"] = ["母版测试警告"]
        con.execute(
            "UPDATE revisions SET data=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), master_id),
        )

    pair = LeatherMoldWorkbench(store, LeatherMoldGeometry()).generate(
        master_id, LeatherMoldParameters()
    )
    manifest = store.get(pair.revision_id)
    assert manifest["master_visual_review"] == "approved"
    assert PENDING_REVIEW_WARNING not in manifest["warnings"]
    assert "母版警告继承：母版测试警告" in manifest["warnings"]


def test_cli_generate_leather_molds_return_codes(tmp_path: Path) -> None:
    store, _, chain = build_chain(tmp_path)
    project = str(tmp_path / "proj")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pet_leather_studio",
            "--project",
            project,
            "generate-leather-molds",
            "--master",
            chain["master"].revision_id,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["kind"] == "mold_pair" and payload["parent_id"] == chain["master"].revision_id

    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "pet_leather_studio",
            "--project",
            project,
            "generate-leather-molds",
            "--master",
            "no-such-revision",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert missing.returncode == 1
    assert "error" in json.loads(missing.stderr)
