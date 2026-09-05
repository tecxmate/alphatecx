"""Every writer of `daily_digest` must agree with `sql/006_digests.sql`.

WHY THIS EXISTS. `src/cron/thesis_status.py` inserted into a column named
`inputs` — the schema calls it `source_inputs` — and omitted `title`, which is
NOT NULL with no default. Both were wrong from the day it was written, and both
were invisible for months because the workflow step is `continue-on-error`: the
Telegram message went out, the digest row silently never landed, and the run
stayed green. It surfaced only once the harvest was made to fail honestly
(2026-09-01) and someone read the log.

`src/cron/brief.py` writes the same table correctly. The bug was one writer
drifting from another with nothing comparing them — the same shape as
`sc_capabilities` drifting from the tool registry, and it wants the same fix: a
test that reads BOTH sides rather than a comment asking people to be careful.

The schema is parsed from the migration rather than hardcoded here, so a future
`ALTER TABLE` cannot leave this test asserting a table that no longer exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "sql" / "006_digests.sql"

# Every module that writes daily_digest. A new one must be added here — which is
# the point: the list is short and the failure mode is expensive.
WRITERS = [
    ROOT / "src" / "cron" / "brief.py",
    ROOT / "src" / "cron" / "thesis_status.py",
]


def _schema_columns() -> dict[str, dict]:
    """{column: {"not_null": bool, "has_default": bool}} for daily_digest."""
    text = SCHEMA.read_text()
    body = re.search(
        r"CREATE TABLE IF NOT EXISTS daily_digest\s*\((.*?)\n\);",
        text, re.S,
    )
    assert body, "could not locate the daily_digest DDL"

    cols: dict[str, dict] = {}
    for raw in body.group(1).splitlines():
        line = raw.split("--")[0].strip().rstrip(",")
        if not line:
            continue
        # Skip table-level constraints, which are not columns.
        if re.match(r"(?i)^(primary key|foreign key|unique|constraint|check)\b", line):
            continue
        name = line.split()[0]
        if not re.match(r"^[a-z_][a-z0-9_]*$", name):
            continue
        cols[name] = {
            "not_null": "NOT NULL" in line.upper(),
            "has_default": "DEFAULT" in line.upper(),
        }
    return cols


def _insert_columns(path: Path) -> list[tuple[Path, list[str]]]:
    """Column lists from every `INSERT INTO daily_digest (...)` in a file."""
    text = path.read_text()
    out = []
    for m in re.finditer(
        r"INSERT\s+INTO\s+daily_digest\s*\(([^)]*)\)", text, re.I | re.S
    ):
        cols = [c.strip() for c in m.group(1).split(",") if c.strip()]
        out.append((path, cols))
    return out


@pytest.fixture(scope="module")
def schema():
    return _schema_columns()


def test_the_schema_parses_at_all(schema):
    """Guards the guard: a parser that silently matched nothing would make
    every assertion below vacuously true."""
    assert {"digest_date", "kind", "title", "body", "source_inputs"} <= set(schema)
    assert schema["title"]["not_null"] and not schema["title"]["has_default"]


def test_there_is_at_least_one_writer_to_check():
    found = [w for w in WRITERS for _ in _insert_columns(w)]
    assert found, "no INSERT INTO daily_digest found — did a writer move?"


@pytest.mark.parametrize("writer", WRITERS, ids=lambda p: p.name)
def test_every_inserted_column_exists_in_the_schema(writer, schema):
    """The `inputs` vs `source_inputs` bug."""
    for path, cols in _insert_columns(writer):
        unknown = [c for c in cols if c not in schema]
        assert not unknown, (
            f"{path.name} inserts into daily_digest column(s) that do not "
            f"exist: {unknown}. Schema has: {sorted(schema)}"
        )


@pytest.mark.parametrize("writer", WRITERS, ids=lambda p: p.name)
def test_every_required_column_is_supplied(writer, schema):
    """The missing-`title` bug. NOT NULL with no default means the INSERT
    raises unless the writer names it."""
    required = {
        c for c, m in schema.items()
        if m["not_null"] and not m["has_default"]
    }
    for path, cols in _insert_columns(writer):
        missing = sorted(required - set(cols))
        assert not missing, (
            f"{path.name} omits NOT NULL column(s) with no default: {missing}"
        )


@pytest.mark.parametrize("writer", WRITERS, ids=lambda p: p.name)
def test_no_writer_repeats_a_column(writer):
    for path, cols in _insert_columns(writer):
        assert len(cols) == len(set(cols)), f"{path.name} repeats a column: {cols}"


def test_thesis_status_specifically_now_writes_a_row(schema):
    """The regression that started this. Kept as a named case so the failure
    reads as 'the thesis heartbeat is broken again' rather than a parametrised
    id nobody recognises."""
    (_p, cols), = _insert_columns(ROOT / "src" / "cron" / "thesis_status.py")
    assert "source_inputs" in cols and "inputs" not in cols
    assert "title" in cols


class TestStaticPngIsBestEffort:
    """`src/quant/correlation_snapshot.py` writes three artefacts in order:
    graph_snapshot.json, graph-image.png, graph-view.html.

    From the plotly>=6 upgrade until 2026-09-05 the PNG raised on every nightly
    run (kaleido 0.2.1 against a plotly that requires >=1). Because it sat
    BETWEEN the other two, it took graph-view.html down with it — the JSON kept
    updating while the interactive viewer silently froze. The version conflict
    is fixed; this pins the ordering hazard so the next renderer problem costs
    only the image.
    """

    def _mod(self):
        # The module reads os.environ["DATABASE_URL"] at import time — a
        # deliberate fail-fast for a harvester entrypoint, and the reason it had
        # no tests until now. Satisfy it rather than weakening it; nothing here
        # opens a connection.
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/t")
        from src.quant import correlation_snapshot
        return correlation_snapshot

    def test_a_render_failure_returns_false_instead_of_raising(self, tmp_path):
        from unittest import mock
        snap = self._mod()
        with mock.patch.object(
            snap, "build_combined_png", side_effect=RuntimeError("no Chrome")
        ):
            assert snap.write_png_best_effort(
                tmp_path / "graph-image.png", {}, None, []
            ) is False

    def test_an_empty_error_message_does_not_itself_raise(self, tmp_path):
        """The real kaleido error starts with a blank line; formatting it with
        `.splitlines()[0]` on an empty string would IndexError inside the
        handler — turning a soft failure back into a hard one."""
        from unittest import mock
        snap = self._mod()
        with mock.patch.object(
            snap, "build_combined_png", side_effect=RuntimeError("")
        ):
            assert snap.write_png_best_effort(
                tmp_path / "graph-image.png", {}, None, []
            ) is False

    def test_a_successful_render_writes_the_file_and_returns_true(self, tmp_path):
        from unittest import mock
        snap = self._mod()
        out = tmp_path / "graph-image.png"
        with mock.patch.object(snap, "build_combined_png", return_value=b"PNGDATA"):
            assert snap.write_png_best_effort(out, {}, None, []) is True
        assert out.read_bytes() == b"PNGDATA"

    def test_the_html_write_happens_after_the_png_in_main(self):
        """Ordering is the whole point — if the HTML ever moves above the PNG
        this test is what says so."""
        import inspect
        src = inspect.getsource(self._mod().main)
        assert src.index("write_png_best_effort") < src.index("out_html")


class TestKaleidoPinMatchesPlotly:
    def test_requirements_no_longer_pin_the_incompatible_kaleido(self):
        """plotly>=6 raises 'requires the Kaleido package, v1.0.0 or greater'
        against kaleido 0.2.1. The pin and the library have to agree."""
        req = (ROOT / "requirements.txt").read_text()
        assert "kaleido==0.2.1" not in req
        assert "kaleido>=1" in req


class TestDashboardPushAnnouncesItsOwnFailure:
    """The push step is `continue-on-error`, so a failure there does not redden
    the run. Branch protection has been rejecting it since 2026-08-16 and the
    dashboards silently froze; the runs happened to be red for an unrelated
    reason, which hid it. Once that reason is fixed the run goes green while the
    console keeps serving stale pages — so the step has to say so itself.
    """

    def _step(self) -> str:
        wf = (ROOT / ".github" / "workflows" / "daily_harvest.yml").read_text()
        start = wf.index("Commit & push refreshed snapshot")
        end = wf.index("- name:", wf.index("run: |", start))
        return wf[start:end]

    def test_a_rejected_push_emits_a_visible_warning_annotation(self):
        step = self._step()
        assert "::warning" in step, (
            "a silent failure inside a continue-on-error step is invisible"
        )

    def test_the_branch_protection_rejection_is_recognised_by_name(self):
        """GH013 is what the server actually returns. Matching only on generic
        words would let the specific, actionable message go unprinted."""
        step = self._step()
        assert "GH013" in step or "repository rule violations" in step

    def test_the_warning_says_the_dashboards_are_stale(self):
        """The annotation has to name the CONSEQUENCE — nobody acts on
        'push failed', they act on 'the pages people look at are old'."""
        step = self._step().upper()
        assert "STALE" in step or "FROZEN" in step

    def test_a_no_change_day_still_exits_quietly(self):
        """Weekends and holidays produce no diff and must not warn."""
        step = self._step()
        assert "no static-asset changes to commit" in step
