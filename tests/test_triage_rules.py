"""
The mechanical half of the inbox-triage gate.

Every case here is drawn from mail that actually arrived in August 2026, and
most of them are errors this skill already made once: a task telling the owner
to reply to a rejection, a task for a thread they had already answered, a task
for a recruiter who owed *them* the next move.

Addresses come from the fixture profile pinned in conftest, not from whatever
`config/profile.md` is on the machine running this.
"""

from src.triage_rules import (
    Rejection,
    contains_ask,
    detect_closing_statement,
    detect_rejection,
    is_from_owner,
    normalize_subject,
    strip_html,
    strip_quoted_chain,
    unescape_title,
)

# Verbatim from thread 1a02060e9e3ab049, with the wrapped Gmail quote marker
# that a naive splitter misses.
TRIANGLE_REPLY = """Hi Liseets,

Thank you for the update. I'm looking forward to the call. Here are some
times that work well for me next week:

Wednesday, August 26: 10:00 AM - 12:00 PM or 2:00 PM - 3:30 PM ET

Best,
Test Owner

On Thu, Aug 20, 2026 at 2:13 PM Liseets Taveras <
recruiting+433606714-075c5aa6@applytojob.com> wrote:

> Hi Test Owner,
>
> Please respond to this email with a list of dates and times that you would
> be available for an initial phone interview.
>
> Best Regards,
>
> Liseets
"""


# ---------------------------------------------------------------- subjects

def test_prefix_chain_collapses_to_one_key():
    assert normalize_subject("Re: FW: Re: Intro Chat") == "intro chat"
    assert normalize_subject("intro  chat") == "intro chat"


def test_bracketed_and_foreign_prefixes_are_stripped():
    assert normalize_subject("RE[2]: Front End Role") == "front end role"
    assert normalize_subject("AW: Front End Role") == "front end role"


def test_the_owner_is_recognised_in_both_inboxes():
    assert is_from_owner("Test Owner <owner@example.test>")
    assert not is_from_owner("Marta Tavanez <marta@ubiminds.com>")


def test_the_match_is_case_insensitive():
    """Headers arrive in whatever case the sending client used."""
    assert is_from_owner("<OUTREACH@EXAMPLE.TEST>")


def test_a_display_name_alone_does_not_match():
    """Someone else may share a name; only the address is identity."""
    assert not is_from_owner("Test Owner <someone.else@recruiter.example>")


# ------------------------------------------------------------ quoted chain

def test_wrapped_gmail_marker_is_cut():
    own = strip_quoted_chain(TRIANGLE_REPLY)
    assert "Thank you for the update" in own
    assert "initial phone interview" not in own
    assert "Liseets Taveras" not in own


def test_outlook_and_angle_quote_styles_are_cut():
    assert strip_quoted_chain("New text.\n\n-----Original Message-----\nold") \
        == "New text."
    assert strip_quoted_chain("New text.\n\n> old quoted line") == "New text."


# ------------------------------------------------------- the key regression

def test_rejection_in_the_quoted_chain_is_not_a_rejection():
    """The failure this design is most likely to introduce.

    A live thread whose history contains a rejection for some *other* role
    must not close the row it is quoting.
    """
    body = """Thanks for clarifying! I'll put you forward for the new opening.

On Mon, Aug 17, 2026 at 9:00 AM Test Owner <
outreach@example.test> wrote:

> Understood, thanks for letting me know you are not moving forward with
> other candidates for that one.
"""
    assert detect_rejection(body) is None


def test_rejection_reports_the_sentence_not_just_a_boolean():
    body = ("Unfortunately we've moved forward with other candidates for the "
            "Front End role. That said, I have a Full Stack opening on "
            "another team - would you be interested?")
    found = detect_rejection(body)
    assert isinstance(found, Rejection)
    assert "Front End role" in found.sentence
    assert "Full Stack" not in found.sentence


def test_a_re_pitch_still_reads_as_an_ask():
    """Q7: the rejection closes one row; the pitch is scored separately."""
    body = ("Unfortunately we went with another candidate. I have a Full "
            "Stack opening though - would you be interested?")
    assert detect_rejection(body) is not None
    assert contains_ask(body) is True


def test_ordinary_scheduling_mail_is_not_a_rejection():
    assert detect_rejection(TRIANGLE_REPLY) is None


# ------------------------------------------------------ ask beats sign-off

def test_an_ask_anywhere_defeats_a_sign_off():
    body = ("Sounds good! Also, could you send over your updated resume "
            "before Thursday?")
    assert contains_ask(body) is True
    assert detect_closing_statement(body) is False


def test_marta_sign_off_closes_the_thread():
    assert detect_closing_statement(
        "Will keep you posted regarding your application"
    ) is True
    assert detect_closing_statement("Okay cool, I will keep you updated :)") \
        is True


def test_a_trailing_thanks_does_not_close_a_message_that_schedules():
    """A sign-off must not swallow a deadline.

    No question mark, no imperative -- only the requirement that the message
    be pleasantry *throughout* keeps this one alive.
    """
    body = ("We would like to schedule your phone screen for Tuesday at 3pm "
            "ET. Thanks!")
    assert detect_closing_statement(body) is False


def test_muhammad_owes_joel_so_there_is_no_ask():
    """Test #2, not #3, is what suppresses this one."""
    body = "I will be sending the job details to you shortly."
    assert contains_ask(body) is False


def test_a_sign_off_over_quoted_history_still_closes():
    body = "Perfect - thanks!\n\nOn Mon, Aug 17, 2026 at 9:00 AM someone <\na@b.com> wrote:\n\n> could you please share a few times?"
    assert detect_closing_statement(body) is True


# ------------------------------------------------------------------ titles

def test_escaped_ampersand_is_repaired_before_any_write():
    assert unescape_title("Software Verification &amp; QA Specialist") \
        == "Software Verification & QA Specialist"
    assert unescape_title("Systems Integration &amp;amp; Validation") \
        == "Systems Integration & Validation"
    assert unescape_title("R&amp;D  Engineer&#39;s Assistant") \
        == "R&D Engineer's Assistant"


# ------------------------------------- "unfortunately" is not a rejection

def test_a_recruiter_apologising_for_being_slow_is_not_a_rejection():
    """Stephen Levis, 21 Aug 2026 -- caught during the first live backfill.

    "unfortunately we" used to match this, which would have closed a row on a
    message that was actually pitching a *new* role.
    """
    body = ("Ive had another role come up that i think could be of interest - "
            "unfortunately we were a bit late on the other ones so looks like "
            "we have missed out on them")
    assert detect_rejection(body) is None


def test_unfortunately_still_counts_next_to_a_real_cue():
    for body in (
        "Unfortunately we are not moving forward with your application.",
        "Unfortunately, we have decided not to proceed at this time.",
        "Unfortunately the role has been filled.",
    ):
        assert detect_rejection(body) is not None, body


def test_unfortunately_about_logistics_is_not_a_rejection():
    assert detect_rejection(
        "Unfortunately we are still waiting on the hiring manager to confirm."
    ) is None


# ------------------------------------------------------------- soft asks

def test_a_soft_offer_still_counts_as_an_ask():
    """Rashi Sharma, 18 Aug 2026 -- no question mark, but the move is Joel's."""
    assert contains_ask(
        "If you're interested, I'd be happy to schedule a quick call to "
        "discuss the role."
    ) is True


def test_informational_updates_still_carry_no_ask():
    assert contains_ask("I will be sending the job details to you shortly.") is False


# ---------------------------------------------------------------- stripping

# Indeed's "you have a new message" wrapper, message 1a03eaa24c97c721. The raw
# body is 55,491 characters; the words in it are the six lines this asserts on.
# Reading it through the MCP server overflowed the tool-result cap onto disk and
# cost ~14,000 tokens to learn that the message is behind a login.
INDEED_WRAPPER = """<html><head><style>.x{{color:#00f}}</style></head><body>
<div style="display:none">Log in to view and respond to the message{pad}</div>
<table><tr><td><a href="https://click.appcast.io/{track}">View Message</a></td></tr>
<tr><td>You&#39;ve received a new message from Ezekiel Himole</td></tr>
<tr><td>Product Engineer | AI Startup</td></tr>
<tr><td>Naijaluxemart</td></tr>
<tr><td>San Francisco, CA 94114</td></tr>
<tr><td>This message is nonrepliable. View this message and reply from your
account to send a response.</td></tr></table>
<script>ga('send','pageview');</script></body></html>""".format(
    pad=" " * 400, track="q" * 400
)


def test_the_indeed_wrapper_reduces_to_its_six_real_lines():
    out = strip_html(INDEED_WRAPPER)
    assert len(out) < 300          # the real message: 55,491 -> 764
    assert "<" not in out and "style" not in out
    for line in (
        "Ezekiel Himole",
        "Product Engineer | AI Startup",
        "Naijaluxemart",
        "San Francisco, CA 94114",
        "nonrepliable",
    ):
        assert line in out


def test_figure_space_padding_does_not_survive():
    """U+2007 is not matched by an ASCII whitespace class.

    After tags, entities and zero-width characters were removed from the Indeed
    message, 800 of the 1,038 remaining characters were still this one padding
    character.
    """
    assert " " not in strip_html(INDEED_WRAPPER)


def test_invisible_padding_characters_are_removed():
    """U+034F is the one that got through the first attempt.

    It is a combining grapheme joiner, not whitespace, so `\\s` never touches it
    and it survives every other pass unnoticed.
    """
    padded = (
        "<p>Unfortunately͏ we are​ not­ moving‌ forward"
        "⁠.</p>"
    )
    out = strip_html(padded)
    assert out == "Unfortunately we are not moving forward."


def test_a_rejection_still_fires_after_stripping():
    """The whole point: the predicates must work on the stripped text.

    A Workday rejection arrives as HTML with the sentence split across tags. If
    stripping joined the fragments without a separator, or left markup between
    them, `detect_rejection` would silently stop matching.
    """
    workday = (
        "<html><body><table><tr><td><p>Dear Joel,</p>"
        "<p>Thank you for your interest in the Product Engineer 3 role.</p>"
        "<p>Unfortunately, we have decided to move forward with other "
        "candidates whose qualifications more closely match our needs.</p>"
        "</td></tr></table></body></html>"
    )
    found = detect_rejection(strip_html(workday))
    assert found is not None
    assert "other candidates" in found.sentence


def test_a_long_tracking_url_is_replaced_not_kept():
    body = "See the posting here: https://click.appcast.io/" + "a" * 300
    out = strip_html(body)
    assert "[long-url]" in out
    assert "aaaa" not in out


def test_a_real_posting_url_is_short_enough_to_survive():
    body = "Apply at https://boards.greenhouse.io/optoinvest/jobs/4512289005"
    assert "greenhouse.io/optoinvest" in strip_html(body)


def test_plain_text_mail_passes_through_undamaged():
    """The tag pass must be a no-op on text that has no tags.

    LinkedIn's hit-reply relay sends plain text, and it carries the live
    conversation -- damaging it would be worse than not stripping at all.
    """
    inmail = (
        "Hi Test Owner,\n\n"
        "I came across your profile and thought you'd be a great fit for a "
        "Senior Frontend Engineer role we're hiring for.\n\n"
        "Would you be open to a quick chat this week?\n\n"
        "Best,\nJack Dahler"
    )
    out = strip_html(inmail)
    assert "Jack Dahler" in out
    assert "Would you be open to a quick chat this week?" in out
    assert contains_ask(out) is True


def test_stripping_leaves_the_quote_marker_intact():
    """`strip_html` runs before `strip_quoted_chain`, so it must not eat the
    marker the second one cuts on."""
    threaded = (
        "<p>Thanks Joel, that works.</p>"
        "<p>On Thu, Aug 20, 2026 at 2:13 PM Joel Christ Abreu wrote:</p>"
        "<blockquote>Unfortunately I am not moving forward.</blockquote>"
    )
    own = strip_quoted_chain(strip_html(threaded))
    assert own == "Thanks Joel, that works."
    assert detect_rejection(strip_html(threaded)) is None


def test_an_empty_body_is_not_an_error():
    assert strip_html("") == ""
    assert strip_html(None) == ""


# ------------------------------------------------- rejections the label found

# Simplify's browser extension labels these `simplify/rejected`. All six are
# genuine rejections that `detect_rejection` read as neutral -- found by
# checking 15 labelled messages against the predicate, which agreed on 9.
# The label was right every time; the phrase list was the thing that was short.

def test_a_curly_apostrophe_does_not_hide_a_rejection():
    """Thrivent, 27 Aug 2026. Mail clients autocorrect to U+2019, and every
    phrase in the list is written with a straight apostrophe."""
    assert detect_rejection(
        "After evaluating the information provided against the requirements "
        "of the role, we won’t be moving forward with your application "
        "at this time."
    ) is not None


def test_a_different_candidate_is_still_a_rejection():
    """Intel, 27 Aug 2026. The list had 'other candidate' and 'another
    candidate' but not this third way of saying it."""
    assert detect_rejection(
        "There were several applications submitted for this position, and "
        "after careful review, unfortunately, we have decided to pursue a "
        "different candidate whose experience more closely meets our needs."
    ) is not None


def test_will_not_be_moving_forward_is_a_rejection():
    """Runlayer, 26 Aug 2026. 'not be moving forward' -- the list had
    'not moving forward' and 'not be moving ahead', and missed the pairing."""
    assert detect_rejection(
        "After reviewing your application we've determined that there isn't "
        "an ideal fit at this time, and we will not be moving forward with "
        "your candidacy."
    ) is not None


def test_a_work_authorisation_screen_out_is_a_rejection():
    """American Iron and Metal, 26 Aug 2026. No standard rejection language at
    all -- the reason replaces it."""
    assert detect_rejection(
        "Unfortunately, since you are not entitled to work in United States, "
        "we are unable to consider your application."
    ) is not None


def test_moving_forward_positively_is_still_not_a_rejection():
    """The guard on the above. 'be moving forward with your application' is
    what an *advance* says, so the negation has to be part of the match."""
    for body in (
        "Great news -- we'll be moving forward with your application!",
        "We are moving forward with your candidacy and would like to schedule "
        "a technical interview.",
    ):
        assert detect_rejection(body) is None, body
