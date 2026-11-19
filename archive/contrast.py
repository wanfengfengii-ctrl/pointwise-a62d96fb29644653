from dataclasses import dataclass

from archive.pairing import PairedEvidence
from source.plate import validate_reading


@dataclass(frozen=True)
class Contrast:
    left: int
    right: int
    difference: int


def compute_contrast(pair: PairedEvidence) -> Contrast:
    left = validate_reading(pair.left.reading)
    right = validate_reading(pair.right.reading)
    return Contrast(left, right, right - left)
