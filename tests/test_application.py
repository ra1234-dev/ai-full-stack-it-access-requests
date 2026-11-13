"""Repair acceptance tests: independent policy facts and transactional operations."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from access_intake.exports import read_export
from access_intake.providers import MockProvider, ControlledResponse

ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / 'tests/mock_responses'


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'state.sqlite'

    def store(self):
        from access_intake.store import Store
        return Store(self.db)

    def test_policy_corpus_and_paraphrase(self):
        from access_intake.app import run_intake
        from access_intake.providers import FixtureProvider
        paths = sorted((ROOT / 'materials/requests').glob('*.json'))
        paths.append(ROOT / 'tests/fixtures/exports/IT-001-paraphrase.json')
        store = self.store()
        run_intake(store, paths, FixtureProvider(), workers=4)
        rows = {r['document_id']: r for r in store.current()}
        self.assertEqual(len(rows), 21)
        for path in paths:
            expected = json.loads((ROOT / 'tests/expectations' / path.name).read_text())
            row = rows[path.name]
            with self.subTest(document=path.name):
                self.assertIsNone(row['error'])
                for key in ('status', 'owner', 'next_action'):
                    self.assertEqual(row[key], expected['route'][key])
                for key, value in expected['facts'].items():
                    if key == 'business_purpose':
                        continue
                    if isinstance(value, dict):
                        self.assertIn(row['extraction'][key], value['alternatives'])
                    else:
                        self.assertEqual(row['extraction'][key], value)
                self.assertTrue(all(q in expected['source_message'] for q in row['extraction']['supporting_quotes']))

    def test_reuse_change_settings_omission_and_failed_retry(self):
        from access_intake.app import run_intake
        store = self.store()
        path = Path(self.temp.name) / 'IT-001.json'
        path.write_bytes((ROOT / 'materials/requests/IT-001.json').read_bytes())
        provider = MockProvider(MOCKS, schedule=['complete-001'] * 4 + [TimeoutError()])
        run_intake(store, [path], provider)
        first = store.current()[0]
        run_intake(store, [path], provider)
        self.assertEqual(provider.call_count, 1)
        run_intake(store, [], provider)
        self.assertEqual(store.current()[0]['attempt_id'], first['attempt_id'])
        path.write_bytes(path.read_bytes() + b'\n')
        run_intake(store, [path], provider)
        self.assertEqual(provider.call_count, 2)
        self.assertNotEqual(store.current()[0]['source_sha256'], first['source_sha256'])
        run_intake(store, [path], provider, settings={'model': 'changed'})
        self.assertEqual(provider.call_count, 3)
        run_intake(store, [path], provider, force=True)
        run_intake(store, [path], provider, force=True)
        self.assertEqual(store.current()[0]['status'], 'error')
        self.assertIsNone(store.current()[0]['extraction'])
        self.assertEqual(len(store.history(path.name)), 5)
        self.assertIsNone(store.history(path.name)[0]['error'])

    def test_slow_and_overlapping_operators_latest_revision_wins(self):
        from access_intake.app import run_intake
        store = self.store()
        path = Path(self.temp.name) / 'IT-001.json'
        path.write_bytes((ROOT / 'materials/requests/IT-001.json').read_bytes())
        started, release = Event(), Event()
        provider = MockProvider(MOCKS, schedule=[ControlledResponse('complete-001', started, release)])
        errors = []
        def old_run():
            try:
                run_intake(store, [path], provider)
            except Exception as exc:
                errors.append(exc)
        thread = Thread(target=old_run)
        thread.start()
        self.addCleanup(release.set)
        try:
            self.assertTrue(started.wait(5))
            self.assertEqual(store.pending()[0]['state'], 'running')
            # Another operator cannot claim the same work.
            duplicate = MockProvider(MOCKS, schedule=[])
            run_intake(store, [path], duplicate)
            self.assertEqual(duplicate.call_count, 0)
            # Independent work finishes while the first call is still blocked.
            run_intake(store, [ROOT / 'materials/requests/IT-002.json'],
                       MockProvider(MOCKS, schedule=['corpus-002']))
            self.assertEqual(store.current()[0]['document_id'], 'IT-002.json')
            path.write_bytes(path.read_bytes() + b'\n')
            run_intake(store, [path], MockProvider(MOCKS, schedule=['complete-001']))
            latest = next(r for r in store.current() if r['document_id'] == path.name)
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(next(r for r in store.current() if r['document_id'] == path.name)['attempt_id'], latest['attempt_id'])
            self.assertEqual(len(store.history(path.name)), 2)
        finally:
            release.set()
            thread.join(5)

    def test_expired_claim_resume_and_snapshot_consistency(self):
        from access_intake.app import run_pending
        store = self.store()
        attempt = store.register(read_export(ROOT / 'materials/requests/IT-001.json'), {'provider': 'mock'})
        self.assertTrue(store.claim(attempt, lease_seconds=-1))
        run_pending(store, MockProvider(MOCKS, schedule=['complete-001']))
        self.assertEqual(store.pending(), [])
        self.assertEqual(store.current()[0]['status'], 'review')
        output = Path(self.temp.name) / 'deliverables'
        store.export(output)
        records = [json.loads(line) for line in (output / 'extractions.jsonl').read_text().splitlines()]
        queue = json.loads((output / 'queue.json').read_text())
        for row, item in zip(records, queue):
            for key in ('document_id', 'source_sha256', 'attempt_id', 'status', 'owner', 'next_action'):
                self.assertEqual(row[key], item[key])

    def test_cli_clean_workflow_and_retry_command(self):
        def cli(*args):
            result = subprocess.run([sys.executable, '-m', 'access_intake', *args, '--db', str(self.db)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        cli('intake', 'materials/requests', '--provider', 'mock')
        self.assertEqual(len(json.loads(cli('queue'))), 20)
        self.assertEqual(json.loads(cli('pending')), [])
        cli('resume')
        cli('retry', 'IT-001.json')
        self.assertEqual(len(json.loads(cli('history', 'IT-001.json'))), 2)
        cli('export', '--output', str(Path(self.temp.name) / 'out'))


class ProviderAdapterTests(unittest.TestCase):
    def test_native_schema_request_and_response_gates(self):
        from access_intake.openai_provider import OpenAIProvider
        from access_intake.validation import SCHEMA
        from access_intake.extraction import extract_document
        doc = read_export(ROOT / 'materials/requests/IT-001.json')
        extraction = json.loads((MOCKS / 'complete-001.json').read_text())['extraction']
        captured = []
        def transport(url, headers, payload, timeout):
            captured.append((url, headers, payload, timeout))
            return {'status': 'completed', 'output': [{'type': 'message', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': json.dumps(extraction)}]}]}
        provider = OpenAIProvider(api_key='synthetic-secret', transport=transport)
        row = extract_document(doc, provider, attempt_id='a')
        self.assertIsNone(row['error'])
        self.assertEqual(captured[0][2]['text']['format']['schema'], SCHEMA)
        self.assertTrue(captured[0][2]['text']['format']['strict'])
        self.assertEqual(captured[0][2]['model'], 'gpt-4.1-mini-2025-04-14')
        self.assertEqual(captured[0][2]['input'][0]['content'], doc.message)
        self.assertNotIn('synthetic-secret', json.dumps(provider.evidence(doc.message)))
        for response, category in [
            ({'status': 'incomplete', 'output': []}, 'incomplete'),
            ({'status': 'completed', 'output': [{'type': 'message', 'status': 'completed', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]}, 'refusal'),
            ({'status': 'completed', 'output': []}, 'malformed_envelope'),
            ({'status': 'completed', 'output': [{'type': 'message', 'status': 'incomplete', 'content': [{'type': 'output_text', 'text': json.dumps(extraction)}]}]}, 'incomplete'),
            ({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(extraction)}]}]}, 'malformed_envelope'),
        ]:
            with self.subTest(category=category):
                provider = OpenAIProvider(api_key='synthetic-secret', transport=lambda *args: response)
                row = extract_document(doc, provider, attempt_id='b')
                self.assertEqual(row['error']['category'], category)
                self.assertIsNone(row['extraction'])


class AccuracyTests(unittest.TestCase):
    def test_fixed_denominator_missing_outputs_and_wrong_fact(self):
        from access_intake.accuracy import compare
        expected = json.loads((ROOT / 'tests/expectations/IT-001.json').read_text())
        result = compare([], [expected])
        self.assertEqual(result['denominator'], 11)
        self.assertEqual(result['exact_matches'], 0)
        self.assertEqual(len(result['mismatches']), 11)
        record = {'document_id': 'IT-001.json', 'extraction': dict(expected['facts']), 'error': None,
                  **{k: expected['route'][k] for k in ('status', 'owner', 'next_action')}}
        record['extraction']['permission'] = 'admin'
        result = compare([record], [expected])
        self.assertEqual(result['exact_matches'], 10)
        self.assertEqual(result['mismatches'][0]['field'], 'permission')
        self.assertEqual(result['whole_document_matches'], 0)
        with self.assertRaises(ValueError):
            compare([record, record], [expected])


class TransportTests(unittest.TestCase):
    def test_real_http_transport_builds_post_and_sets_timeout_without_network(self):
        from access_intake.openai_provider import OpenAIProvider
        from access_intake.extraction import extract_document
        doc = read_export(ROOT / 'materials/requests/IT-001.json')
        text = json.dumps(json.loads((MOCKS / 'complete-001.json').read_text())['extraction'])
        response = {'status': 'completed', 'output': [{'type': 'message', 'status': 'completed',
                     'content': [{'type': 'output_text', 'text': text}]}]}
        with patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            provider = OpenAIProvider(api_key='synthetic-secret', timeout=17)
            result = extract_document(doc, provider, attempt_id='http-test')
            self.assertIsNone(result['error'])
            request = urlopen.call_args.args[0]
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-secret')
            self.assertEqual(urlopen.call_args.kwargs['timeout'], 17)
            self.assertEqual(json.loads(request.data)['text']['format']['type'], 'json_schema')
            self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_rate_limits_and_unavailability_are_safe_and_retryable(self):
        from urllib.error import HTTPError
        from access_intake.extraction import extract_document
        from access_intake.openai_provider import OpenAIProvider
        doc = read_export(ROOT / 'materials/requests/IT-001.json')
        for status, category in [(429, 'rate_limit'), (503, 'provider_unavailable'), (401, 'provider_error')]:
            with self.subTest(status=status), patch('urllib.request.urlopen', side_effect=HTTPError(
                    'https://private/synthetic-secret', status, 'synthetic-secret', {}, None)) as transport:
                result = extract_document(doc, OpenAIProvider(api_key='synthetic-secret'), attempt_id='failure')
                self.assertEqual(result['error']['category'], category)
                self.assertIsNone(result['extraction'])
                self.assertNotIn('synthetic-secret', json.dumps(result))
                self.assertEqual(transport.call_count, 1)


class WorkerVisibilityTests(unittest.TestCase):
    def test_one_batch_publishes_fast_work_before_slow_work(self):
        from access_intake.app import run_intake
        from access_intake.store import Store
        started, release, fast = Event(), Event(), Event()
        errors = []
        class DelayedProvider:
            response_source = 'mock'
            def extract(self, request):
                if request['document_id'] == 'IT-001.json':
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError()
                    return json.loads((MOCKS / 'complete-001.json').read_text())
                fast.set()
                return json.loads((MOCKS / 'corpus-002.json').read_text())
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'state.sqlite')
            def run():
                try:
                    run_intake(store, [ROOT/'materials/requests/IT-001.json', ROOT/'materials/requests/IT-002.json'],
                               DelayedProvider(), workers=2)
                except Exception as exc:
                    errors.append(exc)
            thread = Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertTrue(fast.wait(5))
                # Synchronize on the committed DB state, with a deadline rather than a timing assertion.
                import time
                deadline = time.monotonic() + 5
                while not store.current() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(store.current()[0]['document_id'], 'IT-002.json')
                self.assertEqual(len(store.pending()), 1)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(len(store.current()), 2)
