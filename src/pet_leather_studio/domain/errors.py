"""领域错误码（PRD 11.3）。

用户错误（可恢复、可提示）与程序缺陷（bug）分开表示。
"""

from __future__ import annotations


class PetLeatherError(Exception):
    """项目错误基类。code 为稳定错误码，供 UI 与日志引用。"""

    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidImageError(PetLeatherError):
    code = "INVALID_IMAGE"


class UnitUnconfirmedError(PetLeatherError):
    code = "UNIT_UNCONFIRMED"


class InvalidMeshError(PetLeatherError):
    code = "INVALID_MESH"


class ResourceMissingError(PetLeatherError):
    code = "RESOURCE_MISSING"


class ToolUnavailableError(PetLeatherError):
    code = "TOOL_UNAVAILABLE"


class JobCancelledError(PetLeatherError):
    code = "JOB_CANCELLED"


class ScanCoverageLowError(PetLeatherError):
    code = "SCAN_COVERAGE_LOW"


class UnsupportedOperationError(PetLeatherError):
    """能力未配置/未实现时显式拒绝，不允许以占位结果冒充成功。"""

    code = "UNSUPPORTED_OPERATION"
