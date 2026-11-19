import sqlite3
from contextlib import contextmanager

from batch.trigger_manifest import TriggerManifest


@contextmanager
def write_transaction(db: sqlite3.Connection):
    if db.in_transaction:
        raise RuntimeError("write requires an idle database connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


class ManifestCatalog:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def initialize(self) -> None:
        with write_transaction(self._db):
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS batch_manifests (
                    batch_id TEXT NOT NULL PRIMARY KEY
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS manifest_triggers (
                    batch_id TEXT NOT NULL REFERENCES batch_manifests(batch_id),
                    trigger_id TEXT NOT NULL,
                    position INTEGER NOT NULL CHECK(position >= 0),
                    PRIMARY KEY(batch_id, trigger_id),
                    UNIQUE(batch_id, position)
                )
            """)

    def get(self, batch_id: str) -> TriggerManifest | None:
        rows = self._db.execute("""
            SELECT t.trigger_id
            FROM batch_manifests AS b
            LEFT JOIN manifest_triggers AS t ON t.batch_id = b.batch_id
            WHERE b.batch_id = ?
            ORDER BY t.position
        """, (batch_id,)).fetchall()
        if not rows:
            return None
        return TriggerManifest(batch_id, tuple(row[0] for row in rows if row[0] is not None))

    def insert_or_read(self, manifest: TriggerManifest) -> TriggerManifest:
        with write_transaction(self._db):
            existing = self.get(manifest.batch_id)
            if existing is not None:
                return existing
            self._db.execute(
                "INSERT INTO batch_manifests(batch_id) VALUES (?)", (manifest.batch_id,)
            )
            self._db.executemany(
                "INSERT INTO manifest_triggers(batch_id, trigger_id, position) VALUES (?, ?, ?)",
                ((manifest.batch_id, trigger, index)
                 for index, trigger in enumerate(manifest.ordered_triggers)),
            )
        return manifest
