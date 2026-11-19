from archive.contrast import compute_contrast
from archive.evidence import EvidenceLedger
from archive.pairing import pair_for_trigger
from archive.result_store import PublishedResult, ResultStore
from batch.catalog import ManifestCatalog
from batch.registration import require_registered_trigger


def publish(
    catalog: ManifestCatalog,
    evidence: EvidenceLedger,
    results: ResultStore,
    batch_id: str,
    trigger_id: str,
) -> PublishedResult | None:
    key = require_registered_trigger(catalog, batch_id, trigger_id)
    existing = results.read_published(key)
    if existing is not None:
        return existing
    pair = pair_for_trigger(evidence, key)
    if pair is None:
        return None
    return results.commit_result(pair, compute_contrast(pair))
