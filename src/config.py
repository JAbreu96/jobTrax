"""Every personal value in this repo resolves here.

These used to be literals scattered through the tree: a spreadsheet ID copied
into five files, two Gmail addresses in `triage_rules`, a name in the WS-5
builder, a resume Doc ID in four skills. A fork got a working program pointed at
someone else's account.

Precedence, highest first:

  1. an environment variable (`AGENTS_*`, or a legacy name where one existed)
  2. the YAML front matter of `config/profile.md`
  3. a neutral default

Identity lives in `config/profile.md` rather than `.env` because
`.claude/skills/*/SKILL.md` is Markdown and cannot read environment variables.
The skills read that file directly; this module parses the same front matter, so
there is one source of truth instead of two that drift. `.env` keeps what a
skill never needs to see: credential paths, cloud endpoints, secrets.

Env still wins, so a scheduled or CI run can be pointed at a scratch sheet
without editing a tracked file, and so tests can pin a fixture profile.

**This module must not raise at import.** `tests/test_sync_archived.py` imports
`scripts.sync_jobs_to_sqlite` at module scope and `tests/test_job_agent.py`
imports `src.job_agent`, both of which import this; and a fresh clone has no
`config/profile.md` at all. An import-time raise would turn "you have not
configured this yet" into "the test suite does not collect". Call `require()` at
the point of use instead -- it names the file to edit.
"""

import os
import re
from datetime import date

from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# By absolute path, not find_dotenv(): the MCP server and the cron scripts do
# not run from the repo root, and a cwd-relative search silently finds nothing
# and falls back to a default -- reintroducing the split without an error.
#
# override=False, so a caller that has already exported a variable (or unset it
# deliberately, as tests/conftest.py does) still wins. Both properties are
# load-bearing for the local-vs-cloud database check; see CLAUDE.md.
load_dotenv(os.path.join(REPO_ROOT, ".env"), override=False)


class ConfigError(RuntimeError):
    """A required value is unset, named so the fix is obvious."""


def profile_path() -> str:
    return os.environ.get("AGENTS_PROFILE") or os.path.join(
        REPO_ROOT, "config", "profile.md"
    )


# ------------------------------------------------------------ front matter

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def _parse_front_matter(text: str) -> dict:
    """Flat `key: value` pairs plus `- item` block lists.

    Hand-rolled rather than PyYAML: `requirements.txt` is deliberately curated
    (see its notes on capping `mcp` and pinning `libsql`), and the schema here is
    scalars and one list. A line this cannot parse is skipped, never raised on --
    a malformed profile must not stop the module from importing.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}

    data: dict = {}
    key = None
    for raw in match.group(1).splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue

        if line.lstrip().startswith("- ") and key is not None:
            item = _unquote(line.lstrip()[2:].strip())
            if item:
                data.setdefault(key, [])
                if isinstance(data[key], list):
                    data[key].append(item)
            continue

        name, sep, value = line.partition(":")
        if not sep:
            continue
        key = name.strip()
        value = _unquote(value.strip())
        data[key] = value if value else ""
    return data


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _read_profile() -> dict:
    try:
        with open(profile_path(), encoding="utf-8") as handle:
            return _parse_front_matter(handle.read())
    except OSError:
        # No profile yet. Everything falls through to defaults, and require()
        # is what eventually tells the user to create it.
        return {}


# ---------------------------------------------------------------- resolve

_PROFILE: dict = {}


def _value(env_name: str, key: str, default: str = "") -> str:
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env
    raw = _PROFILE.get(key, "")
    return raw.strip() if isinstance(raw, str) else default or ""


def _load() -> None:
    global _PROFILE
    global OWNER_NAME, OWNER_FIRST_NAME, OWNER_LAST_NAME, OWNER_EMAILS
    global NOTIFY_EMAIL, OUTREACH_EMAIL, LINKEDIN_FORWARD_EMAIL, LINKEDIN_URL
    global SPREADSHEET_ID, SPREADSHEET_URL, SHEET_WORKSHEET
    global RESUME_DOC_ID, RESUME_FOLDER_ID
    global WS5_RECORD_START, WS5_OUTDIR

    _PROFILE = _read_profile()

    OWNER_NAME = _value("AGENTS_OWNER_NAME", "owner_name")
    first, _, last = OWNER_NAME.partition(" ")
    OWNER_FIRST_NAME = _value("", "owner_first_name") or first
    OWNER_LAST_NAME = _value("", "owner_last_name") or last.strip()

    NOTIFY_EMAIL = _value("AGENTS_NOTIFY_EMAIL", "notify_email")
    OUTREACH_EMAIL = _value("AGENTS_OUTREACH_EMAIL", "outreach_email")

    # Every address that is the owner. Defaults to the two above rather than
    # nothing: forgetting one here makes triage re-surface threads already
    # answered, which reads as a triage bug rather than a config gap.
    raw_owned = os.environ.get("AGENTS_OWNER_EMAILS", "").strip()
    if raw_owned:
        owned = [part.strip() for part in raw_owned.split(",")]
    else:
        owned = _PROFILE.get("owner_emails") or []
        if isinstance(owned, str):
            owned = [owned]
    owned = owned or [NOTIFY_EMAIL, OUTREACH_EMAIL]
    OWNER_EMAILS = tuple(dict.fromkeys(a.strip().casefold() for a in owned if a.strip()))

    LINKEDIN_FORWARD_EMAIL = _value("", "linkedin_forward_email")
    LINKEDIN_URL = _value("", "linkedin_url")

    # JOB_TRACKER_SPREADSHEET is the legacy name, already honoured by the
    # --spreadsheet defaults in job_agent and job_digest. Kept so an existing
    # .env keeps working unchanged.
    raw_sheet = (
        os.environ.get("AGENTS_SPREADSHEET_ID", "").strip()
        or os.environ.get("JOB_TRACKER_SPREADSHEET", "").strip()
        or str(_PROFILE.get("spreadsheet_id", "")).strip()
    )
    # A full edit URL is what the browser gives you, so pasting one in was the
    # obvious mistake to make. Accept it.
    url_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw_sheet)
    SPREADSHEET_ID = url_match.group(1) if url_match else raw_sheet
    SPREADSHEET_URL = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
        if SPREADSHEET_ID
        else ""
    )
    SHEET_WORKSHEET = _value("", "sheet_worksheet") or "Sheet1"

    RESUME_DOC_ID = _value("AGENTS_RESUME_DOC_ID", "resume_doc_id")
    RESUME_FOLDER_ID = _value("AGENTS_RESUME_FOLDER_ID", "resume_folder_id")

    WS5_RECORD_START = _parse_date(_value("WS5_RECORD_START", "ws5_record_start"))
    WS5_OUTDIR = os.path.expanduser(
        _value("", "ws5_output_dir") or "~/Desktop/WS5_work_search_records"
    )


def _parse_date(value: str):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def refresh() -> None:
    """Re-read `.env` and the profile, rebinding the module constants.

    For tests, and for anything that changes `AGENTS_PROFILE` after import.
    """
    load_dotenv(os.path.join(REPO_ROOT, ".env"), override=False)
    _load()


def require(name: str) -> str:
    """Return a configured value, or raise naming the file to edit.

    The whole point of the accessor: a forker hits one clear message here rather
    than a 404 from gspread three calls later.
    """
    value = globals().get(name, "")
    if value:
        return value
    raise ConfigError(
        f"{name} is not configured.\n"
        f"Set the matching key in {profile_path()}\n"
        f"(copy config/profile.example.md if you have not yet), "
        f"or export AGENTS_{name}."
    )


_load()
