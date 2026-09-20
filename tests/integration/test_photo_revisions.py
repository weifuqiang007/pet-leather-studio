"""PH07：照片链修订可追溯、篡改拒绝；mold 接缝（kind 分派、input_method 继承、旧 OBJ 兼容）。"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from photo_stubs import StubInference, StubRegistry, make_mask_png, make_photo_png

from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.domain.molds import MoldParameters
from pet_leather_studio.domain.photo_relief import MaskMethod
from pet_leather_studio.infrastructure.photo_io import PhotoIO
from pet_leather_studio.infrastructure.revisions import RevisionStore


def build_photo_service(root: Path, mode: str = "ok") -> tuple[RevisionStore, PhotoWorkbench]:
    store = RevisionStore(root)
    return store, PhotoWorkbench(store, PhotoIO(), StubInference(mode), StubRegistry())


def build_chain(tmp_path: Path, mode: str = "ok") -> tuple[RevisionStore, PhotoWorkbench, dict]:
    store, service = build_photo_service(tmp_path / "proj", mode)
    photo = service.import_photo(make_photo_png(tmp_path / "pet.png"))
    mask = service.save_mask(
        photo.revision_id, make_mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL, notes="集成测试"
    )
    depth = service.estimate_depth(photo.revision_id, mask.revision_id)
    return store, service, {"photo": photo, "mask": mask, "depth": depth}


def test_photo_chain_traceability_and_verify(tmp_path: Path) -> None:
    store, _, chain = build_chain(tmp_path)
    photo_id, mask_id, depth_id = (chain[key].revision_id for key in ("photo", "mask", "depth"))

    photo_manifest = store.get(photo_id)
    assert photo_manifest["kind"] == "photo" and photo_manifest["parent_id"] is None
    assert photo_manifest["visual_review"] == "pending"
    assert set(photo_manifest["files"]) == {"original.png", "work.png"}

    mask_manifest = store.get(mask_id)
    assert mask_manifest["kind"] == "mask"
    assert mask_manifest["parent_id"] == photo_id and mask_manifest["photo_id"] == photo_id
    assert mask_manifest["mask_method"] == "manual" and mask_manifest["notes"] == "集成测试"

    depth_manifest = store.get(depth_id)
    assert depth_manifest["kind"] == "depth"
    assert depth_manifest["parent_id"] == mask_id
    assert depth_manifest["photo_id"] == photo_id and depth_manifest["mask_id"] == mask_id
    assert depth_manifest["depth_semantics"] == "relative_larger_nearer"
    assert any("相机视角" in w for w in depth_manifest["warnings"])
    assert depth_manifest["manufacturing_validated"] is False
    with np.load(store.directory(depth_id) / "depth.npz") as data:
        assert data["depth"].shape == (60, 80) and data["valid"].any()

    for revision_id in (photo_id, mask_id, depth_id):
        store.verify(revision_id)  # 链上全部可校验
    assert store.get()["id"] == depth_id  # 发布后 active 前移


def test_save_mask_rejects_non_photo_parent(tmp_path: Path) -> None:
    store, service = build_photo_service(tmp_path / "proj")
    photo = service.import_photo(make_photo_png(tmp_path / "pet.png"))
    mask = service.save_mask(
        photo.revision_id, make_mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL
    )
    with pytest.raises(ValueError, match="不是 photo"):
        service.save_mask(
            mask.revision_id, make_mask_png(tmp_path / "mask2.png"), MaskMethod.MANUAL
        )


def test_mask_from_other_photo_rejected(tmp_path: Path) -> None:
    store, service = build_photo_service(tmp_path / "proj")
    photo_a = service.import_photo(make_photo_png(tmp_path / "a.png"))
    photo_b = service.import_photo(make_photo_png(tmp_path / "b.png"))
    mask_a = service.save_mask(
        photo_a.revision_id, make_mask_png(tmp_path / "m.png"), MaskMethod.MANUAL
    )
    with pytest.raises(ValueError, match="不一致"):
        service.estimate_depth(photo_b.revision_id, mask_a.revision_id)
    assert len(store.history()) == 3  # 不产生 depth 修订


@pytest.mark.parametrize("target", ["photo", "mask"])
def test_estimate_depth_rejects_tampered_upstream(tmp_path: Path, target: str) -> None:
    store, _, chain = build_chain(tmp_path)
    if target == "photo":
        victim, file_name = chain["photo"].revision_id, "work.png"
    else:
        victim, file_name = chain["mask"].revision_id, "mask.png"
    with (store.directory(victim) / file_name).open("ab") as stream:
        stream.write(b"\x00tamper")

    with pytest.raises(ValueError, match="文件已变化"):
        PhotoWorkbench(store, PhotoIO(), StubInference(), StubRegistry()).estimate_depth(
            chain["photo"].revision_id, chain["mask"].revision_id
        )
    assert len(store.history()) == 3  # 校验失败不发布


class FakeGeometry:
    def import_master(self, source, destination):
        (destination / "master.vtp").write_text("test-master")
        return {"algorithm": "fake-test-only"}

    def generate(self, source, destination, parameters):
        (destination / "male.stl").write_text(str(parameters.gap_mm))
        return {"algorithm": "fake-test-only"}


def test_mold_seam_rejects_photo_chain_and_inherits_input_method(tmp_path: Path) -> None:
    store = RevisionStore(tmp_path / "proj")
    photos = PhotoWorkbench(store, PhotoIO(), StubInference(), StubRegistry())
    molds = MoldWorkbench(store, FakeGeometry())

    photo = photos.import_photo(make_photo_png(tmp_path / "pet.png"))
    mask = photos.save_mask(
        photo.revision_id, make_mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL
    )
    photos.estimate_depth(photo.revision_id, mask.revision_id)  # active = depth
    for revision_id in (None, photo.revision_id, mask.revision_id):
        if revision_id is not None:
            store.activate(revision_id)
        with pytest.raises(ValueError, match="master 母版"):
            molds.generate(MoldParameters(accept_top_projection=True))

    # 旧 OBJ 导入路径（source_import）保持原行为
    master = molds.import_master(Path("unused"))
    mold = molds.generate(MoldParameters(accept_top_projection=True))
    assert store.get(mold["id"])["input_method"] == "source_import"
    assert store.get(mold["id"])["master_id"] == master["id"]

    # photo_reconstruction 母版（P2 由 depth 生成；此处验证继承机制本身）
    stage = store.begin()
    shutil.copyfile(store.directory(master["id"]) / "master.vtp", stage / "master.vtp")
    reconstructed = store.publish(
        stage,
        {
            "kind": "master",
            "parent_id": mask.revision_id,
            "input_method": "photo_reconstruction",
            "visual_review": "pending",
        },
    )
    store.activate(reconstructed["id"])
    photo_mold = molds.generate(MoldParameters(accept_top_projection=True))
    assert store.get(photo_mold["id"])["input_method"] == "photo_reconstruction"
    assert store.get(photo_mold["id"])["master_id"] == reconstructed["id"]


def test_mold_generate_rejects_unknown_kind(tmp_path: Path) -> None:
    store = RevisionStore(tmp_path / "proj")
    molds = MoldWorkbench(store, FakeGeometry())
    stage = store.begin()
    (stage / "note.txt").write_text("mystery")
    mystery = store.publish(stage, {"kind": "mystery"})
    store.activate(mystery["id"])
    with pytest.raises(ValueError, match="不能生成模具"):
        molds.generate(MoldParameters(accept_top_projection=True))


def test_master_without_input_method_refused(tmp_path: Path) -> None:
    store = RevisionStore(tmp_path / "proj")
    molds = MoldWorkbench(store, FakeGeometry())
    master = molds.import_master(Path("unused"))
    with store.connect() as con:  # 模拟旧数据缺 input_method 字段
        data = store.get(master["id"])
        data.pop("input_method")
        con.execute(
            "UPDATE revisions SET data=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), master["id"]),
        )
    store.activate(master["id"])
    with pytest.raises(ValueError, match="input_method"):
        molds.generate(MoldParameters(accept_top_projection=True))
