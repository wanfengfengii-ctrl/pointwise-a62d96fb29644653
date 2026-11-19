from collections.abc import Sequence

from batch.identity import require_identifier
from batch.trigger_manifest import TriggerManifest


class ManifestConflict(ValueError):
    pass


def validate_registration(batch_id: str, triggers: Sequence[str]) -> TriggerManifest:
    identifier = require_identifier(batch_id, "batch_id")
    if isinstance(triggers, (str, bytes, bytearray)) or not isinstance(triggers, Sequence):
        raise ValueError("triggers must be an ordered sequence of identifiers")
    ordered = tuple(require_identifier(trigger, "trigger_id") for trigger in triggers)
    if len(set(ordered)) != len(ordered):
        raise ValueError("duplicate trigger in manifest")
    return TriggerManifest(identifier, ordered)


def require_same_manifest(stored: TriggerManifest, requested: TriggerManifest) -> None:
    if stored != requested:
        raise ManifestConflict(f"different manifest already registered for {requested.batch_id!r}")
