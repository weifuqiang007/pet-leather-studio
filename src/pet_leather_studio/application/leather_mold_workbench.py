"""照片母版 → 皮革阴阳模修订用例（MOLD-PAIR M1）；依赖注入端口。

同一照片工程库内验证 photo/mask/depth/master 四级上游未被篡改，继承
visual_review/warnings（几何验收不替代视觉复核），原子发布 kind="mold_pair"；
失败/取消不产生成功修订。legacy kind="mold" 外部导入路径不受影响。
"""

from __future__ import annotations

from pet_leather_studio.domain.leather_molds import (
    LeatherMoldGeometryPort,
    LeatherMoldParameters,
)
from pet_leather_studio.domain.molds import RevisionPort
from pet_leather_studio.domain.photo_relief import RevisionSummary

PENDING_REVIEW_WARNING = (
    "源母版 visual_review=pending：几何配对验收不替代视觉复核，"
    "模具不得在母版获用户确认前进入实物试压"
)


class LeatherMoldWorkbench:
    def __init__(self, store: RevisionPort, geometry: LeatherMoldGeometryPort) -> None:
        self.store = store
        self.geometry = geometry

    def generate(self, master_id: str, parameters: LeatherMoldParameters) -> RevisionSummary:
        """照片母版 → mold_pair 修订（几何校验失败不发布）。"""
        master = self.store.get(master_id)
        if master.get("kind") != "master":
            raise ValueError(
                f"修订 {master_id[:8]} 不是 master（{master.get('kind')}），不能生成皮革模具"
            )
        if master.get("input_method") != "photo_reconstruction":
            raise ValueError(
                "只支持照片重建母版（input_method=photo_reconstruction）；"
                "外部导入母版请走 legacy 模具工作台（generate 命令）"
            )
        parameters.validate()
        photo_id = master.get("photo_id")
        mask_id = master.get("mask_id")
        depth_id = master.get("depth_id")
        upstreams = [revision_id for revision_id in (photo_id, mask_id, depth_id) if revision_id]
        for revision_id in [*upstreams, master_id]:
            self.store.verify(revision_id)

        stage = self.store.begin()
        try:
            metadata = self.geometry.generate_leather_molds(
                heightfield_npz=self.store.directory(master_id) / "heightfield.npz",
                master_metadata=master,
                parameters=parameters,
                stage=stage,
            )
            inherited: list[str] = []
            if master.get("visual_review") != "approved":
                inherited.append(PENDING_REVIEW_WARNING)
            inherited.extend(f"母版警告继承：{warning}" for warning in master.get("warnings", []))
            metadata["warnings"] = [*metadata.get("warnings", []), *inherited]
            metadata.update(
                kind="mold_pair",
                parent_id=master_id,
                photo_id=photo_id,
                mask_id=mask_id,
                depth_id=depth_id,
                master_id=master_id,
                input_method="photo_reconstruction",
                master_visual_review=master.get("visual_review"),
                visual_review="pending",
                manufacturing_validated=False,
            )
            for revision_id in [*upstreams, master_id]:  # 发布前复验上游未被篡改
                self.store.verify(revision_id)
            published = self.store.publish(stage, metadata)
            return RevisionSummary.from_metadata(published)
        except BaseException:
            self.store.discard(stage)
            raise
