import sqlite3

from batch.catalog import write_transaction
from batch.identity import LaneId, TriggerKey
from source.plate import InvalidPlate, PlateOrigin, RawPlate, decode_count, encode_count


def _plate_from_row(row: tuple) -> RawPlate:
    batch_id, trigger_id, lane, sequence, reading = row
    return RawPlate(
        TriggerKey(batch_id, trigger_id),
        PlateOrigin(batch_id, LaneId(lane), decode_count(sequence)),
        decode_count(reading),
    )


class EvidenceStore:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def initialize(self) -> None:
        with write_transaction(self._db):
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS plate_evidence (
                    batch_id TEXT NOT NULL REFERENCES batch_manifests(batch_id),
                    trigger_id TEXT NOT NULL,
                    lane TEXT NOT NULL CHECK(lane IN ('left', 'right')),
                    original_seq TEXT NOT NULL,
                    reading TEXT NOT NULL,
                    PRIMARY KEY(batch_id, lane, original_seq),
                    UNIQUE(batch_id, trigger_id, lane)
                )
            """)

    def insert_or_read(self, plate: RawPlate) -> RawPlate:
        origin = plate.origin
        with write_transaction(self._db):
            self._db.execute("""
                INSERT INTO plate_evidence(batch_id, trigger_id, lane, original_seq, reading)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (origin.batch_id, plate.key.trigger_id, origin.lane.value,
                  encode_count(origin.sequence), encode_count(plate.reading)))
            stored = self.read_origin(origin)
            if stored != plate:
                raise InvalidPlate("raw origin or trigger lane conflicts with stored evidence")
        return stored

    def read_origin(self, origin: PlateOrigin) -> RawPlate | None:
        row = self._db.execute("""
            SELECT batch_id, trigger_id, lane, original_seq, reading FROM plate_evidence
            WHERE batch_id = ? AND lane = ? AND original_seq = ?
        """, (origin.batch_id, origin.lane.value, encode_count(origin.sequence))).fetchone()
        return None if row is None else _plate_from_row(row)

    def read_trigger(self, key: TriggerKey) -> tuple[RawPlate, ...]:
        rows = self._db.execute("""
            SELECT batch_id, trigger_id, lane, original_seq, reading FROM plate_evidence
            WHERE batch_id = ? AND trigger_id = ? ORDER BY lane
        """, (key.batch_id, key.trigger_id)).fetchall()
        return tuple(_plate_from_row(row) for row in rows)
