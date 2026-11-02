"""Build the Moodle code-submission ZIP (all project files, no secrets).

    python tools/make_submission_zip.py
    python tools/make_submission_zip.py --out C:/Users/me/Downloads/DS25.zip

Packs every file git tracks plus any new file git does not ignore, under one
top-level folder. Whatever .gitignore excludes stays out, which is exactly
what must not be archived: backend/.env (the OpenAI key and JWT secret),
backend/secrets/ (OAuth client, Gmail tokens, the accounts database),
node_modules/, build output, caches, raw Enron downloads and any mail received
by the local mail server. The database requirement is met by
database/accounts_schema.sql, a schema-only dump.

Before writing, every file is scanned for anything shaped like an API key,
OAuth refresh token or private key, and the build stops if one is found.
"""

import argparse
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = "MailKit_DS25_FIT3164"
LIMIT_BYTES = 500 * 1024 * 1024   # Moodle's upload limit

_SECRETS = {
    "OpenAI key": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Anthropic key": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "OAuth refresh token": re.compile(rb"1//0[A-Za-z0-9_-]{30,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
}
_NEVER = re.compile(r"(^|/)\.env$|(^|/)secrets/(?!README\.txt$)|\.db$|(^|/)node_modules/|(^|/)mailbox/")

# In the repository, but not needed for the unit: the team's review sheets and
# their hidden answer keys (working files, rebuilt by eval/human_checks.py;
# only their *_result.json scores are evidence), the team's internal to-do list
# (FIXES.md), and this script itself.
_NOT_FOR_THE_UNIT = re.compile(r"^eval/data/human_checks/(?!.*_result\.json$)|^tools/make_submission_zip\.py$|^FIXES\.md$")


def project_files():
    """Tracked files plus untracked ones git does not ignore."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return sorted({p for p in out.split("\0") if p and os.path.isfile(os.path.join(ROOT, p))})


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Downloads",
                                                      "DS25_MailKit_source_code.zip"))
    args = parser.parse_args()

    files = [p for p in project_files() if not _NOT_FOR_THE_UNIT.search(p)]
    blocked = [p for p in files if _NEVER.search(p)]
    leaks = []
    for path in files:
        data = open(os.path.join(ROOT, path), "rb").read()
        leaks += [(path, label) for label, rx in _SECRETS.items() if rx.search(data)]
    if blocked or leaks:
        for path in blocked:
            print(f"  must not be archived: {path}")
        for path, label in leaks:
            print(f"  looks like a {label}: {path}")
        sys.exit("Stopped: nothing was written.")

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(os.path.join(ROOT, path), f"{FOLDER}/{path}")

    size = os.path.getsize(args.out)
    print(f"{len(files)} files -> {args.out}  ({size / 1e6:.1f} MB)")
    if size > LIMIT_BYTES:
        sys.exit("Over Moodle's 500 MB limit.")


if __name__ == "__main__":
    main()
