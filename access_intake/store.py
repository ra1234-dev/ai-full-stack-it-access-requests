"""SQLite source revisions, renewable ownership tokens and atomic current records."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import time
import uuid
from .exports import SourceDocument


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL, source_hash TEXT NOT NULL, raw BLOB NOT NULL,
                    settings TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    token TEXT, lease REAL, result TEXT, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id)
                );
                CREATE INDEX IF NOT EXISTS attempts_document ON attempts(document_id, id);
            ''')

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, document, settings, *, force=False):
        encoded = json.dumps(settings, sort_keys=True)
        with self.connection(write=True) as db:
            old = db.execute('SELECT a.* FROM documents d JOIN attempts a ON a.id=d.attempt_id '
                             'WHERE d.document_id=?', (document.document_id,)).fetchone()
            if not force and old and old['source_hash'] == document.source_hash and old['settings'] == encoded:
                return old['id']
            cursor = db.execute('INSERT INTO attempts(document_id,source_hash,raw,settings,created) VALUES(?,?,?,?,?)',
                                (document.document_id, document.source_hash, document.raw_bytes, encoded, time.time()))
            attempt = cursor.lastrowid
            db.execute('INSERT INTO documents VALUES(?,?) ON CONFLICT(document_id) DO UPDATE SET attempt_id=excluded.attempt_id',
                       (document.document_id, attempt))
            return attempt

    def attempt(self, attempt):
        with self.connection() as db:
            row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt,)).fetchone()
        if row is None:
            raise ValueError('Unknown attempt.')
        return dict(row)

    def document(self, attempt):
        row = self.attempt(attempt)
        raw = row['raw']
        export = json.loads(raw.decode('utf-8'))
        import re
        match = re.match(r'^(IT-[0-9]+)(?:-|$)', Path(row['document_id']).stem)
        return SourceDocument(row['document_id'], raw, row['source_hash'], export['message'],
                              {k: v for k, v in export.items() if k != 'message'}, match.group(1) if match else None)

    def claim(self, attempt, *, lease_seconds=90):
        token = uuid.uuid4().hex
        now = time.time()
        with self.connection(write=True) as db:
            cursor = db.execute("UPDATE attempts SET state='running', token=?, lease=? WHERE id=? "
                                "AND (state='pending' OR (state='running' AND lease<?))",
                                (token, now + lease_seconds, attempt, now))
            return token if cursor.rowcount else None

    def finish(self, attempt, token, result):
        with self.connection(write=True) as db:
            # A reclaimed lease invalidates the original worker's token. The current pointer
            # is set at registration, so a late old-source completion cannot move it back.
            return bool(db.execute("UPDATE attempts SET state='done',result=?,lease=NULL WHERE id=? AND token=? AND state='running'",
                                   (json.dumps(result), attempt, token)).rowcount)

    def current(self):
        with self.connection() as db:
            rows = db.execute("SELECT a.result FROM documents d JOIN attempts a ON a.id=d.attempt_id "
                              "WHERE a.state='done' ORDER BY d.document_id").fetchall()
        return [json.loads(row['result']) for row in rows]

    def pending(self):
        with self.connection() as db:
            rows = db.execute("SELECT a.id AS attempt_id,a.document_id,a.source_hash AS source_sha256,a.state,a.lease "
                              "FROM documents d JOIN attempts a ON a.id=d.attempt_id WHERE a.state!='done' ORDER BY a.id").fetchall()
        return [dict(row) for row in rows]

    def latest(self, document_id):
        with self.connection() as db:
            row = db.execute('SELECT attempt_id FROM documents WHERE document_id=?', (document_id,)).fetchone()
        if not row:
            raise ValueError('Unknown document_id; inspect queue or pending.')
        return row['attempt_id']

    def history(self, document_id):
        with self.connection() as db:
            rows = db.execute('SELECT * FROM attempts WHERE document_id=? ORDER BY id', (document_id,)).fetchall()
        return [json.loads(r['result']) if r['result'] else
                dict(attempt_id=str(r['id']), document_id=r['document_id'], source_sha256=r['source_hash'],
                     state=r['state'], processing_settings=json.loads(r['settings'])) for r in rows]

    def retry_command(self, document_id):
        return f'python3 -m access_intake retry {shlex.quote(document_id)} --db {shlex.quote(str(self.path))}'

    def export(self, output):
        """Both files come from a single SELECT; publish an atomic directory pointer.

        Stable file symlinks point through current; readers requiring both pin current.resolve().
        Publishing is serialized across processes by a lock on the destination directory.
        """
        import fcntl
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        with (output / '.export.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            rows = self.current()
            snapshots = output / '.snapshots'
            snapshots.mkdir(exist_ok=True)
            generation = uuid.uuid4().hex
            target = snapshots / generation
            target.mkdir()
            queue = [{k: row[k] for k in ('document_id', 'source_sha256', 'attempt_id', 'status', 'owner', 'next_action')}
                     for row in rows]
            for name, content in [('extractions.jsonl', ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)),
                                  ('queue.json', json.dumps(queue, indent=2) + '\n')]:
                with (target / name).open('w', encoding='utf-8') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            temporary = output / f'.current-{generation}'
            temporary.symlink_to(Path('.snapshots') / generation, target_is_directory=True)
            temporary.replace(output / 'current')
            for name in ('extractions.jsonl', 'queue.json'):
                link = output / f'.{name}-{generation}'
                link.symlink_to(Path('current') / name)
                link.replace(output / name)
