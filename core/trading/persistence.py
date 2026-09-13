import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(key TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, session TEXT NOT NULL, entry TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, session TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_analysis_update BEFORE UPDATE ON analyses BEGIN SELECT RAISE(ABORT,'immutable analysis'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_analysis_delete BEFORE DELETE ON analyses BEGIN SELECT RAISE(ABORT,'immutable analysis'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_journal_update BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT,'append-only journal'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_journal_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT,'append-only journal'); END;
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def encode(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
