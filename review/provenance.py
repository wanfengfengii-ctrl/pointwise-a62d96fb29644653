from dataclasses import dataclass

from archive.result_store import PublishedResult
from source.plate import PlateOrigin


@dataclass(frozen=True)
class ReviewResult:
    result_id: int
    batch_id: str
    trigger_id: str
    left_reading: int
    right_reading: int
    difference: int
    left_origin: PlateOrigin
    right_origin: PlateOrigin


def format_review_result(result: PublishedResult) -> ReviewResult:
    return ReviewResult(
        result.result_id,
        result.key.batch_id,
        result.key.trigger_id,
        result.contrast.left,
        result.contrast.right,
        result.contrast.difference,
        result.left_origin,
        result.right_origin,
    )
