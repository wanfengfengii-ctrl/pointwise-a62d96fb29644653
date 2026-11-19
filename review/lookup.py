from archive.result_store import ResultStore
from batch.catalog import ManifestCatalog
from batch.registration import require_registered_trigger
from review.provenance import ReviewResult, format_review_result


def lookup(
    catalog: ManifestCatalog, results: ResultStore, batch_id: str, trigger_id: str,
) -> ReviewResult | None:
    key = require_registered_trigger(catalog, batch_id, trigger_id)
    result = results.read_published(key)
    return None if result is None else format_review_result(result)
