"""
The job tracker's data layer — Turso when TURSO_DATABASE_URL is set, the local
SQLite file at data/jobs.db otherwise.

Usage:
    from src.jobs_db import get_job, get_followup_log, update_followup_log, upsert_job, delete_job
"""

import contextlib
import contextvars
import csv
import io
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv

# Loaded here, in the module every entry point goes through, because which
# database you get used to depend on whether your import chain happened to
# reach something that called load_dotenv(). The GUI did (via job_agent) and
# read Turso; parse_applied_jobs.py and the job_tracker MCP server did not and
# wrote data/jobs.db. The two stores drifted 153 rows apart before anyone
# noticed, and an ApplyPass import of 101 rows landed in the file nothing reads.
#
# By absolute path, not find_dotenv(): the MCP server and the cron scripts do
# not run from the repo root, and a cwd-relative search silently finds nothing
# and falls back to local -- reintroducing the same split without an error.
#
# override=False, so a caller that has already exported TURSO_DATABASE_URL (or
# unset it deliberately, as tests/conftest.py does) still wins.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)

# JOBS_DB points this at a throwaway copy without moving data/jobs.db aside --
# the demo database the README screenshots are taken against, for one. A
# relative value resolves from the repo root rather than the cwd, so a cron
# script and an interactive shell get the same file. Tests monkeypatch this
# constant directly and are unaffected either way.
_DB_OVERRIDE = os.environ.get("JOBS_DB", "").strip()
if not _DB_OVERRIDE:
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db")
elif os.path.isabs(_DB_OVERRIDE):
    DB_PATH = _DB_OVERRIDE
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", _DB_OVERRIDE)

COLUMNS = [
    "company", "position_title", "job_summary", "location", "link",
    "date_added", "contacts", "notes", "outreach_date", "date_applied",
    "status", "followup_log"
]

# What the jobs list ships. job_summary is two thirds of the payload by bytes and
# is never in the table and never searched -- it is fetched per row on expand
# instead. Derived from COLUMNS rather than written out, so a column added there
# reaches the GUI without a second edit. `notes` deliberately stays: the search
# box matches against it, so the whole table needs it in hand.
LIST_COLUMNS = [c for c in COLUMNS if c != "job_summary"]


_JOBS_DDL = """
        CREATE TABLE IF NOT EXISTS {table} (
            company       TEXT NOT NULL,
            date_added    TEXT NOT NULL DEFAULT '',
            position_title TEXT NOT NULL DEFAULT '',
            link          TEXT NOT NULL DEFAULT '',
            job_summary   TEXT,
            location      TEXT,
            contacts      TEXT,
            notes         TEXT,
            outreach_date TEXT,
            date_applied  TEXT,
            status        TEXT,
            followup_log  TEXT,
            archived      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (company, date_added, position_title, link)
        )
"""

# The columns that identify a row, in key order.
KEY_COLUMNS = ["company", "date_added", "position_title", "link"]

# The funnel, in order. Rank is what enforces "never downgrade a status" -- a
# rule the skills have stated in prose for a long time (inbox-triage/SKILL.md:15,
# application-digest/SKILL.md:64) without anything in code holding it. It lives
# here rather than in jobs_gui because importing that module to read a list would
# construct a Flask app as a side effect.
STATUS_ORDER = [
    "", "Tracking", "Applied", "Phone Screen", "Technical",
    "System Design", "Behavioral", "Offer", "Accepted", "Rejected",
]


def status_rank(status: Optional[str]) -> int:
    """Position in STATUS_ORDER; -1 for anything unrecognized, so an unknown
    status never counts as forward progress."""
    try:
        return STATUS_ORDER.index((status or "").strip())
    except ValueError:
        return -1


_META_DDL = """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
"""


def _migrate_key(conn: sqlite3.Connection) -> None:
    """
    Row identity widened twice as collisions surfaced: (company, date_added) lost
    a second role at the same company on the same day, then adding position_title
    still lost distinct requisitions posted under one title. The posting URL is
    what actually distinguishes them, so `link` completes the key. Rebuilding with
    a wider key only ever preserves more rows. No-op once migrated.
    """
    cols = conn.execute("PRAGMA table_info(jobs)").fetchall()
    if not cols:
        return
    in_pk = {row[1] for row in cols if row[5]}  # row[5] = pk position, 0 when not in PK
    if in_pk == set(KEY_COLUMNS):
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(_JOBS_DDL.format(table="jobs_migrated"))
    conn.execute(
        "INSERT OR REPLACE INTO jobs_migrated "
        "(company, date_added, position_title, link, job_summary, location, contacts, "
        " notes, outreach_date, date_applied, status, followup_log, archived) "
        "SELECT company, date_added, COALESCE(position_title, ''), COALESCE(link, ''), "
        "       job_summary, location, contacts, notes, outreach_date, date_applied, "
        "       status, followup_log, COALESCE(archived, 0) FROM jobs"
    )
    conn.execute("DROP TABLE jobs")
    conn.execute("ALTER TABLE jobs_migrated RENAME TO jobs")
    conn.commit()


# Schema setup is idempotent but not free. Against local SQLite a redundant
# CREATE TABLE IF NOT EXISTS costs nothing, so it ran on every connection — and
# an /insights render opens eleven. That is 220 schema statements to serve 12
# data reads. Local: 83ms, invisible. Against a remote database every one of
# those is a round trip, which is roughly nine seconds a page.
#
# Keyed by resolved path rather than a bare boolean so tests, which point
# DB_PATH at a fresh tmp file per test, still get their schema built.
# --- Driver -----------------------------------------------------------------
# The pipeline runs as cloud Routines against a remote libSQL/Turso database,
# but local development and the whole test suite stay on plain SQLite. The
# driver is chosen by environment, and with TURSO_DATABASE_URL unset nothing
# about the SQLite path changes.
#
# libSQL is NOT a drop-in for sqlite3 despite the marketing. It returns plain
# tuples and `conn.row_factory` does not exist at all -- accessing it raises
# AttributeError. This codebase indexes rows by name in 146 places, so the shim
# below rebuilds sqlite3.Row semantics from cursor.description, which libSQL
# does provide.

def _use_libsql() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL", "").strip())


# libSQL raises bare ValueError for SQL errors -- not sqlite3.OperationalError,
# not even its own libsql.Error. _ensure_schema relies on a duplicate-column
# ALTER TABLE failing predictably, so both have to be caught.
_SCHEMA_EXC: tuple = (sqlite3.OperationalError, ValueError)

# Same divergence on the write side: a PRIMARY KEY collision surfaces as
# sqlite3.IntegrityError locally and as a bare ValueError over Hrana. Callers
# that turn a collision into a user-facing message need both.
#
# This is a backstop, not the mechanism. ValueError is wide enough to swallow an
# unrelated bug and report it as "already exists", and tests/conftest.py strips
# TURSO_* for the whole session, so no test can ever prove what libSQL actually
# raises. Detect collisions with an explicit SELECT first; catch this after.
_WRITE_EXC: tuple = (sqlite3.IntegrityError, ValueError)


class _ShimRow(dict):
    """
    A row that behaves like sqlite3.Row for the patterns this codebase uses:
    name indexing, positional indexing, dict() conversion, and .keys().
    """

    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def keys(self) -> list:
        return list(super().keys())


class _ShimCursor:
    """Wraps a libSQL cursor so its rows come back as _ShimRow."""

    def __init__(self, cursor):
        self._cursor = cursor

    def _wrap(self, row):
        if row is None:
            return None
        return _ShimRow([d[0] for d in self._cursor.description], row)

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self) -> list:
        return [self._wrap(r) for r in self._cursor.fetchall()]

    def __iter__(self):
        # libSQL cursors are not iterable, so materialise. Only two callers
        # iterate a cursor directly, both in _relationship_index.
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ShimConnection:
    """Wraps a libSQL connection so execute() yields shimmed cursors."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs) -> _ShimCursor:
        return _ShimCursor(self._conn.execute(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._conn, name)


_SCHEMA_ENSURED: set[str] = set()


def _reset_schema_cache() -> None:
    """Forces the next connection to re-run schema setup. For tests that need to
    prove a migration is idempotent across runs, not merely skipped."""
    _SCHEMA_ENSURED.clear()


def _ensure_schema(conn, path: Optional[str] = None) -> None:
    # Turso rejects busy_timeout and journal_mode outright -- "SQL not allowed
    # statement" over Hrana -- and both are meaningless against a server, which
    # manages its own concurrency and storage. table_info and foreign_keys ARE
    # allowed, so the migrations below work unchanged.
    #
    # Keyed off the connection, not the environment: the GUI opens its own
    # SQLite connection and must still get its PRAGMAs even when
    # TURSO_DATABASE_URL is set.
    remote = isinstance(conn, _ShimConnection)

    # busy_timeout is per-connection, so it is set every time regardless. It is
    # one statement; the other twenty are what this guard exists to skip.
    if not remote:
        conn.execute("PRAGMA busy_timeout=5000")
    if path is not None and path in _SCHEMA_ENSURED:
        return

    # journal_mode is a property of the database file, not the connection, so it
    # only needs setting when we actually touch the schema.
    if not remote:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_JOBS_DDL.format(table="jobs"))
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    except _SCHEMA_EXC:
        pass  # column already exists
    _migrate_key(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company ON jobs (company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archived ON jobs (archived)")
    _ensure_interviews_schema(conn)
    _ensure_recruiters_schema(conn)
    conn.execute(_META_DDL)
    if path is not None:
        _SCHEMA_ENSURED.add(path)


class _Scope:
    """
    One connection and one jobs snapshot, shared for the life of a scope.

    The connection is opened on first use, not on entry. Handlers that never
    touch the database -- the two that only render a template -- would otherwise
    pay ~84ms to open one and throw it away, and laziness is what lets the web
    app wrap *every* request without checking first.
    """

    def __init__(self, create: bool = False):
        self._create = create
        self._conn = None
        self.opened = False
        self.jobs = None      # memoised _stats_jobs payload; None means not fetched

    @property
    def conn(self):
        if not self.opened:
            self._conn = _open_connection(create=self._create)
            self.opened = True
        return self._conn

    def close(self) -> None:
        if self.opened and self._conn is not None:
            self._conn.close()

    def invalidate(self) -> None:
        self.jobs = None


_SCOPE: contextvars.ContextVar = contextvars.ContextVar("jobs_db_scope", default=None)

# Anything that is not a read invalidates the snapshot. A verb test rather than
# real dependency tracking: every write in this module is a plain
# INSERT/UPDATE/DELETE through a handful of helpers, so the verb is enough.
_READ_VERBS = ("select", "pragma", "with")


class _ScopedConnection:
    """
    The shared connection, handed to callers that each believe they own one.

    close() is a no-op, and that is the whole point rather than a nicety. Every
    helper here closes its connection in a `finally`, so the first one to finish
    would close the connection the rest are still using -- and libSQL answers a
    use-after-close with a Rust PanicException, not a Python exception, which no
    caller can catch. The real connection is closed once, when the scope exits.
    """

    def __init__(self, scope: _Scope):
        self._scope = scope

    def execute(self, *args, **kwargs):
        sql = str(args[0]).lstrip() if args else ""
        if not sql[:6].lower().startswith(_READ_VERBS):
            self._scope.invalidate()
        return self._scope.conn.execute(*args, **kwargs)

    def close(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._scope.conn, name)


@contextlib.contextmanager
def shared_connection(create: bool = False):
    """
    Reuse one connection for everything called inside the block.

    A remote connect costs ~84ms, and the helpers here open one apiece: rendering
    /insights called seven of them and opened eleven connections, ~2.1s of the
    4.6s the page took. Importing is worse -- upsert_job connects per row, so a
    101-row import spent 8.5s connecting.

    Opt-in on purpose. Outside a block `_connect()` behaves exactly as it always
    has, so the 21 helpers, the MCP server and every script are unaffected until
    someone wraps them deliberately. Long-running loops that idle between writes
    should stay outside: a remote connection held open across minutes of network
    waits is one that goes stale.

    Nested blocks join the outer scope rather than opening a second connection.
    """
    existing = _SCOPE.get()
    if existing is not None:
        yield _ScopedConnection(existing)
        return

    scope = _Scope(create=create)
    token = _SCOPE.set(scope)
    try:
        yield _ScopedConnection(scope)
    finally:
        _SCOPE.reset(token)
        scope.close()


def _connect(create: bool = False):
    """
    Opens a connection, building the schema on first use for this path.

    Inside a shared_connection() block this hands back the block's connection
    instead, so helpers that each open their own still end up sharing one.
    """
    scope = _SCOPE.get()
    if scope is not None:
        if scope.conn is None:      # local file missing and create=False
            return None
        return _ScopedConnection(scope)
    return _open_connection(create=create)


def _open_connection(create: bool = False):
    """
    Really opens a connection, building the schema on first use for this path.

    `create` only means anything for SQLite, where a missing file is a real
    signal that nothing has been written yet. A remote database always exists,
    so the check is skipped there.
    """
    if _use_libsql():
        import libsql  # imported lazily: unset TURSO_DATABASE_URL needs no dependency

        url = os.environ["TURSO_DATABASE_URL"].strip()
        token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
        conn = _ShimConnection(
            libsql.connect(url, auth_token=token) if token else libsql.connect(url)
        )
        _ensure_schema(conn, url)
        return conn

    path = os.path.abspath(DB_PATH)
    if not create and not os.path.exists(path):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn, path)
    return conn


def _parse_date(value: str) -> Optional[date]:
    if not value or not value.strip():
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def get_meta(key: str, default: str = "") -> str:
    """
    Reads a scalar from the `meta` key/value table.

    Returns `default` when the DB does not exist yet or the key was never set,
    so first-run callers get a usable value without special-casing.
    """
    conn = _connect()
    if not conn:
        return default
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_meta(key: str, value: str) -> None:
    """Writes a scalar to the `meta` key/value table, creating the DB if needed."""
    conn = _connect(create=True)
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(company: str) -> Optional[dict]:
    """
    Returns the most recently added, non-archived job for a company, or None if not found.
    Case-insensitive match.
    """
    conn = _connect()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE LOWER(company) = LOWER(?) AND archived = 0 "
            "ORDER BY date_added DESC LIMIT 1",
            (company,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_jobs_by_company(company: str) -> list[dict]:
    """Returns all tracked, non-archived jobs for a company."""
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE LOWER(company) = LOWER(?) AND archived = 0 "
            "ORDER BY date_added DESC",
            (company,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_job_by_link(link: str) -> Optional[dict]:
    """
    Returns the most recently added, non-archived job matching a link (exact,
    case-insensitive, whitespace-trimmed match), or None if not found.
    """
    link = (link or "").strip()
    if not link:
        return None
    conn = _connect()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE LOWER(TRIM(link)) = LOWER(?) AND archived = 0 "
            "ORDER BY date_added DESC LIMIT 1",
            (link,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_followup_log(company: str) -> str:
    """
    Returns the followup_log string for a company (e.g. '2026-07-05, 2026-07-12').
    Returns '' if not found.
    """
    job = get_job(company)
    return (job or {}).get("followup_log", "") or ""


def update_followup_log(company: str, date_str: str) -> str:
    """
    Appends date_str to the followup_log for the most recent job entry.
    Enforces a max of 2 dates. Returns the updated log string, or raises
    ValueError if the cap has already been reached.
    """
    conn = _connect()
    if not conn:
        raise RuntimeError("SQLite DB not found. Run sync_jobs_to_sqlite.py first.")

    try:
        row = conn.execute(
            "SELECT company, date_added, position_title, link, followup_log FROM jobs "
            "WHERE LOWER(company) = LOWER(?) AND archived = 0 ORDER BY date_added DESC LIMIT 1",
            (company,)
        ).fetchone()

        if not row:
            raise ValueError(f"Company '{company}' not found in local DB.")

        existing = (row["followup_log"] or "").strip()
        dates = [d.strip() for d in existing.split(",") if d.strip()] if existing else []

        if len(dates) >= 2:
            raise ValueError(
                f"Max follow-ups (2) already reached for '{company}': {existing}"
            )

        dates.append(date_str)
        updated = ", ".join(dates)

        conn.execute(
            "UPDATE jobs SET followup_log = ? WHERE company = ? AND date_added = ? "
            "AND position_title = ? AND link = ?",
            (updated, row["company"], row["date_added"], row["position_title"], row["link"])
        )
        conn.commit()
        return updated
    finally:
        conn.close()


def upsert_job(item: dict) -> None:
    """
    Insert or replace a job row in the local DB.
    `item` must contain at least 'company'. 'date_added' defaults to 'unknown'.
    """
    conn = _connect(create=True)
    try:
        vals = [item.get(c, "") or "" for c in COLUMNS]
        if not vals[0]:
            return
        key = [item.get(c, "") or "" for c in KEY_COLUMNS]
        conn.execute(
            f"INSERT OR REPLACE INTO jobs ({', '.join(COLUMNS)}, archived) "
            f"VALUES ({', '.join(['?'] * len(COLUMNS))}, "
            f"COALESCE((SELECT archived FROM jobs WHERE "
            f"          {' AND '.join(f'{c} = ?' for c in KEY_COLUMNS)}), 0))",
            vals + key
        )
        conn.commit()
    finally:
        conn.close()


def _key_clause(position_title: Optional[str], link: Optional[str]) -> tuple[str, list]:
    """
    Row-identity WHERE clause. Each key column supplied narrows the target;
    omitting them widens it to every row sharing what was given, so callers
    holding only (company, date_added) keep the pre-migration group behavior.
    """
    where = ["company = ?", "date_added = ?"]
    params = []
    if position_title is not None:
        where.append("position_title = ?")
        params.append(position_title)
    if link is not None:
        where.append("link = ?")
        params.append(link)
    return " AND ".join(where), params


def update_field(company: str, date_added: str, field: str, value: str,
                 position_title: Optional[str] = None,
                 link: Optional[str] = None) -> bool:
    """
    Updates a single field on the job row identified by
    (company, date_added, position_title, link). Returns True if a row was updated.
    """
    if field not in set(COLUMNS) - {"company", "date_added"}:
        raise ValueError(f"Field '{field}' is not updatable.")
    conn = _connect()
    if not conn:
        return False
    try:
        where, extra = _key_clause(position_title, link)
        cur = conn.execute(
            f"UPDATE jobs SET {field} = ? WHERE {where}",
            [value, company, date_added] + extra
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_job_fields(company: str, date_added: str, updates: dict,
                      position_title: Optional[str] = None,
                      link: Optional[str] = None) -> bool:
    """
    Update several columns on one row in a single statement. The multi-column
    sibling of update_field, for callers merging a batch of changes into a row
    they have already identified -- doing that through update_field would open
    and close a connection per column.

    The caller must pass the key of the row it found, not the key implied by
    whatever data it is merging in. An importer that keys off its own payload
    instead will miss the row and insert a duplicate beside it.
    """
    updatable = set(COLUMNS) - {"company", "date_added"}
    bad = set(updates) - updatable
    if bad:
        raise ValueError(f"Fields {sorted(bad)} are not updatable.")
    if not updates:
        return False
    conn = _connect()
    if not conn:
        return False
    try:
        where, extra = _key_clause(position_title, link)
        sets = ", ".join(f"{c} = ?" for c in updates)
        cur = conn.execute(
            f"UPDATE jobs SET {sets} WHERE {where}",
            list(updates.values()) + [company, date_added] + extra
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def mark_outreached(company: str, date_added: str, outreach_date: str,
                    position_title: Optional[str] = None,
                    link: Optional[str] = None) -> bool:
    return update_field(company, date_added, "outreach_date", outreach_date,
                        position_title, link)


def update_status(company: str, date_added: str, status: str,
                  position_title: Optional[str] = None,
                  link: Optional[str] = None) -> bool:
    return update_field(company, date_added, "status", status, position_title, link)


def update_notes(company: str, date_added: str, notes: str,
                 position_title: Optional[str] = None,
                 link: Optional[str] = None) -> bool:
    return update_field(company, date_added, "notes", notes, position_title, link)


def update_summary(company: str, date_added: str, job_summary: str,
                   position_title: Optional[str] = None,
                   link: Optional[str] = None) -> bool:
    return update_field(company, date_added, "job_summary", job_summary,
                        position_title, link)


def update_contacts(company: str, date_added: str, contacts: str,
                    position_title: Optional[str] = None,
                    link: Optional[str] = None) -> bool:
    return update_field(company, date_added, "contacts", contacts, position_title, link)


def delete_job_by_key(company: str, date_added: str,
                      position_title: Optional[str] = None,
                      link: Optional[str] = None) -> bool:
    """
    Hard-deletes the job row identified by (company, date_added, position_title, link).
    Omitting the trailing key columns deletes every row sharing what was given.
    Returns True if at least one row was deleted.
    """
    conn = _connect()
    if not conn:
        return False
    try:
        where, extra = _key_clause(position_title, link)
        cur = conn.execute(f"DELETE FROM jobs WHERE {where}", [company, date_added] + extra)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_job(company: str) -> int:
    """
    Hard-deletes all rows for a company from the local DB.
    Returns the number of rows deleted. Silently no-ops if the DB file doesn't exist.
    """
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.execute("DELETE FROM jobs WHERE LOWER(company) = LOWER(?)", (company,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def archive_jobs(days: int = 60, dry_run: bool = False) -> dict:
    """
    Soft-archives (sets archived=1) all non-archived jobs where date_added is
    more than `days` days ago. Archived rows are excluded from get_all_jobs()
    and company lookups by default, but stay in the same table.
    - dry_run: if True, returns which jobs would be archived without writing.
    """
    conn = _connect()
    if not conn:
        return {"dry_run": dry_run, "count": 0, "companies": []}

    try:
        cutoff = date.today() - timedelta(days=days)
        rows = conn.execute(
            "SELECT * FROM jobs WHERE archived = 0"
        ).fetchall()
        to_archive = [
            dict(r) for r in rows
            if _parse_date(r["date_added"]) and _parse_date(r["date_added"]) < cutoff
        ]

        if not dry_run and to_archive:
            conn.executemany(
                "UPDATE jobs SET archived = 1 WHERE company = ? AND date_added = ?",
                [(r["company"], r["date_added"]) for r in to_archive]
            )
            conn.commit()

        return {
            "dry_run": dry_run,
            "count": len(to_archive),
            "companies": [r["company"] for r in to_archive],
        }
    finally:
        conn.close()


def get_all_jobs(include_archived: bool = False) -> list[dict]:
    """Returns all jobs in the local DB, excluding archived rows by default."""
    conn = _connect()
    if not conn:
        return []
    try:
        query = "SELECT * FROM jobs"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY date_added DESC"
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _stats_jobs(include_archived: bool = False) -> list[dict]:
    """
    The job rows the derived-stats helpers read, fetched at most once per scope.

    Separate from get_all_jobs() for two reasons. It drops job_summary, which is
    two thirds of the table by bytes and which none of the stats functions reads
    -- 3521KB and 287ms becomes 978KB and 164ms. And inside a shared_connection()
    it memoises, because funnel_stats, classify_interviews and job_silence_stats
    each pulled the whole table independently: rendering /insights fetched the
    same rows three times.

    get_all_jobs() keeps returning every column, because the MCP server and the
    importer do read job_summary.

    Always fetches the archived rows too and filters here. The three callers want
    different subsets, and one fetch plus a list comprehension beats a second
    round trip.
    """
    scope = _SCOPE.get()
    if scope is not None and scope.jobs is not None:
        rows = scope.jobs
    else:
        conn = _connect()
        if not conn:
            return []
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT %s, archived FROM jobs ORDER BY date_added DESC"
                % ", ".join(LIST_COLUMNS)).fetchall()]
        finally:
            conn.close()
        if scope is not None:
            scope.jobs = rows
    if include_archived:
        return list(rows)
    return [r for r in rows if not r.get("archived")]


def export_csv(jobs: list[dict], fileobj) -> None:
    """Writes `jobs` as CSV (COLUMNS as header) to the given file-like object."""
    writer = csv.DictWriter(fileobj, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for job in jobs:
        writer.writerow(job)


def export_csv_string(jobs: list[dict]) -> str:
    """Returns `jobs` rendered as a CSV string (COLUMNS as header)."""
    buf = io.StringIO()
    export_csv(jobs, buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

INTERVIEW_TYPES = [
    "recruiter_screen",
    "phone_screen",
    "technical",
    "behavioral",
    "system_design",
    "take_home",
    "pair_programming",
    "final_round",
    "other",
]

INTERVIEW_COLUMNS = [
    "id", "company", "date_added", "position_title", "link",
    "interview_type", "type_label", "loop_id", "occurred_date",
    "self_rating", "notes",
]

# Terminal job statuses, matched case-insensitively against jobs.status.
TERMINAL_FAIL_STATUSES = {"rejected"}
TERMINAL_WIN_STATUSES = {"offer", "accepted"}

# Silence this long after a round, with nothing following it and no terminal
# status, is a decision that was made and never communicated. Two weeks is the
# point where a process that is still alive normally says something, even if
# only to apologise for the delay.
#
# This trades precision for recall: at 15 days some genuinely slow loops get
# called ghosted, where 30 days let real ghostings sit as 'awaiting outcome' for a
# month. The rate treats both as decided, so the shorter threshold makes it
# move sooner and read slightly pessimistic rather than slightly flattering.
# A percentage over a handful of rounds is a claim the sample cannot support:
# two phone screens that went nowhere is a fact, while "0.0%" reads as a verdict
# on your phone-screen ability. Below this many DECIDED rounds the counts are
# shown and the percentage is withheld.
#
# Deliberately lower than the funnel's RATE_MIN_DENOMINATOR (30): interviews are
# far rarer than applications, so reusing 30 would hide the rate essentially
# forever rather than merely until it means something.
INTERVIEW_RATE_MIN_ROUNDS = 8

GHOSTED_AFTER_DAYS = 15

_INTERVIEWS_DDL = """
        CREATE TABLE IF NOT EXISTS interviews (
            id             INTEGER PRIMARY KEY,
            company        TEXT NOT NULL,
            date_added     TEXT NOT NULL DEFAULT '',
            position_title TEXT NOT NULL DEFAULT '',
            link           TEXT NOT NULL DEFAULT '',
            interview_type TEXT NOT NULL,
            type_label     TEXT,
            loop_id        TEXT,
            scheduled_date TEXT,
            occurred_date  TEXT,
            self_rating    INTEGER,
            notes          TEXT
        )
"""


def _ensure_interviews_schema(conn: sqlite3.Connection) -> None:
    """
    The job key is copied in as plain columns rather than referenced.

    `jobs` is rebuilt wholesale by _migrate_key(), and sync_jobs_to_sqlite.py
    writes with INSERT OR REPLACE, which SQLite implements as delete-then-insert.
    Either one reassigns every rowid, so a rowid foreign key would dangle and
    ON DELETE CASCADE would take the interview history down with it — silently,
    on a routine sync. Interview rounds are the one thing in this DB that cannot
    be re-fetched from anywhere, so they survive by construction.
    """
    conn.execute(_INTERVIEWS_DDL)
    try:
        conn.execute("ALTER TABLE interviews ADD COLUMN scheduled_date TEXT")
    except _SCHEMA_EXC:
        pass  # column already exists
    _migrate_interviews_nullable_occurred(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interviews_job "
        "ON interviews (company, date_added, position_title, link)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interviews_type ON interviews (interview_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interviews_loop ON interviews (loop_id)")


def _migrate_interviews_nullable_occurred(conn: sqlite3.Connection) -> None:
    """
    Drops NOT NULL from interviews.occurred_date on databases created before
    scheduled rounds existed.

    CREATE TABLE IF NOT EXISTS does not alter an existing table and SQLite cannot
    ALTER a column constraint, so the table has to be rebuilt. Caught only
    against the live DB — every test builds a fresh one from the current DDL and
    so never sees the old constraint.

    No-op once migrated.
    """
    cols = conn.execute("PRAGMA table_info(interviews)").fetchall()
    if not cols:
        return
    # row[1] = name, row[3] = notnull
    if not any(row[1] == "occurred_date" and row[3] for row in cols):
        return

    conn.execute(_INTERVIEWS_DDL.replace("interviews", "interviews_migrated"))
    conn.execute(
        "INSERT INTO interviews_migrated (id, company, date_added, position_title, link, "
        " interview_type, type_label, loop_id, scheduled_date, occurred_date, self_rating, notes) "
        "SELECT id, company, date_added, position_title, link, interview_type, type_label, "
        "       loop_id, scheduled_date, occurred_date, self_rating, notes FROM interviews"
    )
    conn.execute("DROP TABLE interviews")
    conn.execute("ALTER TABLE interviews_migrated RENAME TO interviews")
    conn.commit()


def add_interview(company: str, date_added: str, position_title: str, link: str,
                  interview_type: str, occurred_date: str = "", type_label: str = "",
                  loop_id: str = "", self_rating: Optional[int] = None,
                  notes: str = "", scheduled_date: str = "") -> int:
    """
    Records one interview round — booked, held, or both. Returns the new row id.

    The two dates mean different things and only one of them can carry weight:

      * `scheduled_date` — it is on the calendar. Says nothing about whether it
        happens; invites get cancelled and rescheduled constantly.
      * `occurred_date`  — it took place. ONLY this makes a round count toward
        any outcome or rate.

    A row with a scheduled_date and no occurred_date is upcoming, and
    classify_interviews() skips it entirely: an invite is not evidence a round
    happened, and counting it would inflate the denominator with rounds that may
    never occur. When it does happen, set occurred_date via
    mark_interview_occurred().

    At least one date is required — a round that is neither booked nor held is
    not an event.
    """
    if interview_type not in INTERVIEW_TYPES:
        raise ValueError(
            f"Unknown interview_type '{interview_type}'. One of: {', '.join(INTERVIEW_TYPES)}"
        )
    occurred_date = (occurred_date or "").strip()
    scheduled_date = (scheduled_date or "").strip()
    if not occurred_date and not scheduled_date:
        raise ValueError(
            "one of occurred_date (it happened) or scheduled_date (it is booked) is required."
        )
    if self_rating is not None and not (1 <= int(self_rating) <= 5):
        raise ValueError("self_rating must be between 1 and 5, or None.")

    conn = _connect(create=True)
    try:
        cur = conn.execute(
            "INSERT INTO interviews (company, date_added, position_title, link, "
            "interview_type, type_label, loop_id, scheduled_date, occurred_date, "
            "self_rating, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (company, date_added, position_title, link, interview_type,
             type_label or None, loop_id or None, scheduled_date or None,
             occurred_date or None,
             int(self_rating) if self_rating is not None else None, notes or None),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_interview(interview_id: int) -> int:
    """Deletes one interview round by id. Returns rows removed."""
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_interviews(company: str = "", date_added: str = "", position_title: str = "",
                   link: str = "") -> list[dict]:
    """
    Returns interview rounds, oldest first. With no arguments, returns all of them;
    pass the full job key to scope to one posting.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        query = "SELECT * FROM interviews"
        params: list = []
        if company:
            clauses = ["LOWER(company) = LOWER(?)"]
            params.append(company)
            for col, val in (("date_added", date_added), ("position_title", position_title),
                             ("link", link)):
                if val:
                    clauses.append(f"{col} = ?")
                    params.append(val)
            query += " WHERE " + " AND ".join(clauses)
        # COALESCE so an upcoming round (no occurred_date) sorts by when it is
        # booked instead of clustering at the top as a NULL.
        query += " ORDER BY COALESCE(occurred_date, scheduled_date) ASC, id ASC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()

def get_upcoming_interviews(company: str = "", date_added: str = "", position_title: str = "",
                            link: str = "", include_past: bool = False) -> list[dict]:
    """
    Rounds that are booked and not yet held, soonest first. With no arguments,
    returns every one of them; pass the full job key to scope to one posting.

    "Booked and not yet held" is the pair of clauses below: a scheduled_date, and
    no occurred_date. By default the date must also be today or later, so a
    booking whose date has passed with nothing recorded against it does not come
    back as though it were still ahead. Pass include_past=True to retrieve those
    too -- they are the forgotten paperwork, and they still exist.

    Dates are stored as ISO YYYY-MM-DD text, which orders and compares correctly
    as a string. Today's date is bound as a parameter rather than asked of SQLite,
    so a test that pins the clock still gets the answer it pinned.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        clauses = ["COALESCE(scheduled_date, '') <> ''", "COALESCE(occurred_date, '') = ''"]
        params: list = []
        if not include_past:
            clauses.append("scheduled_date >= ?")
            params.append(date.today().isoformat())
        if company:
            clauses.append("LOWER(company) = LOWER(?)")
            params.append(company)
            for col, val in (("date_added", date_added), ("position_title", position_title),
                             ("link", link)):
                if val:
                    clauses.append(f"{col} = ?")
                    params.append(val)
        query = ("SELECT * FROM interviews WHERE " + " AND ".join(clauses)
                 + " ORDER BY scheduled_date ASC, id ASC")
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def _unit_key(row: dict) -> tuple:
    """A loop is one unit; a standalone round is a unit of one."""
    if row.get("loop_id"):
        return ("loop", row["loop_id"])
    return ("round", row["id"])


def classify_interviews() -> list[dict]:
    """
    Labels every interview round 'advanced', 'failed', or 'awaiting_outcome'.

    No verdict is ever stored, because for most rounds it is not observable — a
    rejection email after a four-round loop does not say which round lost it.
    What IS observable is whether the process continued, so that is what gets
    derived here:

      * a later unit exists for this job  -> advanced
      * last unit, job status Rejected    -> failed
      * last unit, job status Offer/Accepted -> advanced
      * last unit, job active, silent 30d+ -> ghosted (counts against the rate)
      * last unit, job still active       -> awaiting_outcome (excluded from the rate)

    Loops are atomic: rounds sharing a loop_id resolve together and every round
    in the loop inherits the loop's outcome. Ordering rounds inside a same-day
    onsite by date would otherwise mark the earlier ones 'advanced' for merely
    having siblings and pin the whole loop's failure on whichever one sorted last.
    """
    # A booked-but-not-held round is not evidence of anything. Including it
    # would put rounds that may never occur into the denominator, which is the
    # exact error `occurred_date` exists to prevent.
    rows = [r for r in get_interviews() if (r.get("occurred_date") or "").strip()]
    if not rows:
        return []

    status_by_key = {
        (j["company"], j["date_added"], j["position_title"], j["link"]):
            (j.get("status") or "").strip().lower()
        for j in _stats_jobs(include_archived=True)
    }

    by_job: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r["company"], r["date_added"], r["position_title"], r["link"])
        by_job.setdefault(key, []).append(r)

    out: list[dict] = []
    for key, job_rows in by_job.items():
        units: dict[tuple, list[dict]] = {}
        for r in job_rows:
            units.setdefault(_unit_key(r), []).append(r)
        # get_interviews() already sorted by occurred_date, so ordering units by
        # their earliest round preserves that order across loops.
        ordered = sorted(units.values(), key=lambda u: (u[0]["occurred_date"], u[0]["id"]))

        status = status_by_key.get(key)
        for i, unit in enumerate(ordered):
            if i < len(ordered) - 1:
                outcome = "advanced"
            elif status is None:
                outcome = "awaiting_outcome"   # job row gone (link changed?) — never guess
            elif status in TERMINAL_FAIL_STATUSES:
                outcome = "failed"
            elif status in TERMINAL_WIN_STATUSES:
                outcome = "advanced"
            else:
                # Nothing followed this round and the job never closed. Past the
                # silence threshold that is a ghosting, not an open process.
                last_seen = max(_parse_date(r["occurred_date"]) or date.min for r in unit)
                idle = (date.today() - last_seen).days if last_seen != date.min else 0
                outcome = "ghosted" if idle >= GHOSTED_AFTER_DAYS else "awaiting_outcome"
            for r in unit:
                out.append({**r, "outcome": outcome, "job_orphaned": status is None})
    return out


def interview_stats() -> dict:
    """
    Round outcomes per interview type. The single source of this computation —
    the GUI view and the MCP tool both call it so the two can never disagree.

    Rate = advanced / (advanced + failed + ghosted). Only awaiting_outcome rounds
    are excluded from the denominator: every job's most recent round has no
    successor yet, so counting those as failures would drag every rate down and
    hit whichever types you interviewed for most recently the hardest. A ghosted
    round IS counted — it demonstrably did not advance you.

    Booked-but-not-held rounds never reach this at all; classify_interviews()
    drops them before any of it runs.
    """
    classified = classify_interviews()

    def blank() -> dict:
        return {"advanced": 0, "failed": 0, "ghosted": 0, "awaiting_outcome": 0}

    by_type: dict[str, dict] = {}
    for r in classified:
        entry = by_type.setdefault(r["interview_type"], {
            "interview_type": r["interview_type"],
            "total": blank(), "standalone": blank(), "loop": blank(),
        })
        bucket = "loop" if r.get("loop_id") else "standalone"
        entry["total"][r["outcome"]] += 1
        entry[bucket][r["outcome"]] += 1

    def score(c: dict) -> None:
        """
        Adds `decided` and `rate` in place.

        Ghosted rounds are in the denominator: they demonstrably did not advance
        you. Leaving them out would compute a rate only over companies polite
        enough to send a rejection, which is not the population you interview with.

        `decided` is always reported; `rate` is withheld below
        INTERVIEW_RATE_MIN_ROUNDS so the caller can say "0 of 2 advanced" rather
        than print a percentage the sample cannot support.
        """
        c["decided"] = c["advanced"] + c["failed"] + c["ghosted"]
        c["rate"] = (round(100.0 * c["advanced"] / c["decided"], 1)
                     if c["decided"] >= INTERVIEW_RATE_MIN_ROUNDS else None)

    rows = []
    for t in INTERVIEW_TYPES:
        if t not in by_type:
            continue
        e = by_type[t]
        for scope in ("total", "standalone", "loop"):
            score(e[scope])
        rows.append(e)

    return {
        "by_type": rows,
        "totals": {
            "rounds": len(classified),
            "advanced": sum(1 for r in classified if r["outcome"] == "advanced"),
            "failed": sum(1 for r in classified if r["outcome"] == "failed"),
            "ghosted": sum(1 for r in classified if r["outcome"] == "ghosted"),
            "awaiting_outcome": sum(1 for r in classified if r["outcome"] == "awaiting_outcome"),
            "orphaned": sum(1 for r in classified if r["job_orphaned"]),
            "decided": sum(1 for r in classified
                           if r["outcome"] in ("advanced", "failed", "ghosted")),
        },
        "rate_min_rounds": INTERVIEW_RATE_MIN_ROUNDS,
    }


# ---------------------------------------------------------------------------
# Application funnel
# ---------------------------------------------------------------------------

# Statuses that mean "currently sitting at an interview stage". This reads
# CURRENT state, not history: a job that reached a phone screen and was then
# rejected reads only as 'Rejected', so this stage is a floor, not a total.
SCREEN_STATUSES = {"phone screen", "technical", "system design", "behavioral", "final round"}

# A screen filters for plausibility; an evaluation tests whether you can do the
# job. The funnel's last stage counts only the latter, so a 15-minute recruiter
# call cannot graduate a job to "interviewed" — screens stop at the screen stage.
SCREENING_TYPES = {"recruiter_screen", "phone_screen"}
EVALUATION_TYPES = {
    "technical", "behavioral", "system_design",
    "take_home", "pair_programming", "final_round", "other",
}

# Source detection is a string match on notes, not a real column — the ApplyPass
# importer stamps its provenance there. Correct today, and quietly wrong if that
# wording ever changes.
_AUTO_MARKERS = ("applypass", "auto-appl")

# Below this many rows a conversion percentage is noise dressed as a finding, so
# the stage shows a bare count instead.
RATE_MIN_DENOMINATOR = 30


def _is_auto(job: dict) -> bool:
    notes = (job.get("notes") or "").lower()
    return any(m in notes for m in _AUTO_MARKERS)


def funnel_stats() -> dict:
    """
    Two-path application funnel, precomputed for each source filter.

    Applying and outreaching turned out to be alternative routes rather than
    sequential stages — of the tracked jobs, hundreds applied without ever
    outreaching, dozens outreached without ever applying, and none did the two on
    different days. So a single linear funnel would render most rows as attrition
    at a stage they never intended to enter. These are two parallel paths that
    converge only at 'interviewed'.

    Rejections are reported alongside rather than inside a path: a rejection is an
    exit, not a step toward an interview.
    """
    # Archived rows are INCLUDED deliberately. Archiving retires jobs older than
    # 60 days from the working table, but a funnel is a historical record and a
    # finished outcome is its most useful input — excluding them drops the
    # majority of outreach history and makes that path look inert.
    jobs = _stats_jobs(include_archived=True)

    rounds = get_interviews()
    def _keys(types):
        return {
            (r["company"], r["date_added"], r["position_title"], r["link"])
            for r in rounds if r["interview_type"] in types
        }
    evaluated_keys = _keys(EVALUATION_TYPES)
    screened_keys = _keys(SCREENING_TYPES)

    def build(rows: list[dict]) -> dict:
        applied = [j for j in rows if (j.get("date_applied") or "").strip()]
        outreached = [j for j in rows if (j.get("outreach_date") or "").strip()]

        def _key(j):
            return (j["company"], j["date_added"], j["position_title"], j["link"])

        def interviewed(subset):
            return sum(1 for j in subset if _key(j) in evaluated_keys)

        def at_screen(subset):
            # Either sitting at a screening status now, or a screening round was
            # logged — a job that was screened and then rejected still reached
            # this stage, and status alone would forget that.
            return sum(
                1 for j in subset
                if (j.get("status") or "").strip().lower() in SCREEN_STATUSES
                or _key(j) in screened_keys
            )

        # An interview can belong to neither path: Base-Power-style rows that came
        # through a contact have no application date and no outreach date. Those
        # would silently vanish from a two-path funnel and make this card
        # contradict the interview table below it, so they are counted out loud.
        interviewed_jobs = [j for j in rows if _key(j) in evaluated_keys]
        unattributed = [
            j for j in interviewed_jobs
            if not (j.get("date_applied") or "").strip() and not (j.get("outreach_date") or "").strip()
        ]

        return {
            "interviewed_total": len(interviewed_jobs),
            "interviewed_unattributed": len(unattributed),
            "application_path": [
                {"stage": "tracked", "count": len(rows)},
                {"stage": "applied", "count": len(applied)},
                {"stage": "at screen", "count": at_screen(applied)},
                {"stage": "interviewed", "count": interviewed(applied)},
            ],
            "outreach_path": [
                {"stage": "tracked", "count": len(rows)},
                {"stage": "outreached", "count": len(outreached)},
                {"stage": "replied", "count": None},   # no reply field exists — never render as 0
                {"stage": "interviewed", "count": interviewed(outreached)},
            ],
            "rejected": sum(1 for j in rows if (j.get("status") or "").strip().lower() == "rejected"),
            "both_paths": sum(
                1 for j in rows
                if (j.get("date_applied") or "").strip() and (j.get("outreach_date") or "").strip()
            ),
        }

    sources = {
        "all": jobs,
        "hand": [j for j in jobs if not _is_auto(j)],
        "auto": [j for j in jobs if _is_auto(j)],
    }
    data = {name: build(rows) for name, rows in sources.items()}

    # Conversion is relative to the stage above it, and only shown once the
    # denominator is big enough to mean anything.
    for payload in data.values():
        for path in ("application_path", "outreach_path"):
            prev = None
            for stage in payload[path]:
                if stage["count"] is None or prev is None or prev < RATE_MIN_DENOMINATOR:
                    stage["rate"] = None
                else:
                    stage["rate"] = round(100.0 * stage["count"] / prev, 1)
                # An unmeasured stage poisons everything downstream: a conversion
                # computed ACROSS the gap would silently claim to measure what the
                # gap says we cannot. Outreach with no reply tracking must read as
                # unknown, never as 0%.
                prev = None if stage["count"] is None else stage["count"]

    return {"sources": data, "rate_min_denominator": RATE_MIN_DENOMINATOR}


# --- Recruiters -------------------------------------------------------------
# A recruiter pitches N roles, so the relationship is one-to-many and the roles
# are ordinary job rows. What `jobs` cannot hold is the recruiter themselves:
# sync_jobs_to_sqlite.py writes only the 12 sheet COLUMNS, so any extra column
# on `jobs` is reset by a sync. Linkage therefore lives on the recruiter side.

_RECRUITERS_DDL = """
        CREATE TABLE IF NOT EXISTS recruiters (
            id            INTEGER PRIMARY KEY,
            source        TEXT NOT NULL,
            identity      TEXT NOT NULL,
            email         TEXT,
            name          TEXT,
            agency        TEXT,
            agency_domain TEXT,
            first_seen    TEXT NOT NULL,
            last_seen     TEXT,
            notes         TEXT,
            UNIQUE (source, identity)
        )
"""

_RECRUITER_JOBS_DDL = """
        CREATE TABLE IF NOT EXISTS recruiter_jobs (
            id             INTEGER PRIMARY KEY,
            recruiter_id   INTEGER NOT NULL,
            company        TEXT NOT NULL,
            date_added     TEXT NOT NULL DEFAULT '',
            position_title TEXT NOT NULL DEFAULT '',
            link           TEXT NOT NULL DEFAULT '',
            sourced_date   TEXT NOT NULL,
            account        TEXT,
            message_id     TEXT,
            UNIQUE (recruiter_id, company, date_added, position_title, link)
        )
"""

_RECRUITER_MESSAGES_DDL = """
        CREATE TABLE IF NOT EXISTS recruiter_messages (
            id            INTEGER PRIMARY KEY,
            recruiter_id  INTEGER NOT NULL,
            direction     TEXT NOT NULL,
            occurred_date TEXT NOT NULL,
            subject       TEXT,
            account       TEXT NOT NULL DEFAULT 'primary',
            message_id    TEXT,
            thread_id     TEXT,
            UNIQUE (account, message_id)
        )
"""

# The one-way Drive export. jobs.db is gitignored and recruiter identity cannot
# be reconstructed from the Sheet, so it needs a copy off this disk, same as
# interviews.
RECRUITER_COLUMNS = [
    "source", "identity", "name", "agency", "email", "agency_domain",
    "first_seen", "last_seen", "role_count", "reply_count", "notes",
    # Carried outward deliberately: a hand-entered recruiter is the one kind
    # this export cannot reconstruct, since no message exists to re-derive them
    # from. Losing the flag would also lose which names are human-owned.
    "manual_entry",
]

RECRUITER_JOB_COLUMNS = [
    "recruiter_identity", "recruiter_name", "recruiter_agency",
    "company", "position_title", "sourced_date", "link", "job_status",
]

RECRUITER_SOURCES = ("email", "linkedin")
MESSAGE_DIRECTIONS = ("inbound", "reply")

# Gmail ids are per-account, so the primary and alt inboxes occupy separate id
# spaces. Uniqueness is the pair; a bare message_id would reject a legitimate
# alt-inbox message that happened to collide with a primary one.
MESSAGE_ACCOUNTS = ("primary", "alt")


def _ensure_recruiters_schema(conn: sqlite3.Connection) -> None:
    """
    Same rule as interviews: the job key is copied in, never referenced.

    _migrate_key() rebuilds `jobs` wholesale and sync_jobs_to_sqlite.py writes
    with INSERT OR REPLACE (delete-then-insert). Both reassign every rowid, so a
    rowid foreign key would dangle and ON DELETE CASCADE would empty these tables
    on a routine sync.
    """
    conn.execute(_RECRUITERS_DDL)
    conn.execute(_RECRUITER_JOBS_DDL)
    conn.execute(_RECRUITER_MESSAGES_DDL)
    # Marks a recruiter a human typed in, so upsert_recruiter can stop a later
    # parse from overwriting the name and agency they entered. Added by ALTER
    # rather than a table rebuild -- the rebuild dance in _migrate_key() exists
    # to change a primary key, which this does not.
    try:
        conn.execute(
            "ALTER TABLE recruiters ADD COLUMN manual_entry INTEGER NOT NULL DEFAULT 0"
        )
    except _SCHEMA_EXC:
        pass  # column already exists
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recruiter_jobs_job "
        "ON recruiter_jobs (company, date_added, position_title, link)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recruiter_jobs_recruiter "
        "ON recruiter_jobs (recruiter_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recruiter_messages_recruiter "
        "ON recruiter_messages (recruiter_id)"
    )


def _slugify(value: str) -> str:
    """Lowercase, alphanumerics and single hyphens. Empty input yields 'role'."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "role"


def recruiter_link(source: str, identity: str, position_title: str) -> str:
    """
    The synthetic `link` for a recruiter-sourced role.

    Recruiter roles have no posting URL, but `link` is part of the jobs primary
    key, so two roles pitched by one recruiter on one day would collide — which
    is exactly how one row came to be titled
    'Frontend Engineer / Cloud Backend Engineer'.

    Keying on (source, identity) rather than the raw address matters for
    LinkedIn: InMail arrives from the shared relay inmail-hit-reply@linkedin.com,
    so an address-keyed link would collapse every LinkedIn recruiter's roles
    together. Deterministic by construction, so re-processing the same message
    updates rather than duplicates.
    """
    return f"recruiter:{source}:{identity}/{_slugify(position_title)}"


def upsert_recruiter(source: str, identity: str, name: str = "", agency: str = "",
                     email: str = "", agency_domain: str = "", notes: str = "",
                     seen_date: str = "", manual_entry: bool = False) -> int:
    """
    Creates or updates one recruiter, returning its id.

    Identity is (source, identity) — an address for mail, a profile slug for
    LinkedIn — because InMail has no per-recruiter sender address. `email` is
    stored separately and may be blank for that reason.

    Only ever widens what is known: a later message with no `agency` must not
    erase an agency learned earlier.

    `manual_entry` marks a recruiter a human entered through the GUI, and on
    those rows `name` and `agency` become theirs: filled if blank, never
    replaced. Widening is not enough protection there, because a signature block
    parsed down to "Jo" is a non-empty value and would otherwise overwrite a
    hand-typed "Joanna Reyes". `email`, `agency_domain` and `last_seen` stay on
    the widen-and-overwrite path -- those are machine facts, and discovering the
    address of a recruiter entered by hand is the point.

    The flag only ever turns on (MAX), so a human correcting an auto-created
    recruiter keeps the protection from then on.

    A hand-added recruiter is keyed source='email' with their address as the
    identity, deliberately NOT a separate 'manual' source: UNIQUE(source,
    identity) would make ('manual', addr) and ('email', addr) two rows for one
    person, so keying on provenance is what would create the duplicate it looks
    like it prevents.
    """
    if source not in RECRUITER_SOURCES:
        raise ValueError(
            f"Unknown recruiter source '{source}'. One of: {', '.join(RECRUITER_SOURCES)}"
        )
    if not identity or not identity.strip():
        raise ValueError("identity is required — it is half the recruiter key.")

    identity = identity.strip()
    seen = seen_date.strip() if seen_date and seen_date.strip() else ""
    today = seen or date.today().isoformat()

    conn = _connect(create=True)
    try:
        row = conn.execute(
            "SELECT id FROM recruiters WHERE source = ? AND identity = ?",
            (source, identity),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE recruiters SET "
                # Human-owned on manual rows: fill a blank, never replace.
                "  name = CASE WHEN manual_entry = 1 "
                "              THEN COALESCE(NULLIF(name, ''), NULLIF(?, '')) "
                "              ELSE COALESCE(NULLIF(?, ''), name) END, "
                "  agency = CASE WHEN manual_entry = 1 "
                "                THEN COALESCE(NULLIF(agency, ''), NULLIF(?, '')) "
                "                ELSE COALESCE(NULLIF(?, ''), agency) END, "
                "  email = COALESCE(NULLIF(?, ''), email), "
                "  agency_domain = COALESCE(NULLIF(?, ''), agency_domain), "
                "  notes = COALESCE(NULLIF(?, ''), notes), "
                "  last_seen = MAX(COALESCE(last_seen, ''), ?), "
                "  manual_entry = MAX(manual_entry, ?) "
                "WHERE id = ?",
                (name, name, agency, agency, email, agency_domain, notes, seen,
                 1 if manual_entry else 0, row["id"]),
            )
            conn.commit()
            return row["id"]

        cur = conn.execute(
            "INSERT INTO recruiters (source, identity, email, name, agency, "
            "agency_domain, first_seen, last_seen, notes, manual_entry) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, identity, email or None, name or None, agency or None,
             agency_domain or None, today, today, notes or None,
             1 if manual_entry else 0),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def link_recruiter_job(recruiter_id: int, company: str, date_added: str,
                       position_title: str, link: str, sourced_date: str = "",
                       account: str = "", message_id: str = "") -> int:
    """
    Records that this recruiter sourced this job row. Returns the link row id.

    Idempotent on the full (recruiter, job key) tuple, so re-processing a message
    re-links rather than duplicating.
    """
    sourced = sourced_date.strip() if sourced_date and sourced_date.strip() \
        else date.today().isoformat()
    conn = _connect(create=True)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO recruiter_jobs (recruiter_id, company, date_added, "
            "position_title, link, sourced_date, account, message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (recruiter_id, company, date_added, position_title, link, sourced,
             account or None, message_id or None),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM recruiter_jobs WHERE recruiter_id = ? AND company = ? "
            "AND date_added = ? AND position_title = ? AND link = ?",
            (recruiter_id, company, date_added, position_title, link),
        ).fetchone()
        return row["id"] if row else 0
    finally:
        conn.close()


def unlink_recruiter_job(recruiter_id: int, company: str, date_added: str,
                         position_title: str, link: str) -> int:
    """
    Removes one recruiter/job link. Returns how many rows went (0 or 1).

    The counterpart link_recruiter_job never had, because until the GUI could
    assign a recruiter nothing ever needed to take one back.
    """
    conn = _connect(create=True)
    try:
        cur = conn.execute(
            "DELETE FROM recruiter_jobs WHERE recruiter_id = ? AND company = ? "
            "AND date_added = ? AND position_title = ? AND link = ?",
            (recruiter_id, company, date_added, position_title, link),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def recruiter_exists(recruiter_id: int) -> bool:
    """Whether a recruiter row with this id is present."""
    conn = _connect()
    if not conn:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def job_recruiter_links(company: str, date_added: str, position_title: str,
                        link: str) -> list[dict]:
    """Every recruiter link on one job, newest first, with the recruiter joined in."""
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT rj.*, r.name AS recruiter_name, r.agency AS recruiter_agency, "
            "       r.source AS recruiter_source, r.identity AS recruiter_identity, "
            "       r.email AS recruiter_email, r.manual_entry AS recruiter_manual "
            "FROM recruiter_jobs rj "
            "JOIN recruiters r ON r.id = rj.recruiter_id "
            "WHERE rj.company = ? AND rj.date_added = ? "
            "  AND rj.position_title = ? AND rj.link = ? "
            "ORDER BY rj.sourced_date DESC, rj.id DESC",
            (company, date_added, position_title, link),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_job_recruiters() -> dict[tuple, dict]:
    """
    The recruiter to show against each job row, keyed by the composite job key.

    Read whole rather than per row: the list view needs this for every job it
    renders, and recruiter_jobs is a table of tens, not thousands -- one scan
    beats a query per row by a wide margin at any size this reaches.

    A job with more than one recruiter yields the most recent. The schema allows
    several on purpose (an agency and an in-house recruiter can pitch the same
    role, and at least one job here already has two), while the GUI assigns one,
    so this collapses the difference rather than pretending it cannot happen.
    """
    conn = _connect()
    if not conn:
        return {}
    try:
        rows = conn.execute(
            "SELECT rj.company, rj.date_added, rj.position_title, rj.link, "
            "       rj.recruiter_id, rj.message_id, rj.sourced_date, "
            "       r.name AS recruiter_name, r.agency AS recruiter_agency, "
            "       r.identity AS recruiter_identity "
            "FROM recruiter_jobs rj "
            "JOIN recruiters r ON r.id = rj.recruiter_id "
            "ORDER BY rj.sourced_date ASC, rj.id ASC"
        ).fetchall()
        # Ascending, so a later row overwrites an earlier one and the most
        # recent link is what survives per key.
        out: dict[tuple, dict] = {}
        for r in rows:
            d = dict(r)
            key = (d["company"], d["date_added"], d["position_title"], d["link"])
            out[key] = d
        return out
    finally:
        conn.close()


def set_job_recruiter(company: str, date_added: str, position_title: str,
                      link: str, recruiter_id: Optional[int],
                      override: bool = False, sourced_date: str = "") -> dict:
    """
    Points one job at one recruiter, or at none when recruiter_id is None.

    Replacing a link that inbox-triage created is refused unless `override` is
    passed. Such a link carries the message_id of the mail that produced it, and
    triage is idempotent on that message: silently dropping the link means the
    next run recreates it and the correction disappears with nothing to show
    what happened. A link with no message_id was made by hand and is replaced
    freely.

    Returns {"ok": bool, "removed": int, "linked": int|None, "current": dict|None,
    "blocked": [...]} where `blocked` lists the triage links that stopped the
    write and `current` is the link the job carries afterwards.
    """
    key = (company, date_added, position_title, link)

    # There is no foreign key here on purpose -- the job key is copied rather
    # than referenced -- which means nothing else will catch an id that does not
    # exist. An unchecked one writes a recruiter_jobs row that never renders,
    # because job_recruiter_links joins recruiters; and SQLite hands a deleted
    # INTEGER PRIMARY KEY back to the next insert, so the next recruiter created
    # inherits the orphan and reports a role it never pitched.
    if recruiter_id is not None and not recruiter_exists(recruiter_id):
        return {"ok": False, "removed": 0, "linked": None, "blocked": [],
                "error": f"No recruiter with id {recruiter_id}."}

    existing = job_recruiter_links(*key)

    protected = [e for e in existing if (e.get("message_id") or "").strip()]
    if protected and not override:
        return {
            "ok": False,
            "removed": 0,
            "linked": None,
            "current": existing[0] if existing else None,
            "blocked": [
                {
                    "recruiter_id": e["recruiter_id"],
                    "recruiter_name": e.get("recruiter_name"),
                    "message_id": e.get("message_id"),
                    "account": e.get("account"),
                    "sourced_date": e.get("sourced_date"),
                }
                for e in protected
            ],
        }

    removed = 0
    for e in existing:
        if e["recruiter_id"] == recruiter_id:
            continue  # already pointed here; leave its provenance alone
        removed += unlink_recruiter_job(e["recruiter_id"], *key)

    linked = None
    if recruiter_id is not None:
        already = any(e["recruiter_id"] == recruiter_id for e in existing)
        if not already:
            linked = link_recruiter_job(
                recruiter_id, company, date_added, position_title, link,
                sourced_date=sourced_date,
            )
        else:
            linked = next(e["id"] for e in existing if e["recruiter_id"] == recruiter_id)

    if protected and override:
        _note_recruiter_override(protected, key, recruiter_id)

    # `current` is what the job points at now. Returned rather than left for the
    # caller to look up, because this function has just decided it -- and the
    # caller asking again is a second read of a row it already owns.
    now = job_recruiter_links(*key)
    return {"ok": True, "removed": removed, "linked": linked, "blocked": [],
            "current": now[0] if now else None}


def _note_recruiter_override(protected: list[dict], key: tuple,
                             recruiter_id: Optional[int]) -> None:
    """
    Records on the displaced recruiter that a human overrode a triage link.

    Without this the override leaves no trace anywhere, and the next time triage
    fails to recreate the link nobody can tell whether that was intended.
    """
    stamp = date.today().isoformat()
    company, date_added, position_title, _link = key

    # One connection for every note, not one each. A remote connect costs ~84ms
    # (see shared_connection), and two agencies pitching the same role is exactly
    # when this runs -- so the loop is where the cost would land.
    conn = _connect(create=True)
    try:
        for e in protected:
            note = (
                f"{stamp}: link to {company} — {position_title or '(no title)'} "
                f"({date_added}) replaced by hand"
                + (f" with recruiter {recruiter_id}" if recruiter_id else " and cleared")
                + f"; was from message {e.get('message_id')}."
            )
            conn.execute(
                "UPDATE recruiters SET notes = "
                "  CASE WHEN notes IS NULL OR notes = '' THEN ? "
                "       ELSE notes || char(10) || ? END "
                "WHERE id = ?",
                (note, note, e["recruiter_id"]),
            )
        conn.commit()
    finally:
        conn.close()


def update_recruiter(recruiter_id: int, name: Optional[str] = None,
                     agency: Optional[str] = None, email: Optional[str] = None,
                     notes: Optional[str] = None) -> bool:
    """
    Edits a recruiter from the GUI. Only the fields passed are touched.

    Unlike upsert_recruiter this overwrites, including with a blank -- a human
    clearing a wrong agency means it, where a parser yielding nothing does not.
    Editing marks the row manual_entry so the correction is protected from the
    next parse.
    """
    sets, params = [], []
    for col, val in (("name", name), ("agency", agency),
                     ("email", email), ("notes", notes)):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val.strip() or None)
    if not sets:
        return False
    sets.append("manual_entry = 1")
    params.append(recruiter_id)

    conn = _connect(create=True)
    try:
        cur = conn.execute(
            f"UPDATE recruiters SET {', '.join(sets)} WHERE id = ?", params
        )
        conn.commit()
        return (cur.rowcount or 0) > 0
    finally:
        conn.close()


def delete_recruiter(recruiter_id: int, dry_run: bool = False) -> dict:
    """
    Deletes a recruiter with its job links and its recorded messages.

    The messages go too, and that is the only safe option rather than an
    oversight. recruiter_messages is UNIQUE(account, message_id) written with
    INSERT OR IGNORE, so messages left behind keep a recruiter_id pointing at
    nothing; when triage next reads the same mail it recreates the recruiter
    under a new id and every one of those inserts is ignored as a duplicate. The
    rebuilt recruiter would show zero messages, permanently. Taking them means a
    later run can reconstruct the record faithfully.

    Returns the counts so the caller can say what it is about to destroy.

    dry_run counts and stops. The confirm dialog needs both numbers *before*
    anything goes, and it cannot get the message count anywhere else: the one
    the Insights page already has is reply_count, which filters
    direction = 'reply' and so omits every outreach message this would delete.
    Naming a number lower than the truth is the specific failure a confirm on an
    unrecoverable delete exists to prevent, so the count comes from the same
    query the delete itself uses.
    """
    conn = _connect(create=True)
    try:
        row = conn.execute(
            "SELECT name, agency FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "No such recruiter.",
                    "jobs": 0, "messages": 0}

        jobs_n = conn.execute(
            "SELECT COUNT(*) AS n FROM recruiter_jobs WHERE recruiter_id = ?",
            (recruiter_id,),
        ).fetchone()["n"]
        msgs_n = conn.execute(
            "SELECT COUNT(*) AS n FROM recruiter_messages WHERE recruiter_id = ?",
            (recruiter_id,),
        ).fetchone()["n"]

        if dry_run:
            return {"ok": True, "dry_run": True, "name": row["name"],
                    "agency": row["agency"], "jobs": jobs_n, "messages": msgs_n}

        conn.execute("DELETE FROM recruiter_messages WHERE recruiter_id = ?",
                     (recruiter_id,))
        conn.execute("DELETE FROM recruiter_jobs WHERE recruiter_id = ?",
                     (recruiter_id,))
        conn.execute("DELETE FROM recruiters WHERE id = ?", (recruiter_id,))
        conn.commit()
        return {"ok": True, "name": row["name"], "agency": row["agency"],
                "jobs": jobs_n, "messages": msgs_n}
    finally:
        conn.close()


def record_recruiter_message(recruiter_id: int, direction: str, occurred_date: str,
                             subject: str = "", account: str = "primary",
                             message_id: str = "", thread_id: str = "") -> int:
    """
    Records one message to or from a recruiter. Returns the row id.

    Idempotent on (account, message_id) so a re-run records nothing new.
    """
    if direction not in MESSAGE_DIRECTIONS:
        raise ValueError(
            f"direction must be one of: {', '.join(MESSAGE_DIRECTIONS)}"
        )
    if not occurred_date or not occurred_date.strip():
        raise ValueError("occurred_date is required.")
    account = account or "primary"

    conn = _connect(create=True)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO recruiter_messages (recruiter_id, direction, "
            "occurred_date, subject, account, message_id, thread_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (recruiter_id, direction, occurred_date.strip(), subject or None,
             account, message_id or None, thread_id or None),
        )
        conn.execute(
            "UPDATE recruiters SET last_seen = MAX(COALESCE(last_seen, ''), ?) WHERE id = ?",
            (occurred_date.strip(), recruiter_id),
        )
        conn.commit()
        if message_id:
            row = conn.execute(
                "SELECT id FROM recruiter_messages WHERE account = ? AND message_id = ?",
                (account, message_id),
            ).fetchone()
            return row["id"] if row else 0
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


def get_recruiters() -> list[dict]:
    """
    Every recruiter with their role count and last contact, most recent first.

    The role count comes from recruiter_jobs, not from `jobs`, so a role whose
    job row was deleted still shows the recruiter as known.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT r.*, "
            "  (SELECT COUNT(*) FROM recruiter_jobs j WHERE j.recruiter_id = r.id) "
            "    AS role_count, "
            "  (SELECT COUNT(*) FROM recruiter_messages m "
            "    WHERE m.recruiter_id = r.id AND m.direction = 'reply') AS reply_count "
            "FROM recruiters r "
            "ORDER BY COALESCE(r.last_seen, r.first_seen) DESC, r.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recruiter_jobs(recruiter_id: Optional[int] = None) -> list[dict]:
    """
    Recruiter-sourced roles, newest first, joined to the live job row.

    LEFT JOIN on purpose: a link whose job row has since been deleted or re-keyed
    still lists, with nulls for the job columns. Silently dropping it would hide
    exactly the breakage worth seeing.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        query = (
            "SELECT rj.*, r.name AS recruiter_name, r.agency AS recruiter_agency, "
            "       r.source AS recruiter_source, r.identity AS recruiter_identity, "
            "       j.status AS job_status, j.notes AS job_notes "
            "FROM recruiter_jobs rj "
            "JOIN recruiters r ON r.id = rj.recruiter_id "
            "LEFT JOIN jobs j ON j.company = rj.company AND j.date_added = rj.date_added "
            "  AND j.position_title = rj.position_title AND j.link = rj.link"
        )
        params: list = []
        if recruiter_id is not None:
            query += " WHERE rj.recruiter_id = ?"
            params.append(recruiter_id)
        query += " ORDER BY rj.sourced_date DESC, rj.id DESC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def get_recruiter_messages(recruiter_id: Optional[int] = None) -> list[dict]:
    """Messages to and from recruiters, oldest first."""
    conn = _connect()
    if not conn:
        return []
    try:
        query = "SELECT * FROM recruiter_messages"
        params: list = []
        if recruiter_id is not None:
            query += " WHERE recruiter_id = ?"
            params.append(recruiter_id)
        query += " ORDER BY occurred_date ASC, id ASC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


# A recruiter-sourced row is one whose link is a CONVERSATION rather than a job
# posting: inbound outreach arrives as a message, whereas a posting URL means
# Joel went looking. Earlier drafts matched company strings too ('%agency%',
# '%via %') and both patterns produced false positives on real rows — OLIVER
# Agency and LMD Agency are ApplyPass applications to real employers, and the
# AustinWorks and Venture Up rows are postings Joel applied to that happen to be
# agency-placed. Company names are prose; link shape is structural.
_CONVERSATION_LINKS = ("recruiter:%", "mailto:%", "%linkedin.com/messaging%")


def _coverage_tier(status: str) -> int:
    """
    0 = live at a screening stage, 1 = ordinary, 2 = closed.

    Sorting by raw progress would rank Rejected above Tracking, which inverts
    the urgency this list exists to show: an uncaptured role still at a screen
    is a live relationship that is invisible, while an uncaptured Rejected one
    is bookkeeping.
    """
    s = (status or "").strip().lower()
    if s in SCREEN_STATUSES:
        return 0
    if s in TERMINAL_FAIL_STATUSES or s in TERMINAL_WIN_STATUSES:
        return 2
    return 1


def unlinked_recruiter_rows() -> list[dict]:
    """
    Job rows that look recruiter-sourced but are linked to no recruiter.

    Heuristic, and deliberately tuned tight. A miss is invisible and costs
    nothing — the row stays untracked exactly as it is today. A false positive
    is visible on the Insights card, and a handful of them teach you to ignore
    the whole thing. So this accepts misses to buy precision.

    Auto-apply imports are excluded outright: an ApplyPass row is by definition
    an application Joel submitted, not outreach he received.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        link_clause = " OR ".join("j.link LIKE ?" for _ in _CONVERSATION_LINKS)
        rows = conn.execute(
            f"SELECT j.company, j.date_added, j.position_title, j.link, j.status, "
            f"       j.notes, j.date_applied "
            f"FROM jobs j "
            f"WHERE ({link_clause}) "
            f"  AND COALESCE(j.notes, '') NOT LIKE '%auto-apply export%' "
            f"  AND NOT EXISTS (SELECT 1 FROM recruiter_jobs rj "
            f"                  WHERE rj.company = j.company AND rj.date_added = j.date_added "
            f"                    AND rj.position_title = j.position_title AND rj.link = j.link)",
            list(_CONVERSATION_LINKS),
        ).fetchall()
        out = [dict(r) for r in rows]
        out.sort(key=lambda r: (_coverage_tier(r["status"]), _neg_date(r["date_added"])))
        return out
    finally:
        conn.close()


def _neg_date(value: str) -> str:
    """Sort key that puts newer dates first inside a tier."""
    return "".join(chr(255 - ord(c)) for c in (value or ""))


def recruiter_coverage() -> dict:
    """
    Two counts, never a ratio.

    A coverage percentage would need a known denominator, and this one is a
    heuristic that errs in both directions. Worse, the ratio would IMPROVE as
    the heuristic got stricter — tightening the patterns shrinks the denominator
    without capturing a single extra row. Two integers say the same thing
    without claiming a total that cannot be computed, which is the rule
    funnel_stats() already follows for unmeasured stages.
    """
    unlinked = unlinked_recruiter_rows()
    conn = _connect()
    captured = 0
    if conn:
        try:
            # DISTINCT job key, not COUNT(*): recruiter_jobs is many-to-many and
            # two agencies pitching the same role is not two roles. GTE arrived
            # from Jack Dahler and Maddison Jonas within a day of each other, and
            # counting rows would report it twice against a "suspected uncaptured"
            # figure that counts each role once -- two numbers side by side
            # measuring different things.
            captured = conn.execute(
                "SELECT COUNT(*) AS n FROM ("
                "  SELECT DISTINCT company, date_added, position_title, link"
                "  FROM recruiter_jobs)"
            ).fetchone()["n"]
        finally:
            conn.close()
    return {"captured": captured, "suspected_uncaptured": len(unlinked), "rows": unlinked}


# --- Job-level silence ------------------------------------------------------
# Silence after a conversation is not the same event as silence after a blind
# submission. A recruiter who wrote and went quiet DISENGAGED; a portal
# application nobody answered was never engaged with in the first place, and for
# an auto-submitted one that is the ordinary outcome rather than a signal.
# Collapsing the two would make 'ghosted' a synonym for "applied and waiting"
# and hand the label to the ~354 auto-submitted rows.

# A blind application needs far longer than a live conversation before silence
# means anything — ATS pipelines routinely take a month.
NO_RESPONSE_AFTER_DAYS = 30


def _relationship_index(conn: sqlite3.Connection) -> dict:
    """
    Job keys that carry evidence of a two-way relationship, with the date of the
    most recent evidence.

    Built as two set queries rather than per-job lookups: classify_job_silence()
    runs over every open row, and a per-row query would be ~1000 round trips.
    """
    index: dict[tuple, str] = {}

    def note(key: tuple, when: str, kind: str, out: dict) -> None:
        prev = out.get(key)
        if prev is None or (when or "") > prev[0]:
            out[key] = ((when or ""), kind)

    staged: dict[tuple, tuple] = {}
    for r in conn.execute(
        "SELECT company, date_added, position_title, link, occurred_date FROM interviews"
    ):
        note((r["company"], r["date_added"], r["position_title"], r["link"]),
             r["occurred_date"], "interview", staged)

    for r in conn.execute(
        "SELECT rj.company, rj.date_added, rj.position_title, rj.link, "
        "       MAX(rm.occurred_date) AS occurred_date "
        "FROM recruiter_jobs rj "
        "JOIN recruiter_messages rm ON rm.recruiter_id = rj.recruiter_id "
        "GROUP BY rj.company, rj.date_added, rj.position_title, rj.link"
    ):
        note((r["company"], r["date_added"], r["position_title"], r["link"]),
             r["occurred_date"], "recruiter_message", staged)

    index.update(staged)
    return index


def _idle_days(since: str) -> Optional[int]:
    d = _parse_date(since)
    return None if d is None else (date.today() - d).days


def classify_job_silence() -> list[dict]:
    """
    Labels every OPEN job 'ghosted', 'no_response' or 'waiting'.

    Rows with neither a date_applied nor a relationship signal are omitted
    entirely rather than labelled: a `Tracking` row is not awaiting a reply, and
    calling it silent would count a decision nobody ever made. That is the rule
    funnel_stats() already applies to unmeasured stages — an unknown must not be
    rendered as a zero.

    Derived, never stored. A stored verdict would go stale the moment a reply
    arrived, and nothing in the write path would clear it.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        rel = _relationship_index(conn)
    finally:
        conn.close()

    out = []
    for job in _stats_jobs():
        status = (job.get("status") or "").strip().lower()
        if status in TERMINAL_FAIL_STATUSES or status in TERMINAL_WIN_STATUSES:
            continue

        key = (job.get("company"), job.get("date_added"),
               job.get("position_title") or "", job.get("link") or "")
        applied = (job.get("date_applied") or "").strip()

        event_date, signal = rel.get(key, ("", ""))
        if not signal and status in SCREEN_STATUSES:
            # A screening status implies a human engaged even where no round was
            # logged — 8 of the 10 current screens have no `interviews` row.
            signal = "screening_status"

        if signal:
            # The clock runs from the newest relationship evidence; fall back to
            # the application, then to when the row was created.
            since = event_date or applied or (job.get("date_added") or "")
            idle = _idle_days(since)
            state = "ghosted" if idle is not None and idle >= GHOSTED_AFTER_DAYS else "waiting"
        elif applied:
            idle = _idle_days(applied)
            since = applied
            state = ("no_response" if idle is not None and idle >= NO_RESPONSE_AFTER_DAYS
                     else "waiting")
        else:
            continue  # not awaiting anything

        out.append({
            "company": job.get("company"),
            "date_added": job.get("date_added"),
            "position_title": job.get("position_title"),
            "link": job.get("link"),
            "status": job.get("status"),
            "state": state,
            # Which test fired, so a classification can be audited rather than
            # taken on faith.
            "signal": signal or "application",
            "since": since,
            "idle_days": idle,
            "auto_applied": any(m in (job.get("notes") or "").lower() for m in _AUTO_MARKERS),
        })

    out.sort(key=lambda r: -(r["idle_days"] or 0))
    return out


def job_silence_stats() -> dict:
    """
    Counts per state, split hand vs auto the way funnel_stats() splits sources.

    Auto-submitted rows are included: an unanswered application is unanswered
    whoever clicked submit. They are counted separately because they behave
    differently — no contact by construction, and no follow-up action available.
    """
    rows = classify_job_silence()
    out = {"ghosted": {"hand": 0, "auto": 0}, "no_response": {"hand": 0, "auto": 0},
           "waiting": {"hand": 0, "auto": 0}}
    for r in rows:
        out[r["state"]]["auto" if r["auto_applied"] else "hand"] += 1
    for state in out:
        out[state]["total"] = out[state]["hand"] + out[state]["auto"]
    return {
        "counts": out,
        "ghosted_rows": [r for r in rows if r["state"] == "ghosted"],
        "no_response_rows": [r for r in rows if r["state"] == "no_response"],
        "ghosted_after_days": GHOSTED_AFTER_DAYS,
        "no_response_after_days": NO_RESPONSE_AFTER_DAYS,
    }


# How far ahead the Insights card shows in its table. A horizon for attention,
# not a filter: rounds past it are counted on an overflow line rather than
# dropped, because a booking nobody can see is the same problem as a booking
# nobody made. This window partitions future rounds only -- a booking whose date
# has gone by never enters the table, and is counted on its own line instead.
UPCOMING_WINDOW_DAYS = 14


def upcoming_interviews(include_past: bool = False) -> list[dict]:
    """
    get_upcoming_interviews() rows with `days_away` and `overdue` added, which is
    what every display surface wants and what the Insights card is built on.

    This is what "in flight" means in ordinary speech, and until now it had
    nowhere to live: two real calls were sitting in free-text `notes` where no
    query could see them.

    A scheduled round already in the past with no `occurred_date` is either
    forgotten paperwork or a call that never happened. It is not shown by
    default -- it is not upcoming -- but `include_past=True` still retrieves it,
    marked `overdue`, so the log can be reconciled against reality.
    """
    today = date.today()
    out = []
    for row in get_upcoming_interviews(include_past=include_past):
        when = _parse_date(row["scheduled_date"])
        row["days_away"] = (when - today).days if when else None
        row["overdue"] = row["days_away"] is not None and row["days_away"] < 0
        out.append(row)
    return out


# Statuses that assert a round happened or is booked. Rejected is deliberately
# out: its process is over, so a missing round there is history to reconstruct
# rather than a booking at risk of being forgotten, and mixing the two would
# make the count on the Insights card un-actionable.
INTERVIEWING_STATUSES = [
    "Phone Screen", "Technical", "System Design", "Behavioral", "Offer", "Accepted",
]


def jobs_missing_interview_rows() -> list[dict]:
    """
    Jobs whose status claims an interview, with no round in `interviews`.

    Status and the interview log are written by different paths and nothing has
    ever reconciled them, so they drift silently -- which is how a confirmed
    Morgan Stanley booking sat in free-text `notes` while "Coming up" showed
    every other screen. The drift is only visible if something counts it.

    A LEFT JOIN on the full composite key, so a round recorded against a
    slightly different key still reads as missing. That is the intent: such a
    round is unreachable from the table too.

    This does NOT catch the other drift: a job whose booking has a past date and
    no outcome recorded has an interview row, so `i.id IS NULL` excludes it. That
    set is counted separately on the card from the `overdue` rows of
    upcoming_interviews(include_past=True). The two numbers do not overlap.
    """
    conn = _connect()
    if not conn:
        return []
    try:
        marks = ", ".join("?" for _ in INTERVIEWING_STATUSES)
        rows = conn.execute(
            "SELECT j.company, j.date_added, j.position_title, j.link, j.status "
            "FROM jobs j LEFT JOIN interviews i "
            "  ON i.company = j.company AND i.date_added = j.date_added "
            " AND i.position_title = j.position_title AND i.link = j.link "
            f"WHERE j.status IN ({marks}) AND COALESCE(j.archived, 0) = 0 "
            "  AND i.id IS NULL "
            "ORDER BY j.date_added DESC",
            tuple(INTERVIEWING_STATUSES),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_interview_occurred(interview_id: int, occurred_date: str = "") -> bool:
    """
    Promotes a booked round to one that happened. Returns False if the id is
    unknown or the round already has an occurred_date.

    Defaults to the scheduled date, since the overwhelmingly common case is a
    call that ran when it was booked to run.
    """
    conn = _connect()
    if not conn:
        return False
    try:
        row = conn.execute(
            "SELECT scheduled_date, occurred_date FROM interviews WHERE id = ?",
            (interview_id,),
        ).fetchone()
        if not row or (row["occurred_date"] or "").strip():
            return False
        when = (occurred_date or "").strip() or (row["scheduled_date"] or "").strip()
        if not when:
            return False
        conn.execute("UPDATE interviews SET occurred_date = ? WHERE id = ?", (when, interview_id))
        conn.commit()
        return True
    finally:
        conn.close()
