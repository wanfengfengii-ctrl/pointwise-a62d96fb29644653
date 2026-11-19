from collections.abc import Sequence

from batch.catalog import ManifestCatalog
from batch.identity import TriggerKey, require_identifier
from batch.trigger_manifest import TriggerManifest
from batch.validation import require_same_manifest, validate_registration


class UnknownBatch(LookupError):
    pass


def register(catalog: ManifestCatalog, batch_id: str, triggers: Sequence[str]) -> TriggerManifest:
    requested = validate_registration(batch_id, triggers)
    stored = catalog.insert_or_read(requested)
    require_same_manifest(stored, requested)
    return stored


def get_registered_batch(catalog: ManifestCatalog, batch_id: str) -> TriggerManifest:
    manifest = catalog.get(require_identifier(batch_id, "batch_id"))
    if manifest is None:
        raise UnknownBatch(batch_id)
    return manifest


def require_registered_trigger(catalog: ManifestCatalog, batch_id: str, trigger_id: str) -> TriggerKey:
    manifest = get_registered_batch(catalog, batch_id)
    return manifest.key_for(require_identifier(trigger_id, "trigger_id"))
