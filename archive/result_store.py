import sqlite3
from dataclasses import dataclass

from archive.contrast import Contrast
from archive.pairing import PairedEvidence
from batch.catalog import write_transaction
from batch.identity import LaneId, TriggerKey
from source.plate import PlateOrigin, decode_count, encode_count


@dataclass(frozen=True)
class PublishedResult:
    result_id: int
    key: TriggerKey
    contrast: Contrast
    left_origin: PlateOrigin
    right_origin: PlateOrigin


def _result_from_row(row: tuple) -> PublishedResult:
    result_id, batch_id, trigger_id, left_seq, right_seq, left, right, difference = row
    return PublishedResult(
        result_id,
        TriggerKey(batch_id, trigger_id),
        Contrast(decode_count(left), decode_count(right), decode_count(difference)),
        PlateOrigin(batch_id, LaneId.LEFT, decode_count(left_seq)),
        PlateOrigin(batch_id, LaneId.RIGHT, decode_count(right_seq)),
    )


class ResultStore:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def initialize(self) -> None:
        with write_transaction(self._db):
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS published_results (
                    result_id INTEGER PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    trigger_id TEXT NOT NULL,
                    left_seq TEXT NOT NULL,
                    right_seq TEXT NOT NULL,
                    left_reading TEXT NOT NULL,
                    right_reading TEXT NOT NULL,
                    difference TEXT NOT NULL,
                    UNIQUE(batch_id, trigger_id),
                    FOREIGN KEY(batch_id, trigger_id)
                        REFERENCES manifest_triggers(batch_id, trigger_id)
                )
            """)

    def commit_result(self, pair: PairedEvidence, contrast: Contrast) -> PublishedResult:
        """Commit a complete pair and its computed contrast as one fixed result."""
        with write_transaction(self._db):
            stored = self.read_published(pair.key)
            if stored is not None:
                return stored
            cursor = self._db.execute("""
                INSERT INTO published_results(
                    batch_id, trigger_id, left_seq, right_seq, left_reading, right_reading, difference
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pair.key.batch_id, pair.key.trigger_id,
                  encode_count(pair.left.origin.sequence), encode_count(pair.right.origin.sequence),
                  encode_count(contrast.left), encode_count(contrast.right), encode_count(contrast.difference)))
            result = PublishedResult(cursor.lastrowid, pair.key, contrast, pair.left.origin, pair.right.origin)
        return result

    def read_published(self, key: TriggerKey) -> PublishedResult | None:
        row = self._db.execute("""
            SELECT result_id, batch_id, trigger_id, left_seq, right_seq,
                   left_reading, right_reading, difference
            FROM published_results WHERE batch_id = ? AND trigger_id = ?
        """, (key.batch_id, key.trigger_id)).fetchone()
        return None if row is None else _result_from_row(row)

    def read_published_batch(self, batch_id: str) -> dict[str, PublishedResult]:
        rows = self._db.execute("""
            SELECT result_id, batch_id, trigger_id, left_seq, right_seq,
                   left_reading, right_reading, difference
            FROM published_results WHERE batch_id = ?
        """, (batch_id,)).fetchall()
        return {row[2]: _result_from_row(row) for row in rows}
