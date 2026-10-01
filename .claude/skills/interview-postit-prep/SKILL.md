---
name: interview-postit-prep
description: Build a compact, post-it-sized recall kit ahead of a screen or behavioral interview round — a one-card competency-to-story map, a card per relevant STAR story (trigger words only, no full sentences), a company mission/values card, and an interviewer-angle card predicting their likely questions from their stated background. Use this whenever the user is prepping for an upcoming interview, screen, or recruiter call and mentions a job description, an interviewer's name or background, or wants "cheat sheet" / "post-it" / "cue card" / "quick recall" material — not just a draft answer to one question, but a full prep kit for the round.
argument-hint: "[job_url_or_pasted_jd] [interviewer_name_and_background] [round: screen|behavioral]"
---

Build a post-it-sized interview prep kit using the arguments: `$ARGUMENTS`

The output is deliberately terse. Everything here exists to be glanced at in
the ten seconds before answering, not read during the interview — so prefer
trigger words and fragments over sentences, and resist the pull to write more.
If a card needs more than ~6 lines to be useful, it has stopped being a post-it
and the user should go find that information in the prep doc, not here.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter. If that file does not exist, tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in — do not
invent a name or path.

`{star_vault_path}` matters most here: it is a folder on the user's own
machine (e.g. an Obsidian vault), not something synced into this repo. If it
is blank, or if this session cannot read that path (a remote/cloud session
has no access to the user's local filesystem — check before assuming), stop
and say so plainly: ask the user to either run this skill from a local
session where that folder is reachable, or paste the relevant STAR stories
directly into the chat so the kit can still be built. Never fabricate a story
to fill a gap in the competency map — an empty card that says "no story yet"
is more useful than a invented one.

## Step 1 — Parse the job description

Accept either a URL or pasted text in `$ARGUMENTS`.

If a URL was given:
- Greenhouse (`greenhouse.io/{company}/jobs/{id}`): fetch
  `https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}` and read
  the `content` field (strip HTML).
- Lever (`jobs.lever.co/{company}/{uuid}`): fetch
  `https://api.lever.co/v0/postings/{company}/{uuid}` and read
  `descriptionPlain`.
- Anything else (including LinkedIn): try `WebFetch`; if that fails, ask the
  user to paste the description instead.

From the JD, pull out:
- **Company name** and **role title**.
- **Core competencies being screened for** — read these from the JD's actual
  structure (a "must haves" / "what you'll be doing" / "baseline expectations"
  section is usually explicit about this), not from generic assumptions about
  the role title. A backend/AI-agent JD and a frontend JD should produce
  different competency lists even if both say "fast-paced startup."
- **Traits the JD explicitly wants to avoid** — these are worth noting because
  they tell you what *not* to emphasize, which is just as useful as knowing
  what to emphasize.

## Step 2 — Research the company

Use `WebSearch` / `WebFetch` on the company's site and recent coverage to find:

- **Stated mission or "what we do" framing** — ideally in the company's own
  words (an About page, a founder blog post, a funding announcement quote).
- **Values or operating principles**, if the company states any explicitly.
  Not every company publishes these — if you can't find them stated anywhere,
  say that rather than inferring values from the product description.
- **One or two pieces of context worth knowing cold**: funding stage, notable
  customers, what they just shipped, team size — whatever a candidate would
  look unprepared for not knowing.

Keep this to what fits on a card. This step is about finding material, not
writing the card yet.

## Step 3 — Read the interviewer's angle

The user will give you the interviewer's name and whatever they know about
their background (a role, a prior company, an industry, something a recruiter
mentioned). This is almost never a LinkedIn URL you can fetch — treat it as
context the user already has, not a research target.

From that background, infer what this *specific* person is likely to probe,
distinct from what the JD already screens for. The pattern to look for: people
tend to ask about the gap between their own background and the environment
the candidate is coming from. A few concrete examples of the shape this takes:

- An interviewer from a regulated industry (pharma, healthcare, finance
  compliance) talking to a candidate from a less formally regulated company
  will often probe process rigor — change control, validation, documentation
  standards, audit trails.
- An interviewer who is an early engineer at the company will often probe
  ambiguity tolerance and ownership — can you operate without a fully formed
  spec.
- An interviewer in a GTM or customer-facing role will often probe how you
  communicate tradeoffs to non-engineers.

Don't force a question onto a background that doesn't suggest one — if the
background given is too thin to infer anything (just a first name, say),
produce the company and story cards and tell the user you need more to build
the interviewer card, rather than guessing generically.

## Step 4 — Map competencies to STAR stories

Using the competencies from Step 1 and the stories read from
`{star_vault_path}` (or pasted by the user, per Step 0), match each
competency to the strongest available story. A few things to watch for:

- **Not every competency needs a dedicated story** — reuse one story across
  multiple competencies if it genuinely demonstrates both; a thin forced match
  is worse than an honest gap.
- **Flag real gaps.** If no story covers a competency the JD clearly cares
  about, say so on the router card (Step 5) instead of silently omitting it —
  that's exactly the kind of thing worth knowing before the interview, not
  during it.
- Pull from the story's actual content for the Tier 1 card (Step 5) — the
  one-line Situation/Task, the action beats, and the Result/number all need
  to come from what the story actually says, not be invented to sound good.

## Step 5 — Produce the cards

Build these five card types. Each one is a recall trigger, not a script —
fragments and nouns/verbs, never full sentences (that's what the full prep
doc or earlier drafted answers are for).

**1. Router card (always exactly one)**
Competency → story title, one line each. This is the card the user looks at
first when a question lands, to know which story to pull.

**2. Story cards (one per story used in the router)**
```
[Story name]
Trigger words: word · word · word
S/T: one line
Beats: verb → verb → verb
Result: the number or outcome
```

**3. Company card (one)**
```
[Company] — [role]
Mission: a few words, their own language if found
Values: short list, or "not publicly stated" if none were found
Why I'd fit: one line
```

**4. Interviewer-angle card (one, only if Step 3 produced real signal)**
```
[Interviewer name] — likely angle: [one phrase, e.g. "process rigor"]
Q1 guess → anchor term
Q2 guess → anchor term
```
The "anchor term" is the single word or short phrase that should unlock the
fuller answer in the user's memory (e.g. "SOP," "downstream impact," "rollback
plan") — not the answer itself.

**5. JD-gap card (only if Step 4 found real gaps — omit entirely otherwise)**
A short list of competencies with no matching story, so the user knows where
they're exposed going in rather than finding out live.

## Step 6 — Output both formats

**Print layout**: write an HTML file sized for actual cutting — each card in
its own bordered box, roughly post-it or index-card dimensions (a simple CSS
grid of fixed-size boxes, print-friendly — no need for anything fancier than
clean borders and readable type at that size). Save it to the scratchpad
directory and tell the user where it is so they can open and print it.

**Screen version**: also output the same cards as plain markdown directly in
the chat, in the compact format from Step 5, so the user has something to
glance at immediately without opening a file.

Keep both versions in sync — the markdown is not a summary of the HTML, it's
the same content in a different shell.
