"""Chipova's records in one SQLite file (``<home>/chipova.db``, see :mod:`chipova.paths`).

One connection per process, shared by the event loop and worker threads under a lock; every
query is short (the big things, files and artifacts, live as files). The schema is created and
migrated on first use; ``SCHEMA`` counts its versions.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from typing import Any, Iterator

from chipova import paths

SCHEMA = 1

_TABLES = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS projects(
    id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, template TEXT DEFAULT '',
    owner TEXT DEFAULT '', owner_name TEXT DEFAULT '', link_access TEXT NOT NULL,
    created_at REAL, updated_at REAL, ai_may_run TEXT DEFAULT '[]', deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS memberships(
    project_id TEXT, user TEXT, role TEXT NOT NULL, added_by TEXT DEFAULT '', added_at REAL,
    PRIMARY KEY(project_id, user));
CREATE TABLE IF NOT EXISTS files(
    project_id TEXT, id TEXT, path TEXT NOT NULL, created_at REAL, updated_at REAL,
    updated_by TEXT DEFAULT '', PRIMARY KEY(project_id, id), UNIQUE(project_id, path));
CREATE TABLE IF NOT EXISTS revisions(
    id TEXT, project_id TEXT, git_commit TEXT, source_sha TEXT, parent TEXT DEFAULT '',
    message TEXT DEFAULT '', created_by TEXT DEFAULT '', created_by_name TEXT DEFAULT '',
    created_at REAL, files TEXT DEFAULT '[]', PRIMARY KEY(project_id, id));
CREATE TABLE IF NOT EXISTS runs(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision_id TEXT NOT NULL, flow_id TEXT NOT NULL,
    flow_version TEXT DEFAULT '', profile_id TEXT DEFAULT '', params TEXT DEFAULT '{}',
    status TEXT NOT NULL, approval_status TEXT NOT NULL, approval_by TEXT DEFAULT '',
    approval_at REAL DEFAULT 0, requested_by TEXT DEFAULT '', requested_by_name TEXT DEFAULT '',
    requested_via TEXT DEFAULT 'ui', source_run TEXT DEFAULT '', created_at REAL,
    queued_at REAL DEFAULT 0, started_at REAL DEFAULT 0, ended_at REAL DEFAULT 0,
    container TEXT DEFAULT '', image TEXT DEFAULT '', image_digest TEXT DEFAULT '',
    exit_code INTEGER, error TEXT DEFAULT '', summary TEXT DEFAULT '{}', problems TEXT DEFAULT '{}');
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS run_steps(
    run_id TEXT, idx INTEGER, node TEXT, title TEXT DEFAULT '', status TEXT NOT NULL,
    started_at REAL DEFAULT 0, ended_at REAL DEFAULT 0, exit_code INTEGER,
    command TEXT DEFAULT '[]', command_digest TEXT DEFAULT '', metrics TEXT DEFAULT '{}',
    PRIMARY KEY(run_id, node));
CREATE TABLE IF NOT EXISTS artifacts(
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL,
    access_scope TEXT DEFAULT 'project');
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id);
CREATE TABLE IF NOT EXISTS agent_actions(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, agent TEXT NOT NULL, on_behalf_of TEXT DEFAULT '',
    kind TEXT NOT NULL, title TEXT DEFAULT '', rationale TEXT DEFAULT '', plan TEXT DEFAULT '',
    base_revision TEXT DEFAULT '', payload TEXT DEFAULT '{}', status TEXT NOT NULL,
    decided_by TEXT DEFAULT '', decided_by_name TEXT DEFAULT '', decided_at REAL DEFAULT 0,
    reason TEXT DEFAULT '', applied_revision TEXT DEFAULT '', created_at REAL, expires_at REAL);
CREATE INDEX IF NOT EXISTS agent_actions_project ON agent_actions(project_id, created_at);
CREATE TABLE IF NOT EXISTS reviews(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision_id TEXT NOT NULL, reviewer TEXT,
    reviewer_name TEXT DEFAULT '', status TEXT NOT NULL, comment TEXT DEFAULT '', created_at REAL);
CREATE TABLE IF NOT EXISTS comments(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, anchor_kind TEXT NOT NULL, anchor TEXT DEFAULT '{}',
    revision_id TEXT DEFAULT '', author TEXT DEFAULT '', author_name TEXT DEFAULT '',
    body TEXT DEFAULT '', created_at REAL, resolved INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS comments_project ON comments(project_id, created_at);
CREATE TABLE IF NOT EXISTS waivers(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision_id TEXT NOT NULL, category TEXT NOT NULL,
    rule_id TEXT DEFAULT '', reason TEXT DEFAULT '', requested_by TEXT DEFAULT '',
    requested_by_name TEXT DEFAULT '', approved_by TEXT DEFAULT '', approved_by_name TEXT DEFAULT '',
    status TEXT NOT NULL, created_at REAL, decided_at REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS releases(
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision_id TEXT NOT NULL, title TEXT DEFAULT '',
    status TEXT NOT NULL, requested_by TEXT DEFAULT '', requested_by_name TEXT DEFAULT '',
    created_at REAL, runs TEXT DEFAULT '[]', checklist TEXT DEFAULT '[]', approvals TEXT DEFAULT '[]',
    manifest_sha TEXT DEFAULT '', package_artifact TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, project_id TEXT DEFAULT '',
    actor TEXT DEFAULT '', actor_name TEXT DEFAULT '', actor_kind TEXT DEFAULT 'human', action TEXT NOT NULL,
    target TEXT DEFAULT '', args TEXT DEFAULT '{}', decision TEXT DEFAULT 'ok', detail TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS audit_project ON audit(project_id, ts);
CREATE TABLE IF NOT EXISTS access_requests(
    project_id TEXT, user TEXT, name TEXT DEFAULT '', at REAL, PRIMARY KEY(project_id, user));
CREATE TABLE IF NOT EXISTS profiles(
    id TEXT PRIMARY KEY, image TEXT DEFAULT '', image_id TEXT DEFAULT '', digest TEXT DEFAULT '',
    versions TEXT DEFAULT '{}', installed_at REAL DEFAULT 0, status TEXT DEFAULT '', detail TEXT DEFAULT '');
"""


# Columns added after a table was first made: (table, column, declaration). Each is added to an
# older database that lacks it, when it is opened.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("audit", "actor_name", "TEXT DEFAULT ''"),
]


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(_TABLES)
            for table, column, decl in _ADDED_COLUMNS:
                have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA),))

    def query(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def execute(self, sql: str, args: tuple | list = ()) -> int:
        """Runs one statement; returns the rows it changed (or the new row id of an insert)."""
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = list(row)
        self.execute(
            f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' for _ in cols)})",
            [_value(row[c]) for c in cols],
        )

    def update(self, table: str, key: dict[str, Any], fields: dict[str, Any]) -> int:
        if not fields:
            return 0
        sets = ", ".join(f"{c} = ?" for c in fields)
        where = " AND ".join(f"{c} = ?" for c in key)
        return self.execute(
            f"UPDATE {table} SET {sets} WHERE {where}",
            [_value(v) for v in fields.values()] + [_value(v) for v in key.values()],
        )

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def _value(v: Any) -> Any:
    """What SQLite stores for a field: JSON for lists and dicts, the value of enums."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    if hasattr(v, "value") and not isinstance(v, (str, int, float)):
        return v.value
    if isinstance(v, str) and hasattr(v, "value"):  # str enums
        return v.value
    return v


_db: Database | None = None
_db_lock = threading.Lock()


def db() -> Database:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                path = paths.db_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                _db = Database(str(path))
    return _db


def reset() -> None:
    """Forgets the open database (tests point CHIPOVA_HOME elsewhere and start again)."""
    global _db
    with _db_lock:
        if _db is not None:
            _db.close()
        _db = None
