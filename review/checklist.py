from dataclasses import dataclass

from archive.result_store import ResultStore
from batch.catalog import ManifestCatalog
from batch.registration import get_registered_batch


@dataclass(frozen=True)
class ChecklistEntry:
    trigger_id: str
    status: str
    result_id: int | None


def checklist(catalog: ManifestCatalog, results: ResultStore, batch_id: str) -> tuple[ChecklistEntry, ...]:
    manifest = get_registered_batch(catalog, batch_id)
    published = results.read_published_batch(manifest.batch_id)
    entries = []
    for trigger_id in manifest.ordered_triggers:
        result = published.get(trigger_id)
        if result is None:
            entries.append(ChecklistEntry(trigger_id, "pending", None))
        else:
            entries.append(ChecklistEntry(trigger_id, "published", result.result_id))
    return tuple(entries)
