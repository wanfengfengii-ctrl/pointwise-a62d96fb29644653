import sqlite3

from batch.catalog import write_transaction
from batch.identity import LaneId
from source.slot import SlotToken, StaleSlot


class RecordingConflict(ValueError):
    pass


class RecordingNotBound(LookupError):
    pass


class LaneProgressStore:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def initialize(self) -> None:
        with write_transaction(self._db):
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS recording_bindings (
                    batch_id TEXT NOT NULL PRIMARY KEY REFERENCES batch_manifests(batch_id),
                    recording_id TEXT NOT NULL
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS lane_positions (
                    batch_id TEXT NOT NULL REFERENCES recording_bindings(batch_id),
                    lane TEXT NOT NULL CHECK(lane IN ('left', 'right')),
                    position INTEGER NOT NULL CHECK(position >= 0),
                    PRIMARY KEY(batch_id, lane)
                )
            """)

    def bind_recording(self, batch_id: str, recording_id: str) -> None:
        with write_transaction(self._db):
            row = self._db.execute(
                "SELECT recording_id FROM recording_bindings WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if row is not None:
                if row[0] != recording_id:
                    raise RecordingConflict(f"another recording is bound to {batch_id!r}")
                return
            self._db.execute(
                "INSERT INTO recording_bindings(batch_id, recording_id) VALUES (?, ?)",
                (batch_id, recording_id),
            )
            self._db.executemany(
                "INSERT INTO lane_positions(batch_id, lane, position) VALUES (?, ?, 0)",
                ((batch_id, lane.value) for lane in LaneId),
            )

    def read_position(self, batch_id: str, recording_id: str, lane: LaneId) -> int:
        row = self._db.execute("""
            SELECT p.position FROM lane_positions AS p
            JOIN recording_bindings AS r ON r.batch_id = p.batch_id
            WHERE p.batch_id = ? AND r.recording_id = ? AND p.lane = ?
        """, (batch_id, recording_id, lane.value)).fetchone()
        if row is None:
            raise RecordingNotBound((batch_id, recording_id, lane.value))
        return row[0]

    def advance_current(self, token: SlotToken) -> int:
        with write_transaction(self._db):
            cursor = self._db.execute("""
                UPDATE lane_positions SET position = position + 1
                WHERE batch_id = ? AND lane = ? AND position = ?
                  AND EXISTS (
                    SELECT 1 FROM recording_bindings
                    WHERE batch_id = ? AND recording_id = ?
                  )
            """, (token.batch_id, token.lane.value, token.position,
                  token.batch_id, token.recording_id))
            if cursor.rowcount != 1:
                raise StaleSlot("release no longer identifies the current position")
        return token.position + 1
