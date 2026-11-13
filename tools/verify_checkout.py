"""Clean source-copy verification with a new venv, no key and pinned wheel install.

Usage: python3 tools/verify_checkout.py --wheels /tmp/access-intake-wheels
Without --wheels, pip downloads the pinned packages through its configured index.
Source is copied with no existing DB, virtualenv or Git metadata.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('API_KEY', None)
    with tempfile.TemporaryDirectory(prefix='intake-clean-') as directory:
        clean = Path(directory)
        for name in ('access_intake', 'materials', 'tests', 'tools'):
            shutil.copytree(root/name, clean/name, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('README.md','requirements.lock','snapshot.schema.json'):
            shutil.copy2(root/name, clean/name)
        def run(*command):
            print('$ ' + ' '.join(map(str,command)), flush=True)
            subprocess.run(list(map(str,command)), cwd=clean, env=env, check=True)
        run(sys.executable, '-m', 'venv', '--without-pip', '.venv')
        install = [sys.executable, '-m', 'pip', '--python', clean/'.venv/bin/python', 'install', '-r', 'requirements.lock', '--disable-pip-version-check']
        if args.wheels:
            install += ['--no-index', '--find-links', str(Path(args.wheels).resolve())]
        run(*install)
        python = clean/'.venv/bin/python'
        run(python, '-m', 'unittest', 'discover', '-s', 'tests', '-v')
        def cli(*args):
            run(python, '-m', 'access_intake', *args)
        cli('intake','materials/requests','--provider','mock')
        cli('intake','tests/fixtures/exports/IT-001-paraphrase.json','--provider','mock')
        cli('queue')
        cli('pending')
        cli('resume')
        cli('export')
        cli('accuracy')
        cli('request-evidence')
        rows = [json.loads(line) for line in (clean/'deliverables/extractions.jsonl').read_text().splitlines()]
        assert len(rows) == 21
        assert all(r['response_source'] == 'mock' and r['error'] is None for r in rows)
        first = {r['document_id']: r['attempt_id'] for r in rows}
        cli('intake','materials/requests','--provider','mock')
        cli('export')
        rows = [json.loads(line) for line in (clean/'deliverables/extractions.jsonl').read_text().splitlines()]
        assert first == {r['document_id']: r['attempt_id'] for r in rows}, 'Unchanged run created attempts'
        cli('retry','IT-001.json')
        cli('history','IT-001.json')
        print('CLEAN CHECKOUT CHECK PASSED: setup, tests, intake, queue, pending, resume, export, accuracy, evidence, reuse and retry/history.',flush=True)


if __name__ == '__main__':
    main()
