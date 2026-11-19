from dataclasses import dataclass
from enum import Enum


class LaneId(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class TriggerKey:
    batch_id: str
    trigger_id: str


def require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be a nonblank identifier without NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must be valid UTF-8") from error
    return value
