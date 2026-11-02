"""Transactional independent emotion ledger. No dependency on any memory module."""
from contextlib import contextmanager, closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time

from .model import Config, EmotionEvent, identifier, number
from .dynamics import initial, advance, apply, coordinates, future
from .expression import describe, reference_packet


class EmotionStore:
    def __init__(self, path, *, assistant_id='companion', config=None):
        self.path = Path(path)
        self.config = config or Config()
        if not isinstance(self.config, Config):
            raise ValueError('config must be Config')
        self.assistant_id = identifier(assistant_id, 'assistant_id')
        # Refuse foreign SQLite files before making any schema changes.
        if self.path.exists():
            with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True)) as probe:
                tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables and 'meta' not in tables:
                    raise ValueError('This is not a yuyi_emotion database; do not pass a memory database')
                if tables:
                    try:
                        row = probe.execute('SELECT schema_version,owner,config_hash FROM meta WHERE id=1').fetchone()
                    except sqlite3.Error as error:
                        raise ValueError('Foreign database metadata') from error
                    if not row or row != (1, self.assistant_id, self.config.fingerprint()):
                        raise ValueError('Database schema, owner or configuration mismatch')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER, owner TEXT, config_hash TEXT, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, evidence_key TEXT UNIQUE NOT NULL, time REAL NOT NULL, payload TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)')
            db.execute('CREATE TABLE IF NOT EXISTS operations (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, recorded_at REAL NOT NULL)')
            row = db.execute('SELECT * FROM meta WHERE id=1').fetchone()
            if row:
                if row['schema_version'] != 1 or row['owner'] != self.assistant_id:
                    raise ValueError('Emotion database schema/assistant mismatch; use a separate directory')
                if row['config_hash'] != self.config.fingerprint():
                    raise ValueError('Configuration changed; compare parameters in a new database')
            else:
                db.execute('INSERT INTO meta VALUES(1,1,?,?,?)',
                           (self.assistant_id, self.config.fingerprint(), json.dumps(initial())))

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _load(self, db):
        return json.loads(db.execute('SELECT state FROM meta WHERE id=1').fetchone()[0])

    def _save(self, db, state):
        db.execute('UPDATE meta SET state=? WHERE id=1', (json.dumps(state),))

    def submit(self, event):
        if not isinstance(event, EmotionEvent):
            raise ValueError('Expected a validated EmotionEvent')
        if event.owner != 'self':
            return {'accepted': False, 'reason': 'not_agent_emotion'}
        if event.evidence_kind in ('recalled_memory', 'unknown'):
            return {'accepted': False, 'reason': 'not_new_supported_experience'}
        if event.evidence_kind == 'verified_outcome' and not event.verified:
            return {'accepted': False, 'reason': 'outcome_not_verified'}
        if event.confidence < self.config.confidence_threshold:
            return {'accepted': False, 'reason': 'low_confidence'}
        with self._db(write=True) as db:
            # Keep IDs reserved after retraction: a retry cannot resurrect an event.
            existing = db.execute('SELECT event_id FROM events WHERE event_id=? OR evidence_key=?',
                                  (event.event_id, event.evidence_key())).fetchone()
            if existing:
                return {'accepted': False, 'reason': 'duplicate_evidence', 'original_event_id': existing[0]}
            state = self._load(db)
            advance(state, event.timestamp, self.config)
            before = coordinates(state, self.config)
            apply(state, event, self.config)
            after = coordinates(state, self.config)
            state['label_hint'] = describe(state, self.config)['label']
            db.execute('INSERT INTO events(event_id,evidence_key,time,payload) VALUES(?,?,?,?)',
                       (event.event_id, event.evidence_key(), event.timestamp,
                        json.dumps(event.to_dict(), ensure_ascii=False)))
            self._save(db, state)
            return {'accepted': True, 'reason': 'new_experience', 'event_id': event.event_id,
                    'coordinates_before': before, 'coordinates_after': after}

    def state(self, timestamp, *, char_budget=500):
        number(timestamp, 'timestamp', 0, 10**12)
        with self._db() as db:
            state = future(self._load(db), timestamp, self.config)
            counts = db.execute('SELECT COUNT(*),SUM(active) FROM events').fetchone()
        description = describe(state, self.config)
        return {'assistant_id': self.assistant_id, 'as_of': timestamp,
                'coordinates': dict(zip(('pleasure', 'arousal', 'agency'), coordinates(state, self.config))),
                'layers': {'baseline': asdict(self.config.baseline),
                           'short_raw': state['short'], 'mood_raw': state['mood']},
                'positive_load': state['positive'], 'negative_load': state['negative'],
                'mood_positive_load': state['mood_positive'], 'mood_negative_load': state['mood_negative'],
                'description': description, 'reference': reference_packet(description, char_budget=char_budget),
                'causes': state['contexts'], 'event_count': counts[0], 'active_event_count': counts[1] or 0,
                'simulated': True, 'memory_modified': False}

    def _replay(self, db):
        state = initial()
        for row in db.execute('SELECT payload,active,time FROM events ORDER BY time,seq'):
            advance(state, row['time'], self.config)
            if row['active']:
                apply(state, EmotionEvent.from_dict(json.loads(row['payload'])), self.config)
                state['label_hint'] = describe(state, self.config)['label']
        return state

    def replay(self, timestamp):
        """Read-only independent reconstruction for checking deterministic state."""
        number(timestamp, 'timestamp', 0, 10**12)
        with self._db() as db:
            state = future(self._replay(db), timestamp, self.config)
        return {'coordinates': coordinates(state, self.config), 'short_raw': state['short'],
                'mood_raw': state['mood'], 'description': describe(state, self.config)}

    def set_active(self, event_id, active, *, reason):
        """Explicit correction/rollback; never called automatically by reading."""
        if not isinstance(active, bool) or reason not in ('correction', 'user_request', 'invalid_evidence', 'reviewed_restore'):
            raise ValueError('Expected a bool and a supported reason code')
        if active and reason != 'reviewed_restore':
            raise ValueError('Restoring requires reviewed_restore')
        with self._db(write=True) as db:
            row = db.execute('SELECT active FROM events WHERE event_id=?', (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if bool(row[0]) == active:
                return False
            db.execute('UPDATE events SET active=? WHERE event_id=?', (int(active), event_id))
            db.execute('INSERT INTO operations(event_id,action,reason,recorded_at) VALUES(?,?,?,?)',
                       (event_id, 'restore' if active else 'retract', reason, time.time()))
            self._save(db, self._replay(db))
        return True

    def audit(self, *, limit=20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('limit must be 1..100')
        with self._db() as db:
            return [{**json.loads(row['payload']), 'active': bool(row['active'])}
                    for row in db.execute('SELECT payload,active FROM events ORDER BY seq DESC LIMIT ?', (limit,))]

    def changes(self, *, limit=20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1<=limit<=100:
            raise ValueError('limit must be 1..100')
        with self._db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM operations ORDER BY seq DESC LIMIT ?', (limit,))]

    def backup(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve() or destination.exists():
            raise ValueError('Backup needs a new destination')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.touch(exist_ok=False)
        try:
            with closing(sqlite3.connect(self.path)) as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                finally:
                    target.close()
        except Exception:
            # Keep a partial file visible; never overwrite an existing backup.
            raise
