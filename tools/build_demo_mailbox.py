"""Build the demo mailbox: twenty full-length emails, six of them with PDFs.

    python tools/build_demo_mailbox.py
    python tools/build_demo_mailbox.py --today 2026-10-16
    python tools/build_demo_mailbox.py --out some/other/folder

WHY THERE IS A SECOND MAILBOX
-----------------------------
The committed fixtures (backend/adapters/fixtures) are six short messages picked
to exercise every branch of the preprocessor, and the test suite asserts on
them. That makes them the wrong thing to put in front of an audience: a
three-line email leaves nothing to summarise, and none of them carries a file
that can be opened. This script writes a separate mailbox for demonstrations
and leaves the fixtures alone.

WHAT IT WRITES
--------------
Twenty .eml files into backend/demo_mailbox (gitignored): five Work, six
Studies, five Personal and four Promotions, each several paragraphs long, all
addressed to one invented student, Alex Tan. Six carry PDFs (seven PDFs in all)
and two carry a CSV. Nobody in them is real, and the companies use the
reserved .example domain. Every sender appears once, so "the email from Hannah"
names one email and a spoken command is never left choosing between two.

Every date is worked out from the day the script is run: the newest email
arrived this morning, and a deadline an email mentions is still ahead. Run it
again on the day of the demo and the mailbox is current again. --today pins
the day instead.

HOW A LOGIN GETS THIS MAILBOX
-----------------------------
Two lines in backend/.env point the fixture source at it:

    EMAIL_FIXTURE_DIR=backend/demo_mailbox
    EMAIL_INBOX_DIR=backend/demo_mailbox/received

Every login then reads it, except the GMAIL_OWNER login when EMAIL_SOURCE is a
Gmail source, which keeps its real inbox. Add a login for the demo with
`python -m backend.scripts.add_user demo@student.monash.edu <password>` and restart the
backend. Remove the two lines to go back to the fixtures.

NO DEPENDENCIES
---------------
Standard library only, PDFs included (see Pdf below), so it runs under
whichever Python starts the app. When the backend package can be imported, the
script reads its own output back through the app's parser and preprocessor and
prints what a reader will see. A body the preprocessor cut to nothing would
otherwise only be found on the day.
"""

import argparse
import csv
import datetime as dt
import io
import os
import re
import sys
import textwrap
import zlib
from email.message import EmailMessage
from email.utils import format_datetime, formataddr

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(_ROOT, "backend", "demo_mailbox")
# Only files carrying this prefix are ever removed from the output folder, so
# a rebuild cannot delete mail that something else put there.
PREFIX = "demo-"

READER = ("Alex Tan", "demo@student.monash.edu")

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


# --- Dates -----------------------------------------------------------------


def nice(day):
    """Friday 16 October."""
    return f"{day:%A} {day.day} {day:%B}"


def brief(day):
    """Fri 16 Oct."""
    return f"{day:%a} {day.day} {day:%b}"


class Calendar:
    """Every date the mailbox mentions, worked out from the day it is built.

    The emails and the PDFs attached to them read their dates from here, so a
    deadline in a message body and the same deadline in its attachment cannot
    disagree, and a weekday always matches its date.
    """

    def __init__(self, now):
        self.now = now
        self.today = now.date()
        days = dt.timedelta

        # Work
        self.draft_due = self.ahead(THU, 2)
        self.review = self.draft_due + days(1)
        self.period_end = self.ahead(SUN, 3)
        self.timesheets_due = self.period_end + days(1)
        self.pay_day = self.period_end + days(4)
        self.bank_details_due = self.period_end - days(2)
        self.outage = self.ahead(SAT, 2)
        self.showcase = self.ahead(TUE, 10)
        self.showcase_reply_due = self.showcase - days(5)    # the Thursday before
        self.privacy_training_due = self.ahead(WED, 3)

        # Studies. Everything hangs off the presentation day.
        self.presentations = self.ahead(WED, 8)
        self.consultation = self.presentations - days(5)     # the Friday before
        self.rehearsal = self.presentations - days(4)        # Saturday
        self.slides_due = self.presentations - days(2)       # Monday
        self.report_due = self.presentations + days(2)       # Friday
        self.peer_due = self.presentations + days(5)         # Monday
        self.exam_1 = self.ahead(MON, 21)
        self.exam_2 = self.exam_1 + days(3)
        self.exam_3 = self.exam_1 + days(8)
        self.clash_due = self.ahead(FRI, 4)
        self.revision_due = self.ahead(WED, 5)
        self.supervision = self.revision_due + days(2)
        self.quiz_review = self.ahead(THU, 3)
        self.revision_workshop = self.exam_2 - days(6)       # the Friday before
        self.recall_due = self.ahead(THU, 2)
        self.loans_due = self.ahead(MON, 5)

        # Personal. The trip is the weekend after the birthday, never the same one.
        self.birthday = self.ahead(SAT, 5)
        self.relatives_land = self.birthday - days(2)
        self.numbers_due = self.birthday - days(4)
        self.trip_start = self.birthday + days(7)
        self.trip_end = self.trip_start + days(2)
        self.trip_money_due = self.trip_start - days(8)
        self.pub_deposit_due = self.trip_start - days(5)
        self.inspection = self.ahead(TUE, 6)
        self.bills_due = self.ahead(FRI, 2)
        self.house_dinner = self.ahead(THU, 1)
        # Trivia is the Thursday after the house dinner, never the same night.
        self.trivia = self.house_dinner + days(7)
        self.trivia_reply_due = self.trivia - days(2)        # Tuesday
        # Three days out at the least, so the Friday before it is still ahead.
        self.semi_final = self.ahead(SUN, 3)
        self.fees_due = self.semi_final - days(2)            # Friday

        # Promotions
        self.coffee_sale_ends = self.ahead(SUN, 2)
        self.members_weekend = self.ahead(SAT, 1)
        self.books_sale_ends = self.ahead(SUN, 4)
        self.mealkit_offer_ends = self.ahead(FRI, 5)

    def ahead(self, weekday, at_least=1):
        """The first `weekday` that is at least `at_least` days away."""
        day = self.today + dt.timedelta(days=at_least)
        while day.weekday() != weekday:
            day += dt.timedelta(days=1)
        return day

    def received(self, days_ago, hour, minute, working_day=False):
        """When an email arrived: a clock time on an earlier day.

        Never in the future, whatever time of day the mailbox is built: a
        time that has not come yet today is moved to the day before. Work and
        university mail arrives on working days only.
        """
        def back(day, count):
            if not working_day:
                return day - dt.timedelta(days=count)
            while day.weekday() > FRI:
                day -= dt.timedelta(days=1)
            while count:
                day -= dt.timedelta(days=1)
                if day.weekday() <= FRI:
                    count -= 1
            return day

        def at(day):
            return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=self.now.tzinfo)

        day = back(self.today, days_ago)
        return at(day) if at(day) <= self.now else at(back(day, 1))


# --- PDF -------------------------------------------------------------------

# Advance widths of Helvetica and Helvetica-Bold for the characters 32 to 126,
# in thousandths of the font size (from the Adobe font metrics). These faces
# are built into every PDF viewer, so nothing is embedded; the widths are
# needed only to wrap text and to right-align a column of figures.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_HELVETICA_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)
# The few characters outside ASCII the documents use, by their Windows-1252
# byte: curly quotes, bullet, en and em dash, middle dot.
_EXTRA = {0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333, 0x95: 350, 0x96: 556, 0x97: 1000, 0xB7: 278}
_EXTRA_BOLD = {0x91: 278, 0x92: 278, 0x93: 500, 0x94: 500, 0x95: 350, 0x96: 556, 0x97: 1000, 0xB7: 278}

REGULAR, BOLD, OBLIQUE = "F1", "F2", "F3"
_METRICS = {
    REGULAR: (_HELVETICA, _EXTRA),
    BOLD: (_HELVETICA_BOLD, _EXTRA_BOLD),
    OBLIQUE: (_HELVETICA, _EXTRA),      # the oblique face keeps the upright widths
}
_BASE_FONTS = {REGULAR: "Helvetica", BOLD: "Helvetica-Bold", OBLIQUE: "Helvetica-Oblique"}

INK = (0.13, 0.16, 0.22)
GREY = (0.42, 0.45, 0.50)
RULE = (0.82, 0.85, 0.89)
TINT = (0.94, 0.96, 0.99)
WHITE = (1.0, 1.0, 1.0)


def _width(text, font, size):
    table, extra = _METRICS[font]
    total = 0
    for byte in text.encode("cp1252", "replace"):
        total += table[byte - 32] if 32 <= byte <= 126 else extra.get(byte, 556)
    return total * size / 1000.0


def _wrap(text, font, size, width):
    lines, current = [], ""
    for word in str(text).split():
        candidate = word if not current else f"{current} {word}"
        if current and _width(candidate, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _pdf_string(text):
    """`text` as a PDF literal string in WinAnsi, with nothing outside ASCII."""
    out = []
    for byte in str(text).encode("cp1252", "replace"):
        if byte in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            out.append(chr(byte))
        else:
            out.append("\\%03o" % byte)
    return "(" + "".join(out) + ")"


class Pdf:
    """A small writer for text documents on A4: a letterhead, headings,
    paragraphs, bullet lists and ruled tables, flowing onto as many pages as
    the content needs.

    It exists so the demo mailbox needs no PDF library. What it produces is an
    ordinary PDF 1.4 file that a browser's viewer opens, with real text in it
    (selectable and searchable), not a picture of text.
    """

    WIDTH, HEIGHT = 595, 842
    LEFT, RIGHT, TOP, BOTTOM = 56, 56, 56, 66

    def __init__(self, title, organisation, accent=(0.11, 0.30, 0.58), author="", created=None):
        self.title = title
        self.organisation = organisation
        self.accent = accent
        self.author = author or organisation
        self.created = created
        self.pages = []
        self._page()

    # -- low level ----------------------------------------------------------

    @property
    def _usable(self):
        return self.WIDTH - self.LEFT - self.RIGHT

    def _page(self):
        self.pages.append([])
        self.y = self.HEIGHT - self.TOP

    def _room(self, height):
        """Start a new page if `height` more points would reach the footer.
        True when it did."""
        if self.y - height < self.BOTTOM:
            self._page()
            return True
        return False

    @staticmethod
    def _text_op(x, baseline, text, font, size, colour):
        return "BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td %s Tj ET" % (
            *colour, font, size, x, baseline, _pdf_string(text))

    @staticmethod
    def _rule_op(x0, x1, y, colour=RULE, weight=0.6):
        return "%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*colour, weight, x0, y, x1, y)

    @staticmethod
    def _box_op(x, y, width, height, colour):
        return "%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*colour, x, y, width, height)

    def _draw(self, x, baseline, text, font=REGULAR, size=10.5, colour=INK):
        self.pages[-1].append(self._text_op(x, baseline, text, font, size, colour))

    def _rule(self, colour=RULE, weight=0.6):
        self.pages[-1].append(
            self._rule_op(self.LEFT, self.WIDTH - self.RIGHT, self.y, colour, weight))

    # -- elements -----------------------------------------------------------

    def letterhead(self, strapline="", reference=""):
        """A coloured band with the organisation's name, then the title."""
        band = 64
        self.pages[-1].append(self._box_op(0, self.HEIGHT - band, self.WIDTH, band, self.accent))
        self._draw(self.LEFT, self.HEIGHT - 39, self.organisation, BOLD, 14, WHITE)
        if reference:
            x = self.WIDTH - self.RIGHT - _width(reference, REGULAR, 9)
            self._draw(x, self.HEIGHT - 38, reference, REGULAR, 9, WHITE)
        self.y = self.HEIGHT - band - 28
        for line in _wrap(self.title, BOLD, 19, self._usable):
            self._draw(self.LEFT, self.y - 15, line, BOLD, 19, INK)
            self.y -= 25
        for line in _wrap(strapline, REGULAR, 10, self._usable) if strapline else ():
            self._draw(self.LEFT, self.y - 9, line, REGULAR, 10, GREY)
            self.y -= 15
        self.y -= 5
        self._rule()
        self.y -= 12

    def heading(self, text):
        # Room for the heading and a couple of lines under it, so a heading is
        # never the last thing on a page.
        self._room(64)
        self.y -= 6
        self._draw(self.LEFT, self.y - 10, text, BOLD, 12.5, self.accent)
        self.y -= 21

    def paragraph(self, text, font=REGULAR, size=10.5, colour=INK, after=7):
        leading = size * 1.45
        for line in _wrap(text, font, size, self._usable):
            self._room(leading)
            self._draw(self.LEFT, self.y - size * 0.8, line, font, size, colour)
            self.y -= leading
        self.y -= after

    def note(self, text):
        self.paragraph(text, OBLIQUE, 9, GREY, after=6)

    def bullets(self, items, size=10.5):
        leading = size * 1.45
        for item in items:
            for number, line in enumerate(_wrap(item, REGULAR, size, self._usable - 16)):
                self._room(leading)
                if number == 0:
                    self._draw(self.LEFT + 3, self.y - size * 0.8, "•", REGULAR, size, self.accent)
                self._draw(self.LEFT + 16, self.y - size * 0.8, line, REGULAR, size, INK)
                self.y -= leading
            self.y -= 2.5
        self.y -= 5

    def table(self, headers, rows, widths, align=None, bold_rows=(), size=9.5):
        """A ruled table.

        `widths` are fractions of the text width, one per column. A cell wraps
        inside its column. `align` is one letter per column, "l" or "r"; "r"
        is for figures. The header row is repeated when the table crosses onto
        a new page.
        """
        align = align or "l" * len(headers)
        pad, inset, leading = 6, 4.5, size * 1.38
        edges = [self.LEFT]
        for fraction in widths:
            edges.append(edges[-1] + fraction * self._usable)

        def measure(values, font):
            wrapped = [_wrap(value, font, size, edges[i + 1] - edges[i] - 2 * pad)
                       for i, value in enumerate(values)]
            return wrapped, max(len(lines) for lines in wrapped) * leading + 2 * inset

        def draw(wrapped, height, font, fill=None):
            if fill:
                self.pages[-1].append(
                    self._box_op(self.LEFT, self.y - height, self._usable, height, fill))
            for i, lines in enumerate(wrapped):
                for number, line in enumerate(lines):
                    baseline = self.y - inset - size * 0.8 - number * leading
                    if align[i] == "r":
                        x = edges[i + 1] - pad - _width(line, font, size)
                    else:
                        x = edges[i] + pad
                    self._draw(x, baseline, line, font, size, INK)
            self.y -= height
            self._rule()

        head, head_height = measure(headers, BOLD)
        first_height = measure(rows[0], REGULAR)[1] if rows else 0
        self._room(head_height + first_height)
        self._rule(self.accent, 1.0)
        draw(head, head_height, BOLD, TINT)
        for number, values in enumerate(rows):
            font = BOLD if number in bold_rows else REGULAR
            wrapped, height = measure(values, font)
            if self._room(height):
                draw(head, head_height, BOLD, TINT)
            draw(wrapped, height, font)
        self.y -= 13

    # -- output -------------------------------------------------------------

    def render(self):
        """The finished document as bytes."""
        total = len(self.pages)
        streams = []
        for number, operations in enumerate(self.pages, start=1):
            label = f"Page {number} of {total}"
            footer = [
                self._rule_op(self.LEFT, self.WIDTH - self.RIGHT, self.BOTTOM - 14),
                self._text_op(self.LEFT, self.BOTTOM - 28,
                              f"{self.organisation}  ·  {self.title}", REGULAR, 8.5, GREY),
                self._text_op(self.WIDTH - self.RIGHT - _width(label, REGULAR, 8.5),
                              self.BOTTOM - 28, label, REGULAR, 8.5, GREY),
            ]
            streams.append(zlib.compress("\n".join(operations + footer).encode("ascii")))

        objects = [b"", b""]                       # 1: catalog, 2: page tree; filled below

        def add(body):
            objects.append(body)
            return len(objects)                    # object numbers start at 1

        fonts = {}
        for name in (REGULAR, BOLD, OBLIQUE):
            fonts[name] = add(
                ("<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
                 % _BASE_FONTS[name]).encode("ascii"))
        resources = "<< /Font << %s >> >>" % " ".join(
            f"/{name} {number} 0 R" for name, number in fonts.items())

        created = self.created or dt.datetime.now().astimezone()
        offset = created.strftime("%z") or "+0000"
        stamp = "D:%s%s'%s'" % (created.strftime("%Y%m%d%H%M%S"), offset[:3], offset[3:5])
        info = add(("<< /Title %s /Author %s /Creator %s /CreationDate %s >>" % (
            _pdf_string(self.title), _pdf_string(self.author),
            _pdf_string("tools/build_demo_mailbox.py"), _pdf_string(stamp))).encode("ascii"))

        page_numbers = []
        for stream in streams:
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                          + stream + b"\nendstream")
            page_numbers.append(add((
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                "/Resources %s >>" % (self.WIDTH, self.HEIGHT, content, resources)).encode("ascii")))

        objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objects[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
            " ".join(f"{number} 0 R" for number in page_numbers), len(page_numbers))).encode("ascii")

        # The second line is the customary marker that the file is binary.
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref_at = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for position in offsets:
            out += b"%010d 00000 n \n" % position
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, info, xref_at)
        return bytes(out)


# --- The seven documents -----------------------------------------------------

HARBOURLINE = (0.11, 0.30, 0.58)
UNIVERSITY = (0.05, 0.35, 0.42)
EXAMS = (0.23, 0.26, 0.36)
TRIP = (0.13, 0.45, 0.33)


def churn_report(cal):
    pdf = Pdf("Q3 Customer Churn Report", "Harbourline Analytics", HARBOURLINE,
              author="Priya Nair", created=cal.now)
    pdf.letterhead(f"Draft v0.3 for the review on {nice(cal.review)}  ·  Prepared by Priya Nair",
                   "INTERNAL DRAFT")

    pdf.heading("1. Summary")
    pdf.paragraph(
        "Quarterly customer churn rose from 4.1% in Q2 to 5.3% in Q3. Of the 23,400 accounts "
        "active at the start of the quarter, 1,240 had cancelled by the end of it. The increase "
        "is concentrated in the small business segment, where churn reached 6.2%. Mid-market "
        "churn rose slightly to 4.2%, and enterprise churn was unchanged at 3.0%.")
    pdf.paragraph(
        "The pattern points to price and support, not to the product. Two thirds of the small "
        "business accounts that left had opened a support ticket in the 30 days before they "
        "cancelled, and most cancellations came within eight weeks of the July price change.")

    pdf.heading("2. Key figures")
    pdf.table(
        ["Measure", "Q2", "Q3", "Change"],
        [["Accounts active at the start of the quarter", "22,950", "23,400", "+450"],
         ["Accounts cancelled", "941", "1,240", "+299"],
         ["Quarterly churn rate", "4.1%", "5.3%", "+1.2 pts"],
         ["Median days from support ticket to cancellation", "19", "11", "-8"],
         ["Annual recurring revenue lost", "$1.42m", "$1.86m", "+$0.44m"]],
        widths=[0.52, 0.16, 0.16, 0.16], align="lrrr")

    pdf.heading("3. Churn by segment")
    pdf.table(
        ["Segment", "Accounts", "Cancelled", "Q3 rate", "Q2 rate"],
        [["Small business", "14,200", "880", "6.2%", "4.4%"],
         ["Mid-market", "7,100", "298", "4.2%", "3.9%"],
         ["Enterprise", "2,100", "62", "3.0%", "3.0%"],
         ["All customers", "23,400", "1,240", "5.3%", "4.1%"]],
        widths=[0.36, 0.16, 0.16, 0.16, 0.16], align="lrrrr", bold_rows=(3,))
    pdf.note("Figure 2, the survival curve for small business accounts, is to be replaced once "
             "the cleaned September data is available. These figures were pulled before two late "
             "cancellations were recorded and still need checking against the warehouse.")

    pdf.heading("4. What is driving the increase")
    pdf.paragraph("To be written by Alex Tan from the support ticket analysis. The working "
                  "hypotheses are:")
    pdf.bullets([
        "The July price change moved small business customers on the Starter plan from $49 to "
        "$59 a month, a 20% rise, with 30 days' notice.",
        "First-response time on support tickets grew from 6 hours to 15 hours over the quarter "
        "while two support roles were vacant.",
        "A competitor launched a free tier in August aimed at businesses with fewer than ten staff.",
    ])

    pdf.heading("5. Open questions")
    pdf.bullets([
        "Does the survival curve still show the drop at week eight once September is included?",
        "How many of the 880 small business cancellations cite price in the exit survey?",
        "Is the rise in mid-market churn real, or within the range of the last four quarters?",
    ])

    pdf.heading("6. Next steps")
    pdf.table(
        ["Task", "Owner", "Due"],
        [["Rerun the survival analysis on the cleaned September data", "Alex Tan", brief(cal.draft_due)],
         ["Check the segment table against the warehouse", "Alex Tan", brief(cal.draft_due)],
         ["Draft Section 4", "Alex Tan", f"{brief(cal.draft_due)}, 5:00 pm"],
         ["Merge sections and circulate the report", "Priya Nair", brief(cal.draft_due)],
         ["Review meeting, Room 4.12", "Everyone", f"{brief(cal.review)}, 10:00 am"]],
        widths=[0.56, 0.18, 0.26])
    return pdf.render()


def payroll_calendar(cal):
    pdf = Pdf("Payroll calendar", "Harbourline Analytics", HARBOURLINE,
              author="People and Culture", created=cal.now)
    pdf.letterhead("Fortnightly pay runs to the end of the year  ·  People and Culture")

    pdf.paragraph(
        "Timesheets are due by 10:00 am on the Monday after each pay period ends, and must be "
        "approved by your manager in Paywise by 12:00 pm the same day. Pay reaches your account "
        "on the Thursday.")

    closure_start = dt.date(cal.period_end.year, 12, 24)
    closure_end = dt.date(cal.period_end.year + 1, 1, 4)

    def working_day_on_or_before(day):
        while day.weekday() > FRI:
            day -= dt.timedelta(days=1)
        return day

    rows, early = [], False
    for run in range(6):
        end = cal.period_end + dt.timedelta(days=14 * run)
        due, paid, mark = end + dt.timedelta(days=1), end + dt.timedelta(days=4), ""
        if closure_start <= paid <= closure_end or closure_start <= due <= closure_end:
            # The run that falls in the closure is processed before it.
            due = working_day_on_or_before(closure_start - dt.timedelta(days=3))
            paid = working_day_on_or_before(closure_start - dt.timedelta(days=1))
            mark, early = " *", True
        rows.append([nice(end), f"{nice(due)}{mark}", f"{nice(paid)}{mark}"])
    pdf.table(["Pay period ending", "Timesheets due, 10:00 am", "Pay date"], rows,
              widths=[0.32, 0.36, 0.32])
    if early:
        pdf.note("* The office is closed from 24 December to 4 January, so this pay run is "
                 "processed early. Enter the hours you expect to work up to 23 December; any "
                 "correction is made in the first pay run of January.")

    pdf.heading("Before each cutoff")
    pdf.bullets([
        "Submit your timesheet in Paywise and check that your manager has approved it. A "
        "timesheet that is submitted but not approved is not paid until the following run.",
        "Interns and casual staff are capped at 20 hours per week during semester. Extra hours "
        "need an exception from People and Culture before they are worked.",
        "Changes to bank details or a tax file number declaration are made in Paywise under "
        "My Profile, at least three days before the cutoff. Never send bank details by email.",
    ])

    pdf.heading("Who to contact")
    pdf.table(
        ["Question about", "Contact", "Extension"],
        [["Timesheets and approvals", "Your manager, then Marcus Bell", "4410"],
         ["Pay, tax and superannuation", "People and Culture desk", "4410"],
         ["Paywise sign-in problems", "IT Service Desk", "4000"]],
        widths=[0.38, 0.42, 0.20])
    return pdf.render()


def presentation_schedule(cal):
    pdf = Pdf("Final presentation schedule", "DSC3900 Data Science Capstone", UNIVERSITY,
              author="Dr Ingrid Halvorsen", created=cal.now)
    pdf.letterhead(f"{nice(cal.presentations)}  ·  Learning and Teaching Building, Room G54")

    pdf.paragraph(
        "Each group has 15 minutes to present and 5 minutes for questions from the panel. A "
        "signal is given at 12 minutes and presentations are stopped at 15. Attendance for the "
        "whole session is compulsory.")

    pdf.heading("Running order")
    pdf.table(
        ["Time", "Group", "Project", "Presenters"],
        [["9:00 am", "1", "Forecasting emergency department demand", "Nguyen, Hart, Costa, Iyer"],
         ["9:20 am", "2", "Estimating pasture growth from satellite imagery", "Brooks, Zhao, Amato"],
         ["9:40 am", "3", "A fairness audit of a credit scoring model", "Rahman, Doyle, Kim, Pham"],
         ["10:00 am", "4", "Predicting tram delays from open data", "Silva, Novak, Chen"],
         ["10:20 am", "", "Break", ""],
         ["10:40 am", "5", "Summarising clinical trial reports", "Ward, Banerjee, Lowe, Sato"],
         ["11:00 am", "6", "Finding energy anomalies in campus buildings", "Reid, Haddad, Tran"],
         ["11:20 am", "7", "Sorting and summarising email with a language model",
          "Tan, Qureshi, Lim, Marsh"],
         ["11:40 am", "8", "Recommending library resources from reading lists", "Ali, Fischer, Mori"]],
        widths=[0.13, 0.09, 0.47, 0.31], bold_rows=(7,))

    pdf.heading("What to submit")
    pdf.table(
        ["Item", "Where", "Due"],
        [["Slides, as a PDF", "Moodle, one upload per group", f"{nice(cal.slides_due)}, 11:55 pm"],
         ["Final report (6,000 words)", "Moodle, one upload per group",
          f"{nice(cal.report_due)}, 11:55 pm"],
         ["Peer assessment form", "Moodle, completed individually", nice(cal.peer_due)]],
        widths=[0.36, 0.31, 0.33])

    pdf.heading("On the day")
    pdf.bullets([
        "Arrive 15 minutes before the session starts. Slides are loaded onto the lectern "
        "computer in advance, so late slides cannot be shown.",
        "The live demonstration counts towards the mark. Test it on the lectern computer, or "
        "bring a laptop with an HDMI adapter.",
        "Every member of the group is expected to speak, and you will be asked to give written "
        "feedback on two other groups.",
        f"An extra consultation runs on {nice(cal.consultation)} from 2:00 pm to 4:00 pm in "
        "Room 2.31, for groups that want to rehearse or test a demonstration.",
    ])
    return pdf.render()


def marking_rubric(cal):
    pdf = Pdf("Final presentation and report: marking rubric", "DSC3900 Data Science Capstone",
              UNIVERSITY, author="Dr Ingrid Halvorsen", created=cal.now)
    pdf.letterhead("The final presentation and report together are worth 50% of the unit mark")

    pdf.heading("Criteria")
    pdf.table(
        ["Criterion", "Weight", "What the panel looks for"],
        [["Technical quality", "30%",
          "The system works as described. Design choices are justified against the alternatives, "
          "and the hard parts of the problem are addressed and not avoided."],
         ["Evaluation", "25%",
          "Claims are measured on data the system was not tuned on. Results are reported with "
          "their uncertainty, and limitations are stated with evidence."],
         ["Demonstration", "20%",
          "A live run of the working system that covers its main use and at least one case it "
          "handles badly. A recording is accepted only if the live run fails on the day."],
         ["Communication", "15%",
          "Slides and report are clear to a technical reader from outside the project. Figures "
          "are labelled, and the time limit and the word limit are respected."],
         ["Teamwork", "10%",
          "Every member presents and answers questions on their own part. The peer assessment "
          "and the contribution statement agree with each other."]],
        widths=[0.22, 0.12, 0.66], align="lrl")

    pdf.heading("Grade descriptors")
    pdf.table(
        ["Grade", "Mark", "Typical work"],
        [["High Distinction", "80-100",
          "A working system, evaluated honestly on held-out data, with limitations that are "
          "measured and not merely listed."],
         ["Distinction", "70-79",
          "A working system with a sound evaluation; some claims rest on small samples or on "
          "data used during development."],
         ["Credit", "60-69",
          "Most of the system works. The evaluation reports results but does not test the "
          "claims that matter most."],
         ["Pass", "50-59",
          "A partial system. The evaluation is descriptive, or measures something other than "
          "what the project set out to do."],
         ["Fail", "0-49",
          "No working system, or no evidence for the claims made about it."]],
        widths=[0.22, 0.12, 0.66], align="lrl")

    pdf.note("Groups that report honest limitations with evidence consistently score better on "
             "Evaluation than groups that claim everything works.")
    pdf.paragraph(
        f"Slides are due at 11:55 pm on {nice(cal.slides_due)} and the final report at 11:55 pm "
        f"on {nice(cal.report_due)}. Late submissions lose 10% of the available mark per day.")
    return pdf.render()


def exam_timetable(cal):
    pdf = Pdf("Personal exam timetable", "Exams and Results", EXAMS,
              author="Monash Exams and Results", created=cal.now)
    pdf.letterhead("Semester 2 assessment period  ·  Alex Tan  ·  Student ID 3141 5926")

    pdf.table(
        ["Unit", "Date", "Start", "Venue", "Seat"],
        [["DSC3410 Machine Learning Systems", nice(cal.exam_1), "9:30 am",
          "Caulfield Racecourse, Hall 2", "214"],
         ["STA3120 Bayesian Data Analysis", nice(cal.exam_2), "2:00 pm",
          "Clayton campus, Sports Centre", "087"],
         ["DSC3250 Data Visualisation Studio", nice(cal.exam_3), "9:30 am",
          "Clayton campus, Sports Centre", "142"]],
        widths=[0.27, 0.24, 0.11, 0.30, 0.08], align="llllr")
    pdf.note("Seat numbers are different for every exam and are also displayed outside the "
             "venue on the day. Each exam runs for 2 hours, plus 10 minutes of reading time.")

    pdf.heading("Permitted materials")
    pdf.table(
        ["Unit", "What you may bring"],
        [["DSC3410", "Closed book. Pens, pencils and an eraser only."],
         ["STA3120", "One double-sided A4 page of handwritten notes and an approved calculator."],
         ["DSC3250", "Closed book. Pens, pencils, an eraser and a ruler."]],
        widths=[0.22, 0.78])

    pdf.heading("On the day")
    pdf.bullets([
        "Arrive at least 30 minutes before the start time. You will not be admitted more than "
        "30 minutes after an exam has started.",
        "You may not leave during the first 30 minutes or the last 15 minutes.",
        "Bring your student ID card. A digital ID on a phone is not accepted, because phones "
        "must be switched off and left in your bag.",
        "Watches of any kind are placed under your desk for the length of the exam.",
    ])

    pdf.heading("If something goes wrong")
    pdf.bullets([
        f"A clash, or three exams within 24 hours: contact the Exams Office by {nice(cal.clash_due)} "
        "so that an alternative sitting can be arranged.",
        "Illness or another serious circumstance: do not attend. Apply for special "
        "consideration within two university working days of the exam, with supporting "
        "documents. A deferred exam is not granted automatically.",
    ])
    return pdf.render()


def revision_checklist(cal):
    pdf = Pdf("Revision checklist", "STA3120 Bayesian Data Analysis", UNIVERSITY,
              author="Nikhil Sharma", created=cal.now)
    pdf.letterhead(f"Exam: {nice(cal.exam_2)}, 2:00 pm  ·  Clayton campus, Sports Centre")

    pdf.paragraph(
        "The exam has five questions worth 20 marks each and covers weeks 1 to 11. This list "
        "follows the order of the lectures. Tick a topic off only when you can do a question on "
        "it without your notes.")

    pdf.heading("Topics, and where to practise them")
    pdf.table(
        ["Weeks", "Topic", "Practise with"],
        [["1 and 2", "Bayes' theorem, priors and likelihoods", "Tutorial 2, questions 1 to 4"],
         ["3 and 4", "Conjugate models: beta-binomial and gamma-Poisson",
          "Quiz 1, and the 2025 exam, question 1"],
         ["5", "Credible intervals and posterior summaries", "Tutorial 5, questions 2 and 3"],
         ["6 and 7", "Markov chain Monte Carlo and convergence checks", "Quiz 3, and lab 7"],
         ["8 and 9", "Hierarchical models and partial pooling",
          "Lab 9, and the 2025 exam, question 4"],
         ["10", "Posterior predictive checks", "Quiz 4, questions 3 to 5"],
         ["11", "Model comparison", "Tutorial 11, all questions"]],
        widths=[0.14, 0.46, 0.40], bold_rows=(4, 5))
    pdf.note("The two rows in bold carry the most marks, and are where most of the class lost "
             "marks in quiz 4.")

    pdf.heading("Before the exam")
    pdf.bullets([
        f"Quiz 4 drop-in: {nice(cal.quiz_review)}, 1:00 pm to 2:00 pm, Mathematics building, "
        "Room 1.17. Not recorded.",
        f"Revision workshop with Dr Park: {nice(cal.revision_workshop)}, 10:00 am to 12:00 pm, "
        "lecture theatre S3. Recorded.",
        "Sit the 2025 exam under time: 2 hours, plus 10 minutes of reading.",
        "Write your page of notes: one double-sided A4 page, handwritten. Printed or "
        "photocopied pages are taken away at the door.",
    ])

    pdf.heading("In the exam")
    pdf.bullets([
        "Bring an approved calculator. Phones and smart watches are not calculators.",
        "Show your working. A wrong answer with the right method earns most of the marks; a "
        "right answer with no method earns very few.",
        "Each question is worth the same, so give each about 24 minutes and move on.",
    ])
    return pdf.render()


def trip_itinerary(cal):
    start = cal.trip_start
    second, third = start + dt.timedelta(days=1), cal.trip_end
    pdf = Pdf("Great Ocean Road: the plan", "Three days, four people, one hire car", TRIP,
              author="Josh Petrovic", created=cal.now)
    pdf.letterhead(f"{nice(start)} to {nice(third)}  ·  Josh, Alex, Nadia and Mel")

    pdf.heading(f"Day 1  ·  {nice(start)}  ·  Clayton to Apollo Bay")
    pdf.bullets([
        "7:30 am: leave from Josh's place in Clayton. Coffee is on whoever is last to the car.",
        "9:15 am: Torquay, then Bells Beach for the lookout.",
        "12:30 pm: lunch in Lorne. Walk to Teddy's Lookout afterwards if the weather holds.",
        "4:00 pm: check in at the house in Apollo Bay. Dinner at the pub at 7:00 pm.",
    ])

    pdf.heading(f"Day 2  ·  {nice(second)}  ·  The Otways and the Twelve Apostles")
    pdf.bullets([
        "9:00 am: Otway treetop walk. Allow two hours; it is $28 each and booked for four.",
        "1:00 pm: late lunch at Lavers Hill, then Loch Ard Gorge.",
        "6:45 pm: Twelve Apostles for sunset. Back to Apollo Bay by 9:00 pm.",
    ])

    pdf.heading(f"Day 3  ·  {nice(third)}  ·  Home the slow way")
    pdf.bullets([
        "10:00 am: check out. The house has to be left as we found it.",
        "11:30 am: Colac, for the bakery.",
        "3:30 pm: car back to the hire depot in Clayton, with a full tank.",
    ])

    pdf.heading("What it costs")
    pdf.table(
        ["Item", "Total", "Each"],
        [["Car hire, three days", "$312", "$78"],
         ["House in Apollo Bay, two nights", "$540", "$135"],
         ["Fuel, estimated", "$120", "$30"],
         ["Otway treetop walk", "$112", "$28"],
         ["Total", "$1,084", "$271"]],
        widths=[0.56, 0.22, 0.22], align="lrr", bold_rows=(4,))
    pdf.paragraph(
        f"Josh has paid for the car and the house. Transfer $271 to him by {nice(cal.trip_money_due)}, "
        "with your name in the reference. Food is not included; we split it as we go.")

    pdf.heading("Bring")
    pdf.bullets([
        "A proper jacket. Apollo Bay is cold at night, even in spring.",
        "Walking shoes for the Otways, and swimmers if you are brave.",
        "Your licence, if you are Alex or Nadia: you are the two drivers on the hire agreement.",
        "A phone charger and a water bottle.",
    ])
    return pdf.render()


def coffee_newsletter(cal):
    """The one HTML-only email. Paragraphs are separated by a pair of line
    breaks inside one block, the way a lot of marketing mail is written, which
    is also what keeps a blank line between them in the text the reader sees."""
    paragraphs = [
        "<strong>Spring roast has landed</strong>",
        "Hi Alex,",
        "Every year we hold back the first lot of the new harvest for one roast that only runs "
        "through spring. This year it is a washed Ethiopian from the Guji zone, roasted a touch "
        "lighter than our house blend, and it tastes like apricot, black tea and honey. It went "
        "into the roaster last week and the first bags are ready to ship today.",
        "To celebrate, everything in the shop is <strong>25% off</strong> until midnight on "
        f"{nice(cal.coffee_sale_ends)}. That includes the spring roast, all six single origins, "
        "the house espresso blend and decaf. Use the code SPRING25 at checkout. Orders over $60 "
        "ship free anywhere in Australia, and orders placed before 2:00 pm leave the roastery "
        "the same day.",
        "A few prices worth knowing before you fill your basket:",
        "<br>".join([
            "- Spring roast, 250 g: $19.50, down from $26.00",
            "- House espresso blend, 1 kg: $41.25, down from $55.00",
            "- Single origin sampler, four 100 g bags: $27.00, down from $36.00",
            "- Pour-over starter kit with a 250 g bag: $48.75, down from $65.00",
        ]),
        "If you already have a coffee subscription, the discount applies to your next delivery "
        "automatically and you do not need the code. If you have been thinking about starting "
        "one, this is the cheapest it will be all year: a fortnightly 250 g bag is $14.60 for "
        "the first three deliveries, and you can pause or cancel whenever you like.",
        "We roast in small batches and the spring roast usually sells out in about ten days, so "
        "if apricot and black tea sound like your sort of morning, do not leave it until the "
        "weekend.",
        "Happy brewing,<br>Anna and the team at Kettle &amp; Bean",
    ]
    footer = (
        "You are receiving this email because you joined the Kettle &amp; Bean mailing list. "
        '<a href="https://kettleandbean.example/unsubscribe">Unsubscribe</a> | '
        '<a href="https://kettleandbean.example/preferences">Manage preferences</a> | '
        "Kettle &amp; Bean Coffee Roasters, 14 Albert Street, Brunswick VIC 3056")
    return ("<html>\n<body>\n<div>" + "<br><br>\n".join(paragraphs) + "</div>\n<hr>\n"
            f"<div>{footer}</div>\n</body>\n</html>\n")


def task_list(cal):
    """The group's task list, as the CSV a shared spreadsheet exports."""
    rows = [
        ("Task", "Owner", "Due", "Status"),
        ("Rerun the classifier on the held-out set", "Alex", brief(cal.consultation), "In progress"),
        ("Update the confusion matrix", "Alex", brief(cal.consultation), "Not started"),
        ("Write up where the classifier fails", "Alex", brief(cal.consultation), "Not started"),
        ("Two evaluation slides", "Alex", brief(cal.consultation), "Not started"),
        ("Script the live demo", "Sana", brief(cal.consultation), "In progress"),
        ("Record a backup video of the demo", "Sana", brief(cal.consultation), "Not started"),
        ("Test the demo on the lectern computer in G54", "Sana", brief(cal.consultation), "Booked"),
        ("Introduction and architecture diagram", "Wei Jie", brief(cal.consultation), "Done"),
        ("Assemble the slide deck", "Wei Jie", brief(cal.rehearsal), "In progress"),
        ("Limitations and future work", "Dylan", brief(cal.consultation), "In progress"),
        ("Cut the report from 6,480 to 6,000 words", "Dylan", brief(cal.rehearsal), "Not started"),
        ("Full rehearsal, Hargrave-Andrew Library, Room 3", "Everyone", brief(cal.rehearsal), "Booked"),
        ("Upload the slides to Moodle", "Wei Jie", brief(cal.slides_due), "Not started"),
        ("Upload the final report to Moodle", "Dylan", brief(cal.report_due), "Not started"),
    ]
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return out.getvalue().encode("utf-8")


def data_dictionary():
    """The customer events table's columns, as the CSV a data catalogue exports."""
    rows = [
        ("Column", "Type", "Description", "Sensitivity"),
        ("event_id", "string", "Unique identifier for the event", "Internal"),
        ("account_id", "string", "Customer account the event belongs to", "Confidential"),
        ("event_time", "timestamp", "When the event happened, in UTC", "Internal"),
        ("event_type", "string",
         "One of login, invoice_viewed, ticket_opened, plan_changed, cancelled", "Internal"),
        ("plan", "string", "Plan at the time of the event: starter, team or enterprise", "Internal"),
        ("segment", "string", "Small business or enterprise", "Internal"),
        ("contact_email", "string", "Email address of the user who triggered the event",
         "Personal information"),
        ("contact_name", "string", "Name of the user who triggered the event",
         "Personal information"),
        ("ip_address", "string", "Address the request came from", "Personal information"),
        ("ticket_text", "string", "Free text of a support ticket, for ticket_opened events",
         "Personal information"),
        ("monthly_value", "decimal", "Monthly contract value in Australian dollars",
         "Confidential"),
        ("loaded_at", "timestamp", "When the row reached the warehouse", "Internal"),
    ]
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return out.getvalue().encode("utf-8")


# --- The twenty emails -------------------------------------------------------

_LIST_ITEM = re.compile(r"(?:- |\d+\. )")


def flow(text):
    """Join the wrapped lines of each paragraph into one line.

    The bodies below are wrapped so they can be read and edited here. A mail
    client sends a paragraph as one line and leaves the wrapping to the
    reader's window, and the reading pane shows every line of a message as a
    paragraph of its own, so a body wrapped at 78 columns would be shown
    ragged. A list item keeps its own line.
    """
    paragraphs = []
    for block in textwrap.dedent(text).strip().split("\n\n"):
        lines = []
        for line in block.split("\n"):
            line = line.strip()
            if lines and not _LIST_ITEM.match(line):
                lines[-1] += " " + line
            else:
                lines.append(line)
        paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def emails(cal):
    """The twenty messages, in no particular order: each carries its own date.

    Priya's is the only one sent this morning after the coffee offer, so once
    the mailbox is built later than 8:47 am, "the latest email" is hers: a long
    one with a PDF. Keep it that way when adding to the list.

    `closing` is appended as written, because a sign-off and the name block
    under it are separate lines, not a paragraph.
    """
    pdf = ("application", "pdf")
    one_day = dt.timedelta(days=1)
    days_to_slides = (cal.slides_due - cal.today).days

    return [
        # ---- Work -----------------------------------------------------------
        dict(
            file="work-churn-report",
            sender=("Priya Nair", "priya.nair@harbourline.example"),
            subject="Q3 churn report: your section and Friday's review",
            received=cal.received(0, 8, 47, working_day=True),
            unread=True,
            body=flow(f"""
                Hi Alex,

                Thanks for turning the cohort tables around so quickly last week. I have
                folded them into the draft of the Q3 customer churn report, which is attached,
                and I would like your help getting it over the line before it goes to the
                leadership team.

                The headline is not great. Quarterly churn rose from 4.1% in Q2 to 5.3% in Q3,
                which is 1,240 accounts out of 23,400. Almost all of the increase comes from
                small business customers, where churn reached 6.2%, while enterprise held
                steady at 3.0%. Section 3 of the draft has the full breakdown by segment.

                There are three things I need from you:

                1. Rerun the survival analysis for the small business segment using the cleaned
                September data, and replace Figure 2 with the updated curve.
                2. Check the numbers in the segment table against the warehouse. I pulled them
                early in the week and two late cancellations may be missing.
                3. Write two or three paragraphs for Section 4 on what is driving the increase.
                The support ticket data you looked at in August should be the main evidence.

                Could you send me your section by 5:00 pm on {nice(cal.draft_due)}? That gives
                me the evening to merge everything before the review meeting on
                {nice(cal.review)} at 10:00 am in Room 4.12. Daniel and Hannah will both be
                there, and it would be good for you to present the survival analysis yourself,
                so please let me know whether you can make it.

                If the September data is not ready in time, tell me as soon as you know and we
                will fall back to the August extract with a note explaining why.
                """),
            closing="Thanks,\nPriya\n\nPriya Nair\nSenior Data Analyst, Harbourline Analytics",
            attachments=[("Q3-churn-report-draft.pdf", pdf, churn_report(cal))],
        ),
        dict(
            file="work-timesheets",
            sender=("Marcus Bell", "marcus.bell@harbourline.example"),
            subject="Timesheets: a new approval step, and the payroll calendar",
            received=cal.received(1, 15, 20, working_day=True),
            unread=True,
            body=flow(f"""
                Hi everyone,

                A reminder that timesheets for the fortnight ending {nice(cal.period_end)} are
                due by 10:00 am on {nice(cal.timesheets_due)}. Anything submitted after that
                will be paid in the following pay run, so please do not leave it until the
                morning.

                Two things change from this pay period.

                First, timesheets now need to be approved by your manager in Paywise before
                the cutoff, not just submitted. A timesheet that is submitted but not approved
                will not be paid. Managers have been asked to approve by 12:00 pm on the due
                date, but it is worth sending yours through early and giving them a nudge.

                Second, interns and casual staff are capped at 20 hours per week during
                semester. If you expect to go over that, for example for the Q3 reporting
                crunch, your manager has to request an exception from People and Culture
                before the hours are worked. We cannot approve extra hours after the fact.

                Pay for this period will reach your account on {nice(cal.pay_day)}. The payroll
                calendar for the rest of the year is attached, including the earlier cutoff in
                December because of the office closure from 24 December to 4 January.

                If your bank details or tax file number declaration have changed, update them
                in Paywise under My Profile by {nice(cal.bank_details_due)}. Please do not
                email bank details to me.

                Any questions, reply to this email or call the People and Culture desk on
                extension 4410.
                """),
            closing="Kind regards,\nMarcus\n\nMarcus Bell\n"
                    "People and Culture Coordinator, Harbourline Analytics",
            attachments=[("Payroll-calendar.pdf", pdf, payroll_calendar(cal))],
        ),
        dict(
            file="work-warehouse-outage",
            sender=("IT Service Desk", "servicedesk@harbourline.example"),
            subject=f"Planned outage: data warehouse offline overnight on {nice(cal.outage)}",
            received=cal.received(2, 11, 5, working_day=True),
            unread=False,
            body=flow(f"""
                Hello all,

                The analytics data warehouse will be offline for planned maintenance from
                10:00 pm on {nice(cal.outage)} until 2:00 am on {nice(cal.outage + one_day)}.
                We are upgrading the storage layer and moving the nightly load jobs to the new
                scheduler, and neither can be done while the warehouse is in use.

                What this means for you:

                - Any query still running at 10:00 pm will be cancelled. Long jobs should be
                finished or paused before then.
                - Dashboards will show data as at 9:30 pm on {nice(cal.outage)} until the
                warehouse is back. They will not show an error, so please do not treat them as
                live during the window.
                - The nightly load will run late and should finish by 6:00 am on
                {nice(cal.outage + one_day)}. Reports that depend on it will be about four
                hours behind.
                - After the upgrade you will be asked to sign in again the first time you
                connect. Saved passwords in desktop tools will need to be entered again.

                There is nothing you need to install. If you have a scheduled extract that runs
                overnight on {nice(cal.outage)}, move it to after 6:00 am or let us know and we
                will reschedule it for you.

                We have tested the upgrade twice on the staging warehouse and expect to finish
                early. If something goes wrong we will roll back, and the warehouse will be
                available on its old configuration by 2:00 am regardless. Progress updates will
                be posted in the #it-status channel.

                Sorry for the weekend disruption, and thank you for your patience.
                """),
            closing="IT Service Desk\nHarbourline Analytics\n"
                    "servicedesk@harbourline.example, extension 4000",
        ),
        dict(
            file="work-showcase-talk",
            sender=("Hannah Reid", "hannah.reid@harbourline.example"),
            subject="Analytics showcase: would you give a ten-minute talk?",
            received=cal.received(1, 9, 12, working_day=True),
            unread=True,
            body=flow(f"""
                Hi Alex,

                I run the analytics showcase, where once a month a few people from the team
                show the rest of the company something they have been working on. The next one
                is on {nice(cal.showcase)} from 3:00 pm to 4:00 pm in the Level 4 town hall
                space, and I would like you to take one of the three slots.

                Priya showed me the survival curves you built for the small business segment,
                and I think they would make a very good talk. Most people outside the team have
                never seen churn drawn as a curve over time, and the point where customers on
                monthly plans drop away after their third invoice is exactly the kind of thing
                the account managers need to hear.

                Each talk is ten minutes with five minutes for questions. It does not need to be
                polished. Three or four slides are plenty, and a chart that people can read from
                the back of the room matters more than anything else. Please leave out customer
                names and anything from the support tickets, because the session is recorded
                and the recording goes on the intranet.

                If you are happy to do it, could you send me a title and one sentence about the
                talk by {nice(cal.showcase_reply_due)}? I will put the running order together
                that afternoon. I can also book you 20 minutes with me earlier that week to run
                through it first, which most first-time speakers find useful.

                I know this lands in the middle of your exams and the capstone, so please say
                no if the timing is bad. There is another showcase in late November and the
                offer stands for that one too.
                """),
            closing="Thanks,\nHannah\n\nHannah Reid\nAnalytics Manager, Harbourline Analytics",
        ),
        dict(
            file="work-data-access",
            sender=("Lucas Meyer", "lucas.meyer@harbourline.example"),
            subject="Access approved: the customer events table, with three conditions",
            received=cal.received(3, 14, 40, working_day=True),
            unread=False,
            body=flow(f"""
                Hi Alex,

                Your request for read access to the customer events table has been approved.
                Priya sponsored it, and it stays active until the end of your internship unless
                she asks for it to be extended.

                The access is live now. The table is analytics.customer_events in the
                warehouse, and it holds one row for every login, invoice view, support ticket,
                plan change and cancellation since January 2024, which is about 41 million
                rows. A data dictionary is attached so you can see what each column holds
                before you query it.

                It comes with three conditions, because four of the columns hold personal
                information.

                1. Complete the Handling Customer Data module in the learning portal by
                {nice(cal.privacy_training_due)}. It takes about 40 minutes. If it is not done
                by then the access is switched off automatically and you will need to ask
                again.
                2. Do not copy the contact_email, contact_name, ip_address or ticket_text
                columns out of the warehouse. That includes notebooks saved to your laptop,
                spreadsheets and anything pasted into a chat. Aggregate first, then export.
                3. Filter on event_time in every query. The table is partitioned by day, and a
                query without a date range scans all of it, which costs real money and slows
                the dashboards down for everyone.

                For the churn work you will mostly want the cancelled and ticket_opened events
                joined to accounts on account_id. There is a view called
                analytics.customer_events_safe that leaves out the four personal columns, and I
                would start there. Most questions can be answered from it, and nothing you take
                from it needs a second look from us.

                One more thing to plan around. The warehouse is offline overnight on
                {nice(cal.outage)} for the storage upgrade, so do not leave a long query
                running into that evening.

                If a query runs for more than ten minutes, stop it and send it to me. It is
                nearly always a missing date filter, and I would rather look at it than have
                you wait.
                """),
            closing="Cheers,\nLucas\n\nLucas Meyer\nData Engineering, Harbourline Analytics",
            attachments=[("customer-events-data-dictionary.csv", ("text", "csv"),
                          data_dictionary())],
        ),

        # ---- Studies --------------------------------------------------------
        dict(
            file="studies-presentations",
            sender=("Dr Ingrid Halvorsen", "ingrid.halvorsen@monash.edu"),
            subject="Capstone final presentations: schedule, rubric and what to submit",
            received=cal.received(1, 16, 15, working_day=True),
            unread=True,
            body=flow(f"""
                Dear students,

                The final presentations for the Data Science Capstone (DSC3900) will be held on
                {nice(cal.presentations)} in the Learning and Teaching Building, Room G54. The
                full running order is in the attached schedule. Please read it carefully,
                because several groups have moved since the draft I showed in the workshop.

                Each group has 15 minutes to present, followed by 5 minutes of questions from
                the panel. The panel is strict about time: you will be given a signal at 12
                minutes and stopped at 15. Every member of the group is expected to speak, and
                the live demonstration of your system counts towards the mark, so make sure it
                runs on the lectern computer or bring a laptop with an HDMI adapter.

                Three things are due around the day:

                - Slides, as a PDF, uploaded to Moodle by 11:55 pm on {nice(cal.slides_due)}.
                Late slides cannot be loaded onto the lectern computer.
                - The final report, also through Moodle, by 11:55 pm on {nice(cal.report_due)}.
                The limit is 6,000 words excluding appendices.
                - The peer assessment form, which each of you completes individually by
                {nice(cal.peer_due)}. It is confidential and it does affect individual marks.

                The marking rubric is attached as well. In short, technical quality is worth
                30%, evaluation 25%, the demonstration 20%, communication 15% and teamwork 10%.
                Groups that report honest limitations with evidence consistently score better
                on evaluation than groups that claim everything works.

                Attendance for the whole session is compulsory, not just your own slot, and you
                will be asked to give written feedback on two other groups. If you cannot
                attend for a reason covered by special consideration, apply through the
                university portal and email me before {nice(cal.slides_due)}, not after the
                presentation.

                I will hold an extra consultation on {nice(cal.consultation)} from 2:00 pm to
                4:00 pm in my office, Room 2.31, for any group that wants to rehearse or test
                their demonstration.
                """),
            closing="Kind regards,\nIngrid\n\nDr Ingrid Halvorsen\n"
                    "Unit Coordinator, Data Science Capstone\nFaculty of Information Technology",
            attachments=[
                ("Capstone-presentation-schedule.pdf", pdf, presentation_schedule(cal)),
                ("Capstone-marking-rubric.pdf", pdf, marking_rubric(cal)),
            ],
        ),
        dict(
            file="studies-exam-timetable",
            sender=("Monash Exams and Results", "no-reply@monash.edu"),
            subject="Your personal exam timetable for Semester 2 is available",
            received=cal.received(3, 9, 2, working_day=True),
            unread=False,
            body=flow(f"""
                Dear Alex,

                Your personal exam timetable for the Semester 2 assessment period is now
                available, and a copy is attached to this email. You have three exams:

                - DSC3410 Machine Learning Systems: {nice(cal.exam_1)} at 9:30 am, Caulfield
                Racecourse, Hall 2
                - STA3120 Bayesian Data Analysis: {nice(cal.exam_2)} at 2:00 pm, Clayton
                campus, Sports Centre
                - DSC3250 Data Visualisation Studio: {nice(cal.exam_3)} at 9:30 am, Clayton
                campus, Sports Centre

                Your seat number for each exam is shown on the attached timetable and will also
                be displayed outside the venue on the day. Seat numbers are different for every
                exam.

                Please arrive at least 30 minutes before the start time. You will not be
                admitted more than 30 minutes after an exam has started, and you may not leave
                during the first 30 minutes or the last 15 minutes. Bring your student ID card;
                a digital ID on your phone is not accepted, because phones must be switched off
                and left in your bag.

                Each exam has its own list of permitted materials, set by the unit coordinator.
                For STA3120 you may bring one double-sided A4 page of handwritten notes and an
                approved calculator. The other two exams are closed book.

                If two of your exams clash, or if you are scheduled for three exams within 24
                hours, contact the Exams Office by {nice(cal.clash_due)} so that an alternative
                sitting can be arranged. Requests received after that date cannot be
                guaranteed.

                If illness or another serious circumstance prevents you from sitting an exam,
                do not attend. Apply for special consideration within two university working
                days of the exam, with supporting documents. A deferred exam is not granted
                automatically.

                We wish you the best for your exams.
                """),
            closing="Monash Exams and Results\nStudent and Education Business Services",
            attachments=[("Exam-timetable-Semester-2.pdf", pdf, exam_timetable(cal))],
        ),
        dict(
            file="studies-literature-review",
            sender=("Dr Amelia Ford", "a.ford@monash.edu"),
            subject="Comments on your literature review draft",
            received=cal.received(4, 17, 48, working_day=True),
            unread=False,
            body=flow(f"""
                Hi Alex,

                I have read the draft literature review you sent last week. It is a solid start
                and the structure is much clearer than the outline we discussed, so thank you
                for taking that feedback on board. I have four comments, in rough order of
                importance.

                1. The review describes each paper in turn but rarely compares them. Section 2
                in particular reads as a list. Group the retrieval-augmented approaches
                together and say where they agree, where they disagree and which evaluation
                choices explain the difference.

                2. You cite accuracy figures from different papers side by side as if they were
                comparable. They are not: the datasets differ, and two of the papers report
                results on test sets of fewer than 200 examples. Either add a table that states
                the dataset and its size for each figure, or drop the direct comparison.

                3. The section on hallucination needs the two 2024 survey papers I mentioned.
                At the moment the most recent source in that section is from 2022, which is old
                for this topic.

                4. The research gap in your final paragraph is asserted, not argued. One or two
                sentences showing that nobody has measured groundedness on email specifically
                would make the gap convincing.

                None of this needs new experiments. I would expect the revision to take two or
                three days of focused work.

                Could you send me the revised draft by {nice(cal.revision_due)}? We can then go
                through it at our next meeting, which I have moved to {nice(cal.supervision)}
                at 11:00 am because of a faculty board clash. If that time does not suit,
                suggest another on the same day.
                """),
            closing="Best wishes,\nAmelia",
        ),
        dict(
            file="studies-group-tasks",
            sender=("Wei Jie Lim", "weijie.lim@example.com"),
            subject="Group 7: who is doing what before the presentation",
            received=cal.received(1, 21, 40),
            unread=True,
            body=flow(f"""
                Hey team,

                Writing this down so we stop losing it in the group chat. We have
                {days_to_slides} days until slides are due on {nice(cal.slides_due)}, and I
                think we are in decent shape, but only if everyone finishes their part by
                {nice(cal.consultation)} so we get one full rehearsal.

                Here is the split we agreed on after the workshop:

                - Alex: the evaluation section. Rerun the classifier on the held-out set,
                update the confusion matrix and write the half page on where it fails. Also
                the two evaluation slides.
                - Sana: the live demo. Script it, record a backup video in case the wifi dies,
                and test it on the lectern computer in G54 at the consultation on
                {nice(cal.consultation)}.
                - Me: the introduction, the architecture diagram and stitching the slides
                together so they look like one deck.
                - Dylan: limitations and future work, plus proofreading the whole report
                against the 6,000 word limit. We are at 6,480 words right now, so something
                has to go.

                The spreadsheet with the full task list is attached. I have marked what is
                done, and anything still not started on {nice(cal.consultation)} we need to
                talk about.

                Two decisions we still need to make. First, do we show the failure cases in the
                demo or only in the slides? I think showing one live is stronger, and Dr
                Halvorsen said honest limitations score better. Second, who answers questions?
                I would suggest that whoever wrote a section answers on it, with Alex taking
                anything about accuracy.

                Can everyone reply with a thumbs up or objections by tomorrow night? And can we
                lock in a rehearsal for {nice(cal.rehearsal)} at 4:00 pm in the Hargrave-Andrew
                Library? I have booked Room 3 for two hours.
                """),
            closing="Cheers,\nWei Jie",
            attachments=[("group7-task-list.csv", ("text", "csv"), task_list(cal))],
        ),
        dict(
            file="studies-quiz-feedback",
            sender=("Nikhil Sharma", "nikhil.sharma@monash.edu"),
            subject="STA3120 quiz 4: your result, and what to revise before the exam",
            received=cal.received(1, 16, 45, working_day=True),
            unread=True,
            body=flow(f"""
                Hi Alex,

                Quiz 4 has been marked and your result is on Moodle: 14 out of 20, which is
                70%. The class average was 12.6, so you are comfortably above it, but I wanted
                to write because the marks you lost were all in one place, and it is a place
                the exam will go.

                Questions 1 and 2, on choosing priors and reading a trace plot, were full
                marks. Questions 3 to 5 were on posterior predictive checks, and that is where
                the six marks went. In question 4 you compared the observed mean with the
                posterior mean of the parameter, when the check needs data simulated from the
                model. It is a very common mix-up, and it is easier to fix now than in the
                exam.

                Three things I would do, in this order:

                1. Redo lab 9 without looking at the solution. It builds a hierarchical model
                and then checks it, which covers both of the topics the exam weights most
                heavily.
                2. Work through the 2025 exam under time: 2 hours, plus 10 minutes of reading.
                Questions 1 and 4 are the closest to what you will see this year.
                3. Write your page of notes early. You may bring one double-sided A4 page,
                handwritten, and making it is half the revision.

                I have attached a revision checklist that lists every topic by week and says
                which tutorial, quiz or past exam question to practise it with. The two rows in
                bold are the ones I would spend longest on.

                There are two chances to ask questions before the exam on {nice(cal.exam_2)}.
                I am holding a drop-in to go through quiz 4 on {nice(cal.quiz_review)} from
                1:00 pm to 2:00 pm in Room 1.17 of the Mathematics building, and Dr Park is
                running a revision workshop on {nice(cal.revision_workshop)} from 10:00 am to
                12:00 pm in lecture theatre S3. The workshop will be recorded, but the drop-in
                will not.

                If you would like your quiz paper looked at again, reply to this email before
                the drop-in and tell me which question. Marks can go down as well as up when a
                paper is looked at again.
                """),
            closing="Nikhil\n\nNikhil Sharma\nTeaching Associate, STA3120 Bayesian Data Analysis",
            attachments=[("STA3120-revision-checklist.pdf", pdf, revision_checklist(cal))],
        ),
        dict(
            file="studies-library-loans",
            sender=("Hargrave-Andrew Library", "library@monash.edu"),
            subject="Two loans due soon, and one item recalled",
            received=cal.received(4, 9, 0, working_day=True),
            unread=False,
            body=flow(f"""
                Dear Alex,

                Here is a summary of the items on your library account that need attention.
                Two loans are due soon, and one of them has been requested by another borrower,
                which shortens the time you have it.

                Recalled item. Pattern Recognition and Machine Learning has been recalled and
                is now due on {nice(cal.recall_due)}. A recalled item cannot be renewed. If it
                comes back late, the charge is $2.00 a day up to $30.00, and you will not be
                able to borrow or renew anything else until it is returned.

                Due soon. Bayesian Data Analysis, third edition, is due on
                {nice(cal.loans_due)}. Nobody else has asked for it, so you can renew it twice
                more, for three weeks each time. Renew it under My Loans in Library Search, or
                at any self-service kiosk.

                Ready to collect. The interlibrary loan you asked for, Statistical Rethinking,
                second edition, has arrived and is on the hold shelf at the Hargrave-Andrew
                Library under the first four letters of your surname. It will be kept until
                closing on {nice(cal.loans_due)} and then sent back.

                Items can be returned through the after-hours chute beside the main entrance,
                or at any Monash library, whichever campus they came from. Returns are taken
                off your account the next working day, so a book put in the chute on the day it
                is due counts as on time.

                During the exam period the library opens from 8:00 am to midnight on weekdays
                and from 10:00 am to 10:00 pm at weekends, and group study rooms can be booked
                for up to two hours a day. A room booked and left empty for 15 minutes is given
                to the next group waiting.

                If you believe a recall or a charge is a mistake, reply to this email or speak
                to the staff at the information desk on the ground floor.
                """),
            closing="Hargrave-Andrew Library\nMonash University Library\nlibrary@monash.edu",
        ),

        # ---- Personal -------------------------------------------------------
        dict(
            file="personal-birthday-dinner",
            sender=("Linda Tan", "linda.tan@example.com"),
            subject="Dad's 60th birthday dinner: the plan",
            received=cal.received(1, 20, 15),
            unread=True,
            body=flow(f"""
                Hi sweetheart,

                I hope the assignments are not eating you alive. I am writing instead of
                calling because there are too many details and you will want them in one
                place.

                Dad's 60th birthday dinner is confirmed for {nice(cal.birthday)} at 6:30 pm at
                Golden Lotus in Glen Waverley. I have booked the private room upstairs for 14
                people. He still thinks it is just the four of us going out for noodles, so
                please, please do not mention it when you call him.

                Aunty Mei and Uncle Raymond are flying in from Penang on
                {nice(cal.relatives_land)} and landing at 9:20 am. Your brother will pick them
                up, so you are off the hook for the airport, but I do need your help with three
                things:

                - Pick up the cake from Rosella Patisserie in Carlton before 5:00 pm on the
                day. It is paid for and under my name. It is a large one, so bring the car and
                not the train.
                - Bring the old photo album from your bookshelf, the green one from the Ipoh
                years. Aunty Mei wants to do a slideshow and I cannot find our copy.
                - Say a few words. Nothing long, two minutes. Your brother is doing the toast,
                so you just need a story. The one about the fishing trip is fine as long as
                you leave out the part with the car keys.

                The restaurant needs final numbers by {nice(cal.numbers_due)}, so let me know
                whether Sam is coming with you. There is a set menu at $68 per person and I
                have asked for two vegetarian meals already.

                Come by the house around 4:30 pm if you can, so you and I can drive over early
                and put up the decorations before everyone arrives.

                Love you. Eat some vegetables.
                """),
            closing="Mum",
        ),
        dict(
            file="personal-road-trip",
            sender=("Josh Petrovic", "josh.petrovic@example.com"),
            subject="Great Ocean Road: itinerary and what everyone owes",
            received=cal.received(2, 19, 32),
            unread=False,
            body=flow(f"""
                Hey Alex,

                The trip is locked in. I have put the full plan in the attached PDF, but here
                is the short version so nobody can say they did not know.

                We leave at 7:30 am on {nice(cal.trip_start)} from my place in Clayton and get
                back on the evening of {nice(cal.trip_end)}. Day one is Torquay, Bells Beach
                and lunch in Lorne, then on to Apollo Bay, where we are staying both nights.
                Day two is the Otway treetop walk in the morning and the Twelve Apostles for
                sunset. Day three is a slow drive home through Colac, with a stop for the
                bakery you keep talking about.

                Money. The car hire came to $312 for the three days and the house in Apollo
                Bay is $540 for two nights. I have guessed $120 for fuel, and the treetop walk
                is $28 each. That is $1,084 all up, or $271 per person between the four of us.
                I have paid for the car and the house already, so could you transfer your $271
                to me by {nice(cal.trip_money_due)}? Same account as last time, and put your
                name in the reference so I can tell who has paid.

                Things to bring: a proper jacket, because Apollo Bay is cold at night even in
                spring, walking shoes for the Otways, swimmers if you are braver than me, and
                your licence. You and Nadia are the only two on the hire agreement, so you are
                sharing the driving. I will do the playlists, which I know is the harder job.

                One question for you. Mel is vegetarian and Nadia does not eat seafood, so I
                was going to book the pub in Apollo Bay for the first night instead of the fish
                place. Any objection? They need a deposit by {nice(cal.pub_deposit_due)}, so
                tell me before then.

                It is going to be great. Do not forget the jacket.
                """),
            closing="Josh",
            attachments=[("Great-Ocean-Road-plan.pdf", pdf, trip_itinerary(cal))],
        ),
        dict(
            file="personal-house-admin",
            sender=("Mia Fraser", "mia.fraser@example.com"),
            subject="House stuff: the inspection, bills and the lease",
            received=cal.received(3, 18, 5),
            unread=False,
            body=flow(f"""
                Hi both,

                Three bits of house admin, sorry in advance.

                The agent emailed to say the routine inspection is on {nice(cal.inspection)}
                between 10:00 am and 11:00 am. We do not have to be home, but the place has to
                look like adults live in it. Last time they wrote up the oven and the mould on
                the bathroom ceiling, and they will check both again, so those are the
                priorities.

                I have split the jobs so nobody gets all the bad ones:

                - Alex: the oven and stovetop, plus the back courtyard. The weeds are waist
                high and the bins need to go back behind the gate.
                - Tess: the bathroom, including the ceiling. There is mould spray under the
                sink.
                - Me: kitchen floors and cupboards, the living room, and the windows inside.

                Everyone does their own room. If we get it done by the night of
                {nice(cal.inspection - one_day)} we will not be scrubbing at 7:00 am.

                Bills. The electricity bill for the quarter came in at $186.40, which is $62.13
                each. Internet is the usual $25 each. So please send me $87.13 by
                {nice(cal.bills_due)} and I will pay both on the due date. The full bill is in
                the house folder if you want to check it.

                Last thing. The lease is up on 31 January, and the agent wants to know by the
                end of November whether we are renewing. The rent would go from $690 to $720 a
                week. I am happy to stay at that price if you two are, but tell me honestly,
                because if anyone wants out we need to start looking for a replacement soon.

                Can we talk about it over dinner on {nice(cal.house_dinner)}? I will cook.
                """),
            closing="Mia",
        ),
        dict(
            file="personal-trivia-night",
            sender=("Grace Liu", "grace.liu@example.com"),
            subject="Trivia night: we need a fourth, and it is your turn",
            received=cal.received(1, 19, 5),
            unread=True,
            body=flow(f"""
                Hey Alex,

                The Rose and Crown has brought trivia back, and Dev, Hana and I have a table
                booked for {nice(cal.trivia)}. We are one short, and after the way you carried
                us on the geography round last time, you are the obvious fourth.

                It starts at 7:30 pm sharp, and they collect the answer sheets at the end of
                each round, so being late costs points. I have booked the table from 6:45 pm so
                we can eat first. It is $10 each to play and that goes into the prize pool.
                First place is a $150 bar tab, second is $60, and last place gets a jar of
                pickled onions, which we have won twice and never opened.

                There are six rounds this time: general knowledge, music from the 2000s, flags
                and capitals, science, a picture round and a mystery round the host announces
                on the night. Hana has music, Dev thinks he has science, and I am useless at
                all of it but good at writing neatly. You would have flags and capitals,
                obviously.

                Two things I need from you. First, tell me by {nice(cal.trivia_reply_due)}
                whether you are in, because if you are not I have to ask my brother, and nobody
                wants that. Second, we still need a team name. Last time it was Les
                Quizerables and the host groaned, so the bar is low.

                I know you have exams coming, so no pressure if you would rather study. It will
                be over by 10:00 pm and the tram stops right outside, so you would be home
                before 11.

                Also, you still have my copy of Dune. Bring it, or I am keeping your umbrella.
                """),
            closing="Grace",
        ),
        dict(
            file="personal-futsal-semi-final",
            sender=("Ben Kowalski", "ben.kowalski@example.com"),
            subject="Semi-final: we need you in goal",
            received=cal.received(2, 21, 40),
            unread=False,
            body=flow(f"""
                Hi team,

                We made it. The 4-3 win last week put us third on the ladder, which means
                Northside Wanderers are in the semi-final for the first time in three seasons.
                It is on {nice(cal.semi_final)} at 6:10 pm on Court 2 at the Brunswick Indoor
                Sports Centre, against the Inbetweeners, who beat us 6-2 back in round four.

                Alex, this one is mostly for you. Jordan has rolled an ankle and is out, so you
                are our only goalkeeper. Can you confirm you can make it? If you cannot, I need
                to know by {nice(cal.fees_due)} so I can ask the league for a fill-in, and they
                want 48 hours of notice.

                Everyone else, please be there by 5:45 pm for a warm-up. We lost the first ten
                minutes last time because half of us were still putting on shin pads, and
                against this team we cannot give away an early goal. Wear the blue shirts. They
                wear white, so the grey away shirts are too close.

                Now the money. The semi-final costs the team $90 on top of the season fee,
                which is $15 each for the six of us playing. Four people also still owe the
                second half of the season fee, which is $45. I have paid the centre for all of
                it so that we could play, so please send me what you owe by
                {nice(cal.fees_due)}. I will post who has paid in the group chat, and I am not
                above naming names.

                If we win, the grand final is the following Sunday at 7:00 pm on Court 1, so
                keep that evening free. If we lose there is a playoff for third at 5:20 pm the
                same day, which nobody wants to play in.

                Afterwards we are going to the souvlaki place on Sydney Road whatever happens.
                Sam is injured and coming anyway, so bring your loudest friends.
                """),
            closing="Ben",
        ),

        # ---- Promotions -----------------------------------------------------
        dict(
            file="promo-coffee",
            sender=("Kettle & Bean Coffee Roasters", "hello@kettleandbean.example"),
            subject="Spring roast is here: 25% off every bag this week",
            received=cal.received(0, 6, 30),
            unread=True,
            # HTML only, as marketing mail often is. The reading pane shows the
            # text the preprocessor recovers from it, and the footer is dropped.
            html=coffee_newsletter(cal),
        ),
        dict(
            file="promo-outdoor",
            sender=("Trailhead Outdoor", "deals@trailhead-outdoor.example"),
            subject="Members' Weekend: up to 40% off tents, packs and jackets",
            received=cal.received(2, 7, 0),
            unread=False,
            body=flow(f"""
                Hi Alex,

                Members' Weekend is back. On {nice(cal.members_weekend)} and
                {nice(cal.members_weekend + one_day)}, Trailhead Rewards members get up to 40%
                off tents, packs, jackets and boots, in every store and online. Doors open at
                8:00 am on both days, an hour before the general public, and the online sale
                starts at 7:00 am on the Saturday.

                Here are the offers we expect to go first:

                - Ridgeline 2 hiking tent, 1.9 kg: $329, was $549
                - Altitude 65 litre pack with rain cover: $199, was $319
                - Stormline waterproof jacket, men's and women's: $179, was $299
                - Summit mid hiking boots: $159, was $249
                - All merino base layers: 30% off the marked price

                You will also earn double points on everything you buy across the weekend,
                including sale items, and points from this event can be spent from the
                following Monday. If you find the same item cheaper at another Australian
                retailer during the sale, show us and we will match the price on the spot.

                Not sure what you need for your next trip? Our staff run free pack-fitting
                sessions in store every half hour from 9:00 am, and the Melbourne city store is
                hosting a talk on walking the Great Ocean Walk at 2:00 pm on the Saturday.
                Seats are limited to 40, so arrive early.

                Click and collect is free and usually ready within two hours. Sale prices end
                when stores close at 5:00 pm on {nice(cal.members_weekend + one_day)}, and we
                cannot hold stock or offer rain checks on clearance lines.
                """),
            closing="See you on the trail,\nThe Trailhead Outdoor team\n\n"
                    "You are receiving this email because you are a Trailhead Rewards member. "
                    "To stop receiving member offers, update your preferences or unsubscribe at "
                    "https://trailhead-outdoor.example/preferences",
        ),
        dict(
            file="promo-bookshop",
            sender=("Pagewise Books", "news@pagewise.example"),
            subject="Exam season: 3 for 2 on every paperback this week",
            received=cal.received(1, 7, 30),
            unread=False,
            body=flow(f"""
                Hi Alex,

                Exams are close, and we have never met a student who did not buy a novel the
                week before one. So until {nice(cal.books_sale_ends)}, every paperback in the
                shop is 3 for 2: buy any three and the cheapest is free. It works in all eleven
                Pagewise stores and online, and it stacks with your student discount.

                A few that our booksellers keep pressing into people's hands:

                - The Salt Road, the new novel from the author of Low Tide: $22.99
                - A Field Guide to Getting Lost in the Suburbs, essays: $24.99
                - The Orchard at the End of the Line, shortlisted for the Whitlock Prize: $19.99
                - Slow Cooking for Fast Weeks, 90 dinners that mostly cook themselves: $34.99
                - Any title in the Pocket Classics range: $12.99 each

                Students get more than the offer. Show your student card in store, or add it to
                your account online, and you take a further 10% off everything, including
                stationery and study guides. Our exam packs are back as well: two notebooks, a
                set of highlighters, 200 flash cards and a pack of sticky tabs for $18, which
                is $11 less than buying them one at a time.

                Delivery is free on orders over $40 and usually takes two to four working days
                in Melbourne. Click and collect is ready within three hours at most stores, and
                you can return anything unread within 30 days.

                Our Carlton store is staying open until 9:00 pm on weeknights through the exam
                period, with free tea, a quiet table at the back and no obligation to buy
                anything at all.
                """),
            closing="Happy reading,\nThe Pagewise team\n\n"
                    "You are receiving this email because you joined Pagewise Rewards. "
                    "To stop receiving offers, update your preferences or unsubscribe at "
                    "https://pagewise.example/preferences",
        ),
        dict(
            file="promo-meal-kits",
            sender=("FreshCrate", "offers@freshcrate.example"),
            subject="50% off your first two boxes: dinner sorted for exam season",
            received=cal.received(4, 12, 10),
            unread=False,
            body=flow(f"""
                Hi Alex,

                When the calendar fills up, dinner is the first thing to go. FreshCrate sends
                you the ingredients for the week, measured out, with recipes that take 30
                minutes or less, and right now your first two boxes are half price.

                Here is the offer. Order by {nice(cal.mealkit_offer_ends)} with the code
                STUDY50 and you get 50% off your first box and 50% off your second. For the
                plan most students pick, three dinners for two people, that brings each of the
                first two boxes down from $69.90 to $34.95. Delivery is free on both.

                On the menu next week:

                - Honey soy chicken with sesame greens and rice, 25 minutes
                - One-pan chorizo and white bean stew, 30 minutes
                - Crispy tofu noodle bowls with peanut dressing, 20 minutes, vegan
                - Lemon and herb fish with roast potatoes, 30 minutes
                - Mushroom and spinach gnocchi, 15 minutes, vegetarian

                There are 24 recipes to choose from every week, including eight vegetarian and
                four vegan, and you can swap any of them until midnight on the Wednesday before
                your box arrives.

                There is no lock-in. Skip a week, pause for a month or cancel altogether from
                your account page, with nothing to pay as long as you do it five days before
                the next delivery. Boxes arrive chilled, in packaging that goes straight into
                the recycling bin, on a day and in a two-hour window that you choose.

                Living with housemates? The four-person plan works out at $8.70 a serve, which
                is less than most takeaway, and you can split the cost between cards at
                checkout.

                The half-price offer is for new customers and ends at midnight on
                {nice(cal.mealkit_offer_ends)}.
                """),
            closing="Enjoy,\nThe FreshCrate kitchen\n\n"
                    "You are receiving this email because you signed up at freshcrate.example. "
                    "To stop receiving offers, unsubscribe at https://freshcrate.example/unsubscribe",
        ),
    ]


# --- Writing the mailbox -----------------------------------------------------


def to_message(entry):
    message = EmailMessage()
    message["From"] = formataddr(entry["sender"])
    message["To"] = formataddr(READER)
    message["Subject"] = entry["subject"]
    message["Date"] = format_datetime(entry["received"])
    # Fixed, so an email keeps its id from one build to the next.
    domain = entry["sender"][1].split("@")[1]
    message["Message-ID"] = f"<demo-{entry['file']}@{domain}>"
    # Stands in for the IMAP Seen flag, as in the committed fixtures.
    message["X-Unread"] = "true" if entry["unread"] else "false"
    if "html" in entry:
        message.set_content(entry["html"], subtype="html")
    else:
        closing = entry.get("closing")
        message.set_content(entry["body"] + (f"\n\n{closing}" if closing else "") + "\n")
    for filename, (maintype, subtype), data in entry.get("attachments", ()):
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message


def build(out_dir, now):
    """Write the mailbox into `out_dir`, replacing a previous build. Returns
    the paths written, newest email first."""
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.startswith(PREFIX) and name.lower().endswith(".eml"):
            os.remove(os.path.join(out_dir, name))

    entries = sorted(emails(Calendar(now)), key=lambda entry: entry["received"], reverse=True)
    paths = []
    for number, entry in enumerate(entries, start=1):
        path = os.path.join(out_dir, f"{PREFIX}{number:02d}-{entry['file']}.eml")
        with open(path, "wb") as handle:
            handle.write(to_message(entry).as_bytes())
        paths.append(path)
    return paths


def report(paths):
    """Read the mailbox back the way the app will, and print what it found.

    False if a message would reach the reading pane short or empty.
    """
    try:
        sys.path.insert(0, _ROOT)
        from email import policy
        from email.parser import BytesParser

        from backend.adapters.headers import parse_message
        from backend.orchestrator.preprocess import preprocess_email
    except ImportError:
        print("  (backend not importable from here, so the mailbox was not read back)")
        return True

    healthy = True
    for path in paths:
        with open(path, "rb") as handle:
            parsed = parse_message(BytesParser(policy=policy.default).parse(handle))
        words = len(preprocess_email(parsed, 12000).text.split())
        files = ", ".join(a.filename for a in parsed.attachments) or "-"
        short = words < 150
        healthy = healthy and not short
        when = dt.datetime.fromisoformat(parsed.received_at).astimezone()
        print(f"  {when:%a %d %b %H:%M}  {words:>4} words  {parsed.sender_name[:26]:<26}  "
              f"{files}{'   <-- SHORT' if short else ''}")
    return healthy


def _shown(path):
    try:
        return os.path.relpath(path, _ROOT)
    except ValueError:              # another drive, on Windows
        return path


def main():
    parser = argparse.ArgumentParser(description="Build the demo mailbox.")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="Folder to write into (default: backend/demo_mailbox).")
    parser.add_argument("--today", metavar="YYYY-MM-DD",
                        help="Build the mailbox as it would look at the end of this day.")
    args = parser.parse_args()

    if args.today:
        try:
            day = dt.date.fromisoformat(args.today)
        except ValueError:
            raise SystemExit(f"--today wants a date like 2026-10-16, not {args.today!r}.")
        now = dt.datetime.combine(day, dt.time(23, 59)).astimezone()
    else:
        now = dt.datetime.now().astimezone()

    paths = build(args.out, now)
    print(f"Wrote {len(paths)} emails to {_shown(args.out)}, dated as of {nice(now.date())}:")
    healthy = report(paths)
    print("")
    print("To sign in to this mailbox, backend/.env needs these two lines:")
    print("    EMAIL_FIXTURE_DIR=backend/demo_mailbox")
    print("    EMAIL_INBOX_DIR=backend/demo_mailbox/received")
    print("and a login:  python -m backend.scripts.add_user demo@student.monash.edu <password>")
    print("Then restart the backend.")
    if not healthy:
        raise SystemExit("A message came out short once preprocessed; see the list above.")


if __name__ == "__main__":
    main()
