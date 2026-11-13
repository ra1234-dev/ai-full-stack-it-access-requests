"""Operator CLI. Run from repository root: python3 -m access_intake --help."""
import argparse
import json
import os
from pathlib import Path
import sys
from .app import run_intake, run_pending, processing_settings
from .providers import FixtureProvider
from .openai_provider import OpenAIProvider, MODEL, ENDPOINT
from .store import Store


def provider_from_config(config):
    if config.get('provider', 'mock') == 'mock':
        return FixtureProvider()
    return OpenAIProvider(api_key=os.environ.get('API_KEY', ''), model=config.get('model', MODEL),
                          endpoint=config.get('endpoint', ENDPOINT), timeout=config.get('timeout', 60),
                          max_output_tokens=config.get('max_output_tokens', 2500))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--db', default=argparse.SUPPRESS)
    parser.add_argument('--db', default='var/intake.sqlite', help='Shared local-host database')
    sub = parser.add_subparsers(dest='command', required=True)
    intake = sub.add_parser('intake', parents=[shared], help='Register and process a batch')
    intake.add_argument('paths', nargs='+')
    for p in (intake,):
        p.add_argument('--provider', choices=['mock', 'openai'], default='mock')
        p.add_argument('--model', default=MODEL)
        p.add_argument('--endpoint', default=ENDPOINT)
        p.add_argument('--timeout', type=float, default=60)
        p.add_argument('--max-output-tokens', type=int, default=2500)
        p.add_argument('--workers', type=int, default=4)
        p.add_argument('--force', action='store_true', help='Create attempts even for unchanged documents')
    for name in ('queue', 'pending'):
        sub.add_parser(name, parents=[shared])
    for name in ('history', 'retry'):
        p = sub.add_parser(name, parents=[shared])
        p.add_argument('document_id')
    p = sub.add_parser('resume', parents=[shared])
    p.add_argument('--workers', type=int, default=4)
    p = sub.add_parser('refresh', parents=[shared], help='Re-extract registered sources with current code/policy/settings')
    p.add_argument('--workers', type=int, default=4)
    p = sub.add_parser('export', parents=[shared])
    p.add_argument('--output', default='deliverables')
    p = sub.add_parser('accuracy', parents=[shared])
    p.add_argument('--output', default='deliverables/accuracy.md')
    p.add_argument('--records', help='Optional exported JSONL to measure instead of database')
    p = sub.add_parser('request-evidence', parents=[shared])
    p.add_argument('--output', default='deliverables/request-evidence.json')
    args = parser.parse_args(argv)
    try:
        if args.command == 'request-evidence':
            example = json.loads(Path('materials/requests/IT-001.json').read_text())['message']
            # Synthetic placeholder only; evidence construction never reads a credential.
            evidence = OpenAIProvider(api_key='evidence-placeholder').evidence(example)
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
            print(str(path))
            return 0
        store = Store(args.db)
        if args.command == 'intake':
            paths = []
            for value in args.paths:
                path = Path(value)
                paths.extend(sorted(path.glob('*.json')) if path.is_dir() else [path])
            provider = provider_from_config(vars(args))
            run_intake(store, paths, provider, workers=args.workers, force=args.force)
            print(json.dumps({'current_records': len(store.current()), 'unfinished': len(store.pending())}))
        elif args.command in ('queue', 'pending', 'history'):
            rows = store.history(args.document_id) if args.command == 'history' else getattr(store, 'current' if args.command == 'queue' else 'pending')()
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        elif args.command == 'resume':
            run_pending(store, workers=args.workers, provider_factory=provider_from_config)
            print(json.dumps({'unfinished': len(store.pending())}))
        elif args.command in ('retry', 'refresh'):
            attempts = [store.latest(args.document_id)] if args.command == 'retry' else [store.latest(r['document_id']) for r in store.current() + store.pending()]
            for attempt in attempts:
                row = store.attempt(attempt)
                provider = provider_from_config(json.loads(row['settings']))
                document = store.document(attempt)
                new = store.register(document, processing_settings(provider), force=True)
                run_pending(store, provider, attempt_ids=[new])
            print(json.dumps({'current_records': len(store.current()), 'unfinished': len(store.pending())}))
        elif args.command == 'export':
            store.export(args.output)
            print(str(Path(args.output).resolve() / 'current'))
        elif args.command == 'accuracy':
            from .accuracy import write_accuracy
            rows = [json.loads(line) for line in Path(args.records).read_text().splitlines()] if args.records else store.current()
            print(json.dumps(write_accuracy(rows, Path(args.output))))
        return 0
    except (ValueError, OSError) as exc:
        # Do not print provider exceptions or credential-bearing values.
        print('Operation failed. Check input paths/configuration and database access. '
              'For extraction failures inspect queue and use its retry_command.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
