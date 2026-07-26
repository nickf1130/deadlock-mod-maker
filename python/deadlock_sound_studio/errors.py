from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StudioError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def as_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def validation_error(message: str, **details: Any) -> StudioError:
    return StudioError("VALIDATION_FAILED", message, details)


def capability_error(message: str, **details: Any) -> StudioError:
    return StudioError("CAPABILITY_UNAVAILABLE", message, details)
