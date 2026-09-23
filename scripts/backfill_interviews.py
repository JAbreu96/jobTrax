"""
Move interview bookings out of free-text notes and into the interviews table.

Ten jobs sit at Phone Screen or later; three have a round recorded. The other
seven carry the booking as prose -- Morgan Stanley's `notes` say "INTERVIEW
CONFIRMED, Wednesday, September 2, 2026, 11:45 AM to 12:15 PM EDT" while the
"Coming up" card on Insights, which reads the interviews table, shows every
screen except that one.

Note the card is future-only: a row this writes whose date has already gone by
is a held round and belongs to the outcome table rather than the "Coming up"
card. Nothing has to promote it -- the date alone decides which it is.

The cause is upstream and fixed separately: nothing was allowed to write
`interviews.scheduled_date`. Triage was told to record a round "only with
occurred_date -- never a scheduled-but-not-yet-held invite", the GUI returned a
hard 400 without one, and the MCP server has no interview writer at all. So a
confirmed booking had nowhere to go but prose. This script recovers what that
rule already lost.

**It records rounds against rows that exist. It never creates a job row.**
add_interview() keys off the full composite (company, date_added,
position_title, link) and does NOT verify a job matches, so a round written
against a near-miss key counts in the funnel while being unreachable from the
table. Every key here comes from a row read back out of the database, never
assembled. `job rows: N -> N` is the guard, and it is printed on every run.

A row whose text names no time is REPORTED AND SKIPPED, never guessed. Highlight
AI and Triangle Manufacturing are both "awaiting Joel's reply" with no time
agreed -- those are not interviews yet, and inventing a date for them would put
a fiction on the card this exists to make honest.

Usage:
    python scripts/backfill_interviews.py            # dry run (default)
    python scripts/backfill_interviews.py --write
"""

import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import jobs_db  # noqa: E402

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "backfill")

# A date alone is not a booking. Job rows are full of dates that are not rounds
# -- "Role posted", "Booked 2026-08-20", "Created by inbox-triage" -- so a
# candidate has to clear two bars before it counts.
#
# The first is adjacency. In every real booking here the date and the clock time
# are one phrase: "2026-08-20, 10:30-10:45 AM ET", "September 2, 2026 — 11:45 AM
# to 12:15 PM EDT". In every false positive something sits between them:
# "InMail 2026-08-18, call at 10:30 AM ET" names the day an InMail arrived and,
# separately, a time on a different day. Requiring the gap to be punctuation
# only is what separates the two, and it is why a date with no time on its line
# is never a candidate at all.
_GAP = re.compile(r"^[\s,\-–—]{0,3}$")

# The second bar: the line, or the one above it, has to be talking about a
# round. Morgan Stanley needs the line above -- "✅ INTERVIEW CONFIRMED" sits on
# its own, with the date beneath it.
_BOOKING_WORDS = re.compile(
    r"\b(interview|phone\s*screen|screening|screen|intro\s*chat|call|meeting|"
    r"onsite|booked|confirmed|scheduled)\b", re.I)

# ...and these say a time was requested, not agreed.
_PENDING_WORDS = re.compile(
    r"\b(availability|asking for|requested|awaiting|pick a time|"
    r"let us know|when are you|scheduling link)\b", re.I)

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_MONTH_RE = "|".join(m[:3] for m in _MONTHS)

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG = re.compile(rf"\b({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:[-–—]\s*\d{1,2}(?::\d{2})?)?\s*(a\.?m\.?|p\.?m\.?)\b", re.I)


def _norm_time(match) -> str:
    """A matched time as HH:MM, 24-hour."""
    hour = int(match.group(1)) % 12
    if match.group(3).lower().startswith("p"):
        hour += 12
    return f"{hour:02d}:{int(match.group(2) or 0):02d}"


def _dates_in(line: str) -> list:
    """Every date on one line, ISO and long form, as (date, end_offset)."""
    out = []
    for m in _ISO.finditer(line):
        try:
            out.append((datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.end()))
        except ValueError:
            pass
    for m in _LONG.finditer(line):
        month = next((i + 1 for i, name in enumerate(_MONTHS)
                      if name.startswith(m.group(1).lower()[:3])), None)
        if month:
            try:
                out.append((datetime.date(int(m.group(3)), month, int(m.group(2))), m.end()))
            except ValueError:
                pass
    return out


def extract_rounds(row: dict) -> list:
    """
    Booking candidates in one job row's free text, as {date, time, evidence}.

    Reads `notes` and `contacts` line by line, keeping the previous line as
    context. GTE is the shape that proves the (date, time) key: two competing
    agency recruiters each booked a call on 2026-08-20, at 10:30 and 11:00, and
    both are real rounds -- deduping on the date alone would drop one.
    """
    seen, out = set(), []
    for field in ("notes", "contacts"):
        prev = ""
        for raw in (row.get(field) or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            context = line + " " + prev
            if not _BOOKING_WORDS.search(context) or _PENDING_WORDS.search(line):
                prev = line
                continue
            for when, date_end in _dates_in(line):
                t = _TIME.search(line, date_end)
                # Adjacency: only punctuation may separate the date from its time.
                if not t or not _GAP.match(line[date_end:t.start()]):
                    continue
                key = (when, _norm_time(t))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"date": when, "time": _norm_time(t),
                            "evidence": line[:110]})
            prev = line
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="apply. Without it the script only prints what it found.")
    args = ap.parse_args()

    today = datetime.date.today()
    drifted = jobs_db.jobs_missing_interview_rows()
    jobs_before = len(jobs_db.get_all_jobs(include_archived=True))

    by_key = {(j["company"], j["date_added"], j["position_title"], j["link"]): j
              for j in jobs_db.get_all_jobs(include_archived=True)}

    planned, skipped = [], []
    for d in drifted:
        key = (d["company"], d["date_added"], d["position_title"], d["link"])
        row = by_key.get(key)
        if row is None:                      # cannot happen; a missed key is a bug
            skipped.append((d["company"], "job row not found by its own key"))
            continue
        rounds = extract_rounds(row)
        if not rounds:
            skipped.append((d["company"], "no date and time in notes/contacts"))
            continue
        for r in rounds:
            planned.append({"key": key, "company": d["company"], **r})

    log = [f"backfill_interviews {datetime.datetime.now().isoformat(timespec='seconds')}",
           f"drifted rows: {len(drifted)}"]

    print(f"{len(drifted)} jobs at an interview status with no round recorded.")
    print()
    print(f"{'COMPANY':<26} {'DATE':<12} {'TIME':<6} {'AS':<10} EVIDENCE")
    print("-" * 118)
    for p in planned:
        field = "occurred" if p["date"] <= today else "scheduled"
        line = (f"{p['company'][:25]:<26} {p['date'].isoformat():<12} "
                f"{p['time'] or '—':<6} {field:<10} {p['evidence']}")
        print(line)
        log.append(line)
    if skipped:
        print()
        print("Skipped — no booking to recover, left for a human:")
        for company, why in skipped:
            print(f"  {company:<26} {why}")
            log.append(f"skip {company}: {why}")

    written = 0
    if args.write:
        scope = jobs_db.shared_connection()
        scope.__enter__()
        try:
            for p in planned:
                company, date_added, title, link = p["key"]
                note = f"Recovered from row notes by backfill_interviews."
                if p["time"]:
                    note = f"{p['time']}. " + note
                jobs_db.add_interview(
                    company=company, date_added=date_added, position_title=title,
                    link=link, interview_type="phone_screen",
                    scheduled_date=p["date"].isoformat(),
                    notes=note)
                written += 1
        finally:
            scope.__exit__(None, None, None)

    print()
    print(f"rounds found: {len(planned)} | rows skipped: {len(skipped)} | written: {written}")

    if args.write:
        jobs_after = len(jobs_db.get_all_jobs(include_archived=True))
        # The check that matters. This script records rounds; if the job count
        # moved, something inserted a job, which it must never do.
        print(f"job rows: {jobs_before} -> {jobs_after} "
              f"({'unchanged, as expected' if jobs_after == jobs_before else 'CHANGED — investigate'})")
        left = jobs_db.jobs_missing_interview_rows()
        print(f"still drifted: {len(left)}"
              + (" — " + ", ".join(r["company"] for r in left) if left else ""))
        log.append(f"job rows {jobs_before} -> {jobs_after}; written {written}")
    else:
        print("Dry run — nothing written. Re-run with --write to apply.")

    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "interviews_%s.log"
                        % datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S"))
    open(path, "w").write("\n".join(log) + "\n")
    print(f"Log: {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
