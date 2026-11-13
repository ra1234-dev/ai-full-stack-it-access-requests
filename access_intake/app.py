"""Bounded independent workers over durable source revisions."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from .exports import read_exports
from .extraction import extract_document
from .routing import route

ROOT = Path(__file__).resolve().parents[1]


def processing_settings(provider, extra=None):
    # Conservative invalidation: all runtime code, schema, policy and provider configuration.
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'access_intake').glob('*.py')) + [ROOT / 'snapshot.schema.json', ROOT / 'materials/office-policy.md']:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    config = provider.configuration() if hasattr(provider, 'configuration') else {'provider': provider.response_source}
    return dict(config, implementation_sha256=digest.hexdigest(), overrides=extra or {})


def run_pending(store, provider=None, *, workers=4, attempt_ids=None, provider_factory=None):
    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32.')
    attempts = attempt_ids if attempt_ids is not None else [r['attempt_id'] for r in store.pending()]
    def work(attempt):
        row = store.attempt(attempt)
        config = json.loads(row['settings'])
        source = provider_factory(config) if provider_factory else provider
        if source is None:
            raise ValueError('Provider required to resume work.')
        token = store.claim(attempt, lease_seconds=getattr(source, 'timeout', 60) + 30)
        if not token:
            return
        document = store.document(attempt)
        result = route(document, extract_document(document, source, attempt_id=str(attempt)))
        result['processing_settings'] = config
        result['settings_sha256'] = hashlib.sha256(row['settings'].encode()).hexdigest()
        if result['error']:
            result['error']['retry_command'] = store.retry_command(document.document_id)
        store.finish(attempt, token, result)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map yields in order, but each worker commits independently before returning.
        list(pool.map(work, attempts))


def run_intake(store, paths, provider, *, workers=4, force=False, settings=None):
    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32.')
    documents = read_exports(paths)
    config = processing_settings(provider, settings)
    attempts = [store.register(document, config, force=force) for document in documents]
    run_pending(store, provider, workers=workers, attempt_ids=attempts)
    return store.current()
