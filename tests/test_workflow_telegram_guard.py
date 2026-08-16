"""Every workflow step that talks to Telegram must honour TELEGRAM_ENABLED.

This exists because of a real gap. `TELEGRAM_ENABLED` was introduced as the one
flag that silences all outbound Telegram, and it does cover every *application*
path, because those funnel through `src.config.telegram_configured()`. But the
two alerting workflows end with a `if: failure()` step that POSTs to the
Telegram API with **raw curl** — no Python, no `telegram_configured()` — so the
switch did not reach them. Setting the flag to false silenced everything except
the "🔴 FAILED" messages, which is exactly the case the flag was set for.

A unit test cannot catch that: the offending code is YAML, not Python. So this
scans the workflow files as text and asserts that any step invoking the Telegram
API also mentions `TELEGRAM_ENABLED`.

Deliberately dependency-free (no PyYAML): CI installs only the two requirements
files, and PyYAML is in neither. It is importable locally as a transitive
dependency, which is precisely the kind of thing that passes here and fails in
CI.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# A step starts at `      - ` (six spaces, dash, space) inside `steps:`.
_STEP_SPLIT = re.compile(r"^ {6}- ", re.MULTILINE)

TELEGRAM_API = "api.telegram.org"

# Steps that legitimately call Telegram, as (workflow, step-name fragment).
# Asserted to be exactly what we find, so a NEW unguarded step fails the test
# rather than silently joining the crowd.
EXPECTED = {
    ("daily_harvest.yml", "Telegram token preflight"),
    ("daily_harvest.yml", "Notify on failure"),
    ("riskguard_premarket.yml", "Telegram token preflight"),
    ("riskguard_premarket.yml", "Notify on failure"),
    # db_backup.yml was found by this test, not by hand: it alerts on the same
    # channel but was never listed alongside the two "alerting workflows", so it
    # was missed twice -- once by the kill switch, once by the fix for it.
    ("db_backup.yml", "Notify on failure"),
}


def _strip_comments(block: str) -> str:
    """Drop whole-line YAML/shell comments.

    Without this the checks below can be satisfied by a comment that merely
    *mentions* TELEGRAM_ENABLED -- which is not a guard. Caught by deleting a
    real guard and watching this file still pass.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )


def _telegram_steps() -> list[tuple[str, str, str]]:
    """Return (workflow_filename, step_name, step_code) for Telegram-calling steps.

    `step_code` has comments stripped, so every assertion is about code.
    """
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for block in _STEP_SPLIT.split(path.read_text(encoding="utf-8")):
            if TELEGRAM_API not in block:
                continue
            name_match = re.match(r"name:\s*(.+)", block)
            name = name_match.group(1).strip() if name_match else "<unnamed step>"
            found.append((path.name, name, _strip_comments(block)))
    return found


def test_step_splitting_actually_found_the_telegram_steps():
    """Guard against a vacuous pass.

    If the regex stops matching -- indentation changes, steps get restructured --
    every assertion below would pass over an empty list and report success while
    the workflows were wide open. Pin the exact set instead.
    """
    found = {(wf, name) for wf, name, _ in _telegram_steps()}
    assert found == EXPECTED, (
        "the set of workflow steps calling the Telegram API changed.\n"
        f"  expected: {sorted(EXPECTED)}\n"
        f"  found:    {sorted(found)}\n"
        "If you added a step, add it to EXPECTED *and* make sure it honours "
        "TELEGRAM_ENABLED."
    )


def test_every_telegram_step_honours_the_kill_switch():
    unguarded = [
        f"{wf}: {name}"
        for wf, name, body in _telegram_steps()
        if "TELEGRAM_ENABLED" not in body
    ]
    assert not unguarded, (
        "these workflow steps call the Telegram API without checking "
        "TELEGRAM_ENABLED, so switching Telegram off will not silence them:\n  "
        + "\n  ".join(unguarded)
    )


def test_guard_accepts_the_same_values_as_the_application():
    """`src.config.telegram_enabled()` accepts false/0/no/off, case-insensitively.

    A workflow that only tested for `false` would still alert for someone who
    set `off` -- the same class of bug this file exists to prevent, one level
    down.
    """
    for wf, name, body in _telegram_steps():
        if "Notify on failure" not in name:
            continue
        # `${VAR,,}` is bash lowercasing; without it `False` slips through.
        assert "${TELEGRAM_ENABLED,,}" in body, (
            f"{wf}: {name} compares TELEGRAM_ENABLED without lowercasing it"
        )
        for value in ("false", "0", "no", "off"):
            assert value in body, (
                f"{wf}: {name} does not treat {value!r} as off, but "
                "src.config.telegram_enabled() does"
            )
