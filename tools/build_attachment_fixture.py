"""Rebuild backend/adapters/fixtures/07-invoice-with-attachments.eml.

    python tools/build_attachment_fixture.py

The .eml is committed, so this does not need to run as part of anything. It
exists because that fixture contains a PDF, and a binary blob nobody can
regenerate is a liability in a repository that will be read by markers and
picked up again next semester. Running this reproduces the file byte for byte.

WHY THE PDF IS HAND-BUILT
-------------------------
Exporting one from Word would mean a 40 KB binary with an embedded font, a
creation timestamp and a producer string -- large, unreadable in a diff, and
different every time it is regenerated. The PDF written below is about 900
bytes of plain ASCII with a real text layer that `pypdf` genuinely has to
parse, so the extraction path is tested against a parser rather than a stub.

THE FIGURES MATTER
------------------
`NG-2291` and `5,335.00` appear only inside the PDF and nowhere in the email
body. tests/test_attachments.py relies on that to prove a summary quoting them
comes back grounded rather than flagged as an invented number -- the failure
that happens when attachment text reaches the prompt but not the grounding
source. Change these strings and that test changes meaning.

No image library is used: the PNG is assembled from a zlib-compressed scanline
block and the three chunks a decoder requires. It is a flat colour and nothing
ever looks at it -- image analysis is on request only and the suite never calls
a model -- so all that matters is that it is a well-formed image/png part.
"""

import os
import zlib
from email.message import EmailMessage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "backend", "adapters", "fixtures",
                   "07-invoice-with-attachments.eml")

INVOICE_LINES = [
    "NORTHGATE CONSULTING",
    "Tax Invoice NG-2291",
    "",
    "Issued: 12 September 2026",
    "Due: 26 September 2026",
    "",
    "Consulting services, August 2026      4,850.00",
    "GST                                     485.00",
    "Total due                             5,335.00",
    "",
    "Please remit to BSB 083-004 Account 55 912 3310.",
]

SCHEDULE = (
    "Milestone,Owner,Due,Status\n"
    "Requirements sign-off,D Robinson,2026-09-05,Complete\n"
    "Data pipeline,A Chen,2026-09-19,In progress\n"
    "Model evaluation,S Patel,2026-10-03,Not started\n"
    "Final report,D Robinson,2026-10-17,Not started\n"
)

BODY = (
    "Hi,\n\n"
    "Please find this month's invoice attached, along with the revised "
    "milestone schedule we agreed in Tuesday's catch-up.\n\n"
    "The payment terms have not changed. Let me know if anything in the "
    "schedule looks wrong before I circulate it to the wider team.\n\n"
    "Best regards,\n"
    "Accounts Team\n"
    "Northgate Consulting\n"
)


def minimal_pdf(lines):
    """A valid one-page PDF with a real text layer. Offsets are computed."""
    content = "BT /F1 11 Tf 72 720 Td 14 TL\n"
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content += f"({escaped}) Tj T*\n"
    content += "ET"
    stream = content.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def flat_png(width=48, height=48, colour=(40, 90, 160)):
    """A PNG of one colour, built from zlib and three chunks."""
    raw = b"".join(b"\x00" + bytes(colour * width) for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return (len(data).to_bytes(4, "big") + body
                + zlib.crc32(body).to_bytes(4, "big"))

    # 8-bit truecolour, no interlace.
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def build():
    message = EmailMessage()
    message["From"] = "Accounts <accounts@northgate.com.au>"
    message["To"] = "Student <student@monash.edu>"
    message["Subject"] = "Invoice NG-2291 and the updated milestone schedule"
    message["Date"] = "Mon, 14 Sep 2026 11:02:40 +1000"
    message["Message-ID"] = "<b4d7e118-work-007@northgate.com.au>"
    message["X-Unread"] = "true"
    message.set_content(BODY)

    message.add_attachment(minimal_pdf(INVOICE_LINES), maintype="application",
                           subtype="pdf", filename="invoice-NG-2291.pdf")
    message.add_attachment(SCHEDULE.encode("utf-8"), maintype="text",
                           subtype="csv", filename="milestone-schedule.csv")
    message.add_attachment(flat_png(), maintype="image", subtype="png",
                           filename="office-photo.png")

    # MIME boundaries are random by default, so without this the script would
    # produce a byte-different file on every run and the committed fixture
    # would show a spurious diff whenever anyone regenerated it. A boundary is
    # arbitrary text; pinning it costs nothing and makes the output stable.
    _pin_boundaries(message)
    return message


def _pin_boundaries(message, prefix="===============FIXTURE07", counter=None):
    """Replace every generated MIME boundary with a fixed one."""
    counter = counter if counter is not None else [0]
    if message.get_content_maintype() == "multipart":
        message.set_boundary(f"{prefix}{counter[0]}==")
        counter[0] += 1
        for part in message.get_payload():
            _pin_boundaries(part, prefix, counter)


if __name__ == "__main__":
    with open(OUT, "wb") as handle:
        handle.write(build().as_bytes())
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
