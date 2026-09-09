#!/usr/bin/env python3
"""Generate NYS DOL WS-5 Work Search Record PDFs, one per benefit week.

Data sources (evidence-backed only, nothing invented):
  1. Gmail application-confirmation emails  -> exact date + employer (primary)
  2. data/jobs.db job tracker               -> position title + URL + status
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (BooleanObject, NameObject, NumberObject,
                           TextStringObject)
from reportlab.pdfbase.pdfmetrics import stringWidth

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
from src import config  # noqa: E402
DB = os.path.join(REPO, "data", "jobs.db")
TEMPLATE = os.path.join(HERE, "WS5.pdf")
EVIDENCE = os.path.join(HERE, "evidence.json")
OUTDIR = config.WS5_OUTDIR

# One uniform font size for every filled cell. Lower this for smaller text;
# individual cells only drop below it when a value genuinely cannot fit.
FONT_PT = 8.0

# First benefit week on record; the backfill never walks back past it. Set
# ws5_record_start in config/profile.md. Unset means no week is old enough to
# fill, which is the right answer for anyone not claiming New York benefits.
RECORD_START = config.WS5_RECORD_START or date.max

FIRST_NAME = config.OWNER_FIRST_NAME
LAST_NAME = config.OWNER_LAST_NAME

def load_evidence():
    """Gmail-confirmed applications, from evidence.json (append-only record).

    Returns (gmail, overrides) in the shapes the rest of this script expects.
    Only genuine applications belong in that file - rejection and status-update
    emails are employer replies, not work-search activities you performed.
    """
    with open(EVIDENCE) as fh:
        data = json.load(fh)
    gmail, overrides = [], {}
    for rec in data.get("applications", []):
        key = (rec["date"], rec["company"])
        gmail.append(key)
        extra = {k: rec[k] for k in
                 ("position", "person", "method", "contact", "result")
                 if rec.get(k)}
        if extra:
            overrides[key] = extra
    return gmail, overrides


RESULT_BY_STATUS = {
    "rejected": "Not hired",
    "interview": "Interview",
    "phone screen": "Interview - phone screen",
    "technical": "Interview - technical",
    "behavioral": "Interview - behavioral",
    "system design": "Interview - system design",
    "offer": "Offer received",
}
DEFAULT_RESULT = "Waiting for response"


def week_ending(d: date) -> date:
    """Sunday on or after d (NYS benefit week ends Sunday)."""
    return d + timedelta(days=(6 - d.weekday()) % 7)


def last_completed_week(today: date = None) -> date:
    """Most recent Sunday on or before today - the last week that has closed."""
    today = today or date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


def missing_weeks(today: date = None):
    """Week-ending Sundays that have closed but have no form on disk yet.

    Driven by the calendar rather than by evidence.json: a brand-new week has
    no evidence recorded yet but still needs a form, so it must show up here.
    """
    end = last_completed_week(today)
    out, wk = [], RECORD_START
    while wk <= end:
        if not os.path.exists(
                os.path.join(OUTDIR, f"WS5_week_ending_{wk.isoformat()}.pdf")):
            out.append(wk)
        wk += timedelta(days=7)
    return out


def load_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT company, date_added, position_title, link, status, outreach_date "
        "FROM jobs WHERE date_added <> ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


# --- text fitting -----------------------------------------------------------
# pypdf does NOT implement auto-sizing: a "0 Tf" (auto) DA is silently rendered
# at a hardcoded 12pt, which overflows the short table cells and gets clipped by
# the widget's clip rect. So compute a concrete size that genuinely fits.

LEADING = 1.156      # matches pypdf's line spacing
PAD_X, PAD_Y = 4.0, 2.0


def _wrap(text, size, max_w):
    """Greedy word wrap; returns lines, or None if a single token cannot fit."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if stringWidth(trial, "Helvetica", size) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        if stringWidth(word, "Helvetica", size) > max_w:
            return None          # unbreakable token too wide at this size
        cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_size(text, width, height, lo=4.0, hi=11.0):
    """Largest size in [lo, hi] whose wrapped text fits the box."""
    text = (text or "").strip()
    if not text:
        return hi
    max_w, max_h = width - PAD_X, height - PAD_Y
    size = hi
    while size >= lo:
        lines = _wrap(text, size, max_w)
        if lines and len(lines) * size * LEADING <= max_h:
            return round(size, 1)
        size -= 0.5
    return lo


def fit_single(text, width, height, cap=10.5):
    """Size for a NON-wrapping field: fit width and height, but never scale up
    past `cap` (pypdf's single-line auto mode would blow "05" up to 24pt)."""
    text = (text or "").strip()
    if not text:
        return cap
    per_pt = stringWidth(text, "Helvetica", 1.0) or 1.0
    return round(max(4.0, min(cap,
                              (height - PAD_Y) / LEADING,
                              (width - PAD_X) / per_pt)), 1)


def fit_wrapped(text, width, height, start=8.0):
    """Wrap `text` to the box at `start` pt, shrinking only if it truly cannot
    fit. Returns (size, text_with_newlines)."""
    text = (text or "").strip()
    if not text:
        return start, text
    size = start
    while size >= 4.0:
        lines = _wrap(text, size, width - PAD_X)
        if lines and len(lines) * size * LEADING <= height - PAD_Y:
            return round(size, 1), "\n".join(lines)
        size -= 0.5
    lines = _wrap(text, 4.0, width - PAD_X) or [text]
    return 4.0, "\n".join(lines)


def short_contact(value: str) -> str:
    """Fit the contact column. A full job URL is one unbreakable token and gets
    clipped, so reduce it to its host (still accurate for 'website/URL').
    Email addresses are short enough to keep verbatim."""
    v = (value or "").strip()
    if not v:
        return v
    if "@" in v:
        # Long ATS addresses clip too; fall back to the bare domain.
        return v.split("@", 1)[1] if len(v) > 24 else v
    host = v.split("//", 1)[-1].split("/", 1)[0]
    return host or v


def main():
    ap = argparse.ArgumentParser(description="Generate NYS WS-5 work search records.")
    ap.add_argument("--week", metavar="YYYY-MM-DD",
                    help="Week-ending Sunday to generate. Default: the most "
                         "recently completed week.")
    ap.add_argument("--all", action="store_true",
                    help="Regenerate every week present in the evidence file.")
    ap.add_argument("--list-missing", action="store_true",
                    help="Print the closed weeks that still have no form, one "
                         "per line, and exit. Prints nothing when up to date.")
    args = ap.parse_args()

    if args.list_missing:
        for wk in missing_weeks():
            print(wk.isoformat())
        return 0

    global GMAIL, OVERRIDES
    GMAIL, OVERRIDES = load_evidence()

    if args.all:
        only = None
    elif args.week:
        only = date.fromisoformat(args.week)
        if only.weekday() != 6:
            ap.error(f"--week must be a Sunday; {only} is a {only:%A}.")
    else:
        # Most recent Sunday on or before today. Run on Sunday evening this is
        # the week that just closed; run midweek it is last week's form.
        today = date.today()
        only = today - timedelta(days=(today.weekday() + 1) % 7)

    db_rows = load_db()

    # company -> best DB record (for position title / link enrichment)
    by_company = {}
    for r in db_rows:
        k = norm(r["company"])
        if k and (k not in by_company or (r["position_title"] and not by_company[k]["position_title"])):
            by_company[k] = r

    entries = defaultdict(list)   # week_ending -> list of row dicts
    seen = set()

    # --- primary: Gmail-confirmed applications -----------------------------
    for ds, company in GMAIL:
        d = date.fromisoformat(ds)
        wk = week_ending(d)
        db = by_company.get(norm(company), {})
        status = (db.get("status") or "").strip().lower()
        key = (wk, norm(company))
        if key in seen:
            continue
        seen.add(key)
        ov = OVERRIDES.get((ds, company), {})
        entries[wk].append({
            "date": d,
            "company": company,
            "position": ov.get("position") or (db.get("position_title") or "").strip(),
            "link": ov.get("contact") or (db.get("link") or "").strip(),
            "person": ov.get("person", ""),
            "method": ov.get("method", "Website"),
            "result": ov.get("result") or RESULT_BY_STATUS.get(status, DEFAULT_RESULT),
            "src": "gmail",
        })

    # --- supplement: tracker rows, to top weeks up toward 5 ----------------
    # Only rows with affirmative evidence that contact actually happened.
    # A blank/"Tracking"/"Not Applied" status means the job was merely sourced,
    # which is NOT an employer contact and must not appear on the form.
    CONTACTED = ("applied", "outreach", "rejected", "interview",
                 "offer", "phone screen", "technical", "behavioral")
    # Placeholder employers cannot be verified by DOL - exclude them.
    UNVERIFIABLE = ("unknown", "stealth", "anonymous", "confidential")

    for r in db_rows:
        try:
            d = date.fromisoformat(r["date_added"])
        except ValueError:
            continue
        status_raw = (r["status"] or "").strip().lower()
        if not any(t in status_raw for t in CONTACTED):
            continue
        if any(t in (r["company"] or "").lower() for t in UNVERIFIABLE):
            continue
        wk = week_ending(d)
        key = (wk, norm(r["company"]))
        if key in seen:
            continue
        if len(entries[wk]) >= 5:
            continue
        seen.add(key)
        status = (r["status"] or "").strip().lower()
        outreached = "outreach" in status
        entries[wk].append({
            "date": d,
            "company": r["company"],
            "position": (r["position_title"] or "").strip(),
            "link": (r["link"] or "").strip(),
            "person": "",
            "method": "Email" if outreached else "Website",
            "result": RESULT_BY_STATUS.get(status, DEFAULT_RESULT),
            "src": "tracker",
        })

    # --- emit one PDF per week --------------------------------------------
    os.makedirs(OUTDIR, exist_ok=True)
    # keep the ID stamper alongside the forms it operates on
    helper = os.path.join(HERE, "fill_my_id.py")
    if os.path.exists(helper):
        import shutil
        shutil.copy(helper, os.path.join(OUTDIR, "fill_my_id.py"))
    weeks = sorted(entries)
    if only is not None:
        weeks = [w for w in weeks if w == only]
        if not weeks:
            print(f"No evidence for week ending {only}. "
                  f"Nothing generated.", file=sys.stderr)
            return 1
    summary = []

    for wk in weeks:
        rows = sorted(entries[wk], key=lambda e: (e["date"], e["company"]))[:5]
        fields = {
            "Contact_FirstName": FIRST_NAME,
            "Contact_LastName": LAST_NAME,
            "CurrentDate_CurrentMM": f"{wk.month:02d}",
            "CurrentDate_CurrentDD": f"{wk.day:02d}",
            # Two-digit year: MM/DD/YY.
            "CurrentDate_CurrentYY": f"{wk.year % 100:02d}",
        }
        for i, e in enumerate(rows, start=1):
            p = f"Employment_JobSearchRecord_Row{i}"
            fields[f"{p}BusinessName"] = e["company"]
            fields[f"{p}PositionApplied"] = e["position"]
            fields[f"{p}MethodOfContact"] = e["method"]
            fields[f"{p}ContactInformation"] = short_contact(e["link"])
            fields[f"{p}PersonContactedNameTitle"] = e.get("person", "")
            fields[f"{p}Result"] = e["result"]
            fields[f"Grievance_DateList_Row{i}DateMM"] = f"{e['date'].month:02d}"
            fields[f"Grievance_DateList_Row{i}DateDD"] = f"{e['date'].day:02d}"
            fields[f"Grievance_DateList_Row{i}DateYY"] = f"{e['date'].year % 100:02d}"

        reader = PdfReader(TEMPLATE)
        writer = PdfWriter(clone_from=reader)
        # We generate correctly-sized appearance streams ourselves, so tell
        # viewers to use them rather than re-rendering with their own guesses
        # (which is what made the same file look different in each viewer).
        writer.set_need_appearances_writer(False)

        # The narrow table columns clip long values (job titles, URLs). Make the
        # wide-content fields multiline with auto-sizing text so they wrap and
        # shrink to fit instead of being cut off mid-word.
        # ContactInformation is deliberately NOT multiline: a hostname is one
        # unbreakable token, so word-wrapping cannot help it and pypdf would
        # leave it at 12pt and clip. Single-line auto-size scales it to fit.
        WRAP = ("PositionApplied", "BusinessName",
                "Result", "PersonContactedNameTitle")
        MULTILINE = 1 << 12
        for page in writer.pages:
            for annot in (page.get("/Annots") or []):
                obj = annot.get_object()
                name = obj.get("/T")
                if name is None and obj.get("/Parent") is not None:
                    name = obj["/Parent"].get("/T")
                if not name:
                    continue
                name = str(name)
                rect = [float(x) for x in obj.get("/Rect", [0, 0, 0, 0])]
                w, h = abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
                ff = int(obj.get("/Ff", 0))
                value = fields.get(name, "")

                if any(t in name for t in WRAP):
                    obj[NameObject("/Ff")] = NumberObject(ff | MULTILINE)
                    # We wrap the text ourselves and write the line breaks into
                    # the value. pypdf's explicit-size branch splits on newlines
                    # (`for line in text.splitlines()`), so this keeps the one
                    # uniform font size instead of letting each field auto-size
                    # to something different.
                    size, wrapped = fit_wrapped(value, w, h, FONT_PT)
                    if wrapped != value:
                        fields[name] = wrapped
                else:
                    # The template marks every cell multiline. Clear it here so
                    # single-token values (hostnames, dates) sit on one line.
                    obj[NameObject("/Ff")] = NumberObject(ff & ~MULTILINE)
                    size = fit_single(value, w, h, cap=FONT_PT)

                obj[NameObject("/DA")] = TextStringObject(
                    f"/Helvetica {size} Tf 0 g")

        for page in writer.pages:
            # auto_regenerate=True is what makes pypdf word-wrap multiline
            # fields; we clear NeedAppearances afterwards so viewers still use
            # the streams we just generated.
            writer.update_page_form_field_values(
                page, fields, auto_regenerate=True)

        acro = writer._root_object.get("/AcroForm")
        if acro is not None:
            acro.get_object()[NameObject("/NeedAppearances")] = BooleanObject(False)

        out = os.path.join(OUTDIR, f"WS5_week_ending_{wk.isoformat()}.pdf")
        with open(out, "wb") as fh:
            writer.write(fh)

        summary.append({
            "week_ending": wk.isoformat(),
            "count": len(rows),
            "meets_minimum": len(rows) >= 3,
            "gmail_backed": sum(1 for e in rows if e["src"] == "gmail"),
            "file": os.path.basename(out),
            "employers": [e["company"] for e in rows],
        })

    with open(os.path.join(OUTDIR, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    print(f"{'week ending':<14}{'rows':>5}{'gmail':>7}  ok   employers")
    for s in summary:
        flag = "YES" if s["meets_minimum"] else "SHORT"
        print(f"{s['week_ending']:<14}{s['count']:>5}{s['gmail_backed']:>7}  {flag:<5} "
              + ", ".join(s["employers"][:4]))
    short = [s for s in summary if not s["meets_minimum"]]
    print(f"\n{len(summary)} forms written to {OUTDIR}")
    print(f"weeks below the 3-activity minimum: {len(short)}")
    for s in short:
        print(f"  SHORT: week ending {s['week_ending']} has only "
              f"{s['count']} activities (NYS requires 3).")
    return 2 if short else 0


if __name__ == "__main__":
    sys.exit(main())
