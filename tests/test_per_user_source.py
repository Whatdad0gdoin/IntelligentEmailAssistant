"""A real mailbox belongs to one account (GMAIL_OWNER).

EMAIL_SOURCE is a single global setting, so before this every login in
AUTH_USERS was shown whatever mailbox was configured. Once a real Gmail inbox
is connected that is a privacy failure, not a configuration quirk: a teammate
signing in to try the app would be reading someone's actual mail.

These tests pin the rule down: the owner gets the real mailbox, everybody else
gets the fixture mailbox, and leaving GMAIL_OWNER unset changes nothing.
"""

import pytest

from backend.adapters.email_source import (
    FixtureEmailSource,
    effective_source,
    get_email_source,
)
from backend.config import Config

OWNER = "dsmailkit@gmail.com"
OTHER = "someone.else@monash.edu"


@pytest.fixture
def gmail_config(monkeypatch, tmp_path, config):
    """A config with Gmail selected and an owner named."""
    monkeypatch.setenv("EMAIL_SOURCE", "gmail")
    monkeypatch.setenv("GMAIL_OWNER", OWNER)
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))
    return Config(require_llm=False)


# --- who gets what ---------------------------------------------------------


def test_the_owner_gets_the_real_mailbox(gmail_config):
    assert effective_source(gmail_config, OWNER) == "gmail"


def test_anyone_else_gets_the_fixture_mailbox(gmail_config):
    assert effective_source(gmail_config, OTHER) == "fixture"


def test_an_unauthenticated_caller_gets_the_fixture_mailbox(gmail_config):
    """No user is not the owner. Defaulting the other way would mean a missing
    argument silently handed out somebody's inbox."""
    assert effective_source(gmail_config, None) == "fixture"


@pytest.mark.parametrize("spelling", [OWNER.upper(), f"  {OWNER}  ", OWNER.title()])
def test_the_owner_match_ignores_case_and_padding(gmail_config, spelling):
    """Logins are compared the way the login route compares them."""
    assert effective_source(gmail_config, spelling) == "gmail"


def test_a_near_miss_is_not_the_owner(gmail_config):
    assert effective_source(gmail_config, "dsmailkit@gmail.com.evil.test") == "fixture"


# --- the factory honours it ------------------------------------------------


def test_a_non_owner_is_handed_a_fixture_source_object(gmail_config):
    """Not just the name: the object itself must be the fixture reader, and it
    must not be the cached Gmail instance."""
    assert isinstance(get_email_source(gmail_config, OTHER), FixtureEmailSource)


def test_the_owner_and_a_non_owner_get_different_instances(gmail_config, monkeypatch):
    """The source cache is keyed on the effective source, so one user's lookup
    cannot poison another's."""
    from backend.adapters import email_source as module

    class FakeGmail:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "backend.adapters.gmail_api_source.GmailApiSource", FakeGmail, raising=False
    )
    module._sources.clear()

    owner_source = get_email_source(gmail_config, OWNER)
    other_source = get_email_source(gmail_config, OTHER)
    assert owner_source is not other_source
    assert isinstance(other_source, FixtureEmailSource)


# --- the default is unchanged ---------------------------------------------


def test_without_an_owner_everyone_sees_the_configured_source(monkeypatch, tmp_path, config):
    """GMAIL_OWNER unset keeps the previous behaviour, which is what a
    fixture-only deployment and the rest of the suite rely on."""
    monkeypatch.setenv("EMAIL_SOURCE", "gmail")
    monkeypatch.delenv("GMAIL_OWNER", raising=False)
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))
    unrestricted = Config(require_llm=False)
    assert effective_source(unrestricted, OTHER) == "gmail"


def test_the_fixture_source_is_never_restricted(config):
    """Nothing to protect: the fixtures are demo data meant to be seen."""
    assert effective_source(config, OTHER) == "fixture"
    assert effective_source(config, None) == "fixture"


# --- the suite must not inherit the developer's .env -----------------------


def test_importing_backend_modules_does_not_load_the_env_file():
    """Importing a module must not mutate the process environment.

    backend/mailserver.py used to call load_dotenv() at module scope. Because
    tests/test_mailserver.py imports it, and pytest imports every test module
    before running anything, the whole suite ran against whatever was in the
    developer's backend/.env. It was invisible until GMAIL_OWNER was added
    there: two Gmail tests then failed in the full suite and passed on their
    own, which is the worst shape a bug can take.
    """
    import os
    import subprocess
    import sys

    probe = (
        "import os,sys;"
        "sys.path.insert(0, r'.');"
        "before = set(os.environ);"
        "import backend.mailserver;"      # the module that used to leak
        "import tests.test_mailserver;"   # and the test that imports it
        "leaked = sorted(set(os.environ) - before);"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, cwd=os.getcwd(),
    )
    assert result.returncode == 0, result.stderr
    leaked = [name for name in result.stdout.strip().split(",") if name]
    assert leaked == [], f"importing backend modules added env vars: {leaked}"
