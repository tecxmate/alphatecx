"""Macro series harvest (src/harvester/macro.py).

These tests drive the PURE parsers over captured payloads. That is not a
stylistic choice: this container's egress is a GitHub/PyPI allowlist that
blocks Yahoo, FRED and www.twse.com.tw alike — the repo's own production
sources are unreachable here too — so the fetch path cannot be exercised where
the code is written. Everything that can be verified offline, is.

The payload shapes below are real Yahoo v8 / FRED CSV structures, including
their two nastiest properties: nulls for no-print sessions, and FRED's literal
'.' placeholder.
"""

from __future__ import annotations

import pytest

from src.harvester import macro


def _yahoo(stamps, closes):
    return {"chart": {"result": [{
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}]},
    }]}}


class TestParseYahoo:
    # 2026-08-27..2026-08-31, 09:30 EDT bars
    STAMPS = [1787836200, 1787922600, 1788009000, 1788095400, 1788183000]

    def test_rows_carry_series_source_and_pct(self):
        rows = macro.parse_yahoo_chart(
            _yahoo(self.STAMPS, [100.0, 101.0, 102.0, 103.0, 104.0]), "sox")
        assert len(rows) == 5
        assert {r["series"] for r in rows} == {"sox"}
        assert {r["source"] for r in rows} == {"yahoo_chart_v8"}
        assert rows[0]["prev_close"] is None          # nothing before the first bar
        assert rows[0]["pct_change"] is None
        assert rows[1]["prev_close"] == 100.0
        assert rows[1]["pct_change"] == 1.0

    def test_dates_are_utc_session_dates_not_taipei(self):
        """A US close stamped with a Taipei date lands a day ahead and silently
        misaligns every join against a Taiwan trading date."""
        rows = macro.parse_yahoo_chart(_yahoo([1788183000], [104.0]), "sox")
        assert rows[0]["date"] == "2026-08-31"

    def test_null_closes_are_dropped_not_forward_filled(self):
        """A null is 'no data'. Inventing a flat day shows up downstream as a
        real 0.00% move, which is worse than a gap."""
        rows = macro.parse_yahoo_chart(
            _yahoo(self.STAMPS[:3], [100.0, None, 102.0]), "sox")
        assert len(rows) == 2
        # pct is computed against the previous PRESENT bar, not the dropped one
        assert rows[1]["prev_close"] == 100.0
        assert rows[1]["pct_change"] == 2.0

    def test_empty_and_malformed_payloads_return_no_rows(self):
        for payload in ({}, {"chart": {}}, {"chart": {"result": []}},
                        _yahoo([], []), {"chart": {"result": [{}]}}):
            assert macro.parse_yahoo_chart(payload, "sox") == []

    def test_mismatched_array_lengths_do_not_raise(self):
        """Yahoo has been observed returning ragged arrays; zip(strict=False)
        must truncate rather than explode mid-harvest."""
        rows = macro.parse_yahoo_chart(_yahoo(self.STAMPS, [100.0, 101.0]), "sox")
        assert len(rows) == 2


class TestParseFred:
    CSV = (
        "observation_date,DGS10\n"
        "2026-08-27,4.639\n"
        "2026-08-28,4.664\n"
        "2026-08-31,4.758\n"
    )

    def test_parses_dated_values(self):
        rows = macro.parse_fred_csv(self.CSV, "us10y")
        assert len(rows) == 3
        assert rows[-1]["date"] == "2026-08-31"
        assert rows[-1]["close"] == 4.758
        assert rows[-1]["source"] == "fred_csv"
        assert rows[0]["prev_close"] is None

    def test_dot_placeholder_is_skipped_not_crashed_on(self):
        """FRED writes '.' for a US holiday. float('.') raises."""
        rows = macro.parse_fred_csv(
            "observation_date,DGS10\n2026-08-27,4.639\n2026-08-28,.\n2026-08-31,4.758\n",
            "us10y")
        assert [r["date"] for r in rows] == ["2026-08-27", "2026-08-31"]
        assert rows[1]["prev_close"] == 4.639

    def test_empty_and_headerless_input(self):
        assert macro.parse_fred_csv("", "us10y") == []
        assert macro.parse_fred_csv("observation_date\n2026-08-27\n", "us10y") == []

    def test_yield_pct_change_is_relative_not_basis_points(self):
        """4.639 -> 4.758 is +2.57% relative. Anyone wanting bps must subtract
        the levels themselves; this column is uniform across all five series."""
        rows = macro.parse_fred_csv(self.CSV, "us10y")
        assert rows[-1]["pct_change"] == round((4.758 / 4.664 - 1) * 100, 4)


class TestSeriesRegistry:
    def test_every_series_has_exactly_one_vendor(self):
        overlap = set(macro.YAHOO_SERIES) & set(macro.FRED_SERIES)
        assert not overlap, f"series claimed by two vendors: {overlap}"

    def test_all_series_matches_the_tool_and_the_schema(self):
        """The MCP tool advertises a series list; it must match the harvester's.

        A tool promising a series nothing writes is the same class of lie as a
        capabilities entry for a tool that does not exist.
        """
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        import index
        assert set(index._MACRO_SERIES) == set(macro.ALL_SERIES)

    def test_us10y_is_deliberately_not_on_yahoo(self):
        """Two vendors is the hedge: a Yahoo outage costs every series but this one."""
        assert "us10y" in macro.FRED_SERIES
        assert "us10y" not in macro.YAHOO_SERIES


class TestFetchSeriesErrorHandling:
    @pytest.fixture(autouse=True)
    def _no_pacing(self, monkeypatch):
        """fetch_series paces its Yahoo calls (see YAHOO_REQUEST_DELAY). Real
        for the nightly run, pure latency here."""
        monkeypatch.setattr(macro, "YAHOO_REQUEST_DELAY", 0)

    def test_partial_failure_returns_rows_and_errors_not_an_exception(self, monkeypatch):
        """One 429 must not cost the other ten series."""
        calls = []

        def fake_get(url):
            calls.append(url)
            if "TSM" in url:
                raise OSError("429 Too Many Requests")
            class R:
                @staticmethod
                def json():
                    return _yahoo([1788183000], [104.0])
                text = "observation_date,DGS10\n2026-08-31,4.758\n"
            return R()

        monkeypatch.setattr(macro, "_get", fake_get)
        rows, errors = macro.fetch_series(days=2)

        assert any(r["series"] == "sox" for r in rows)
        assert any(r["series"] == "us10y" for r in rows)
        assert not any(r["series"] == "tsm_adr" for r in rows)
        assert len(errors) == 1 and "tsm_adr" in errors[0]

    def test_total_failure_is_empty_rows_plus_one_error_per_series(self, monkeypatch):
        monkeypatch.setattr(macro, "_get",
                            lambda url: (_ for _ in ()).throw(OSError("blocked")))
        rows, errors = macro.fetch_series()
        assert rows == []
        assert len(errors) == len(macro.ALL_SERIES)


class TestBriefMacroBlock:
    """The pre-market brief's macro line.

    The property that matters: the brief predates macro and must keep sending
    when the table is empty, absent (migration not yet applied in production),
    or unreadable. A macro outage must never cost the whole brief.
    """

    def _block(self, rows=None, raises=None):
        from unittest import mock

        import src.cron.brief as brief

        class FakeCur:
            def execute(self, *a, **k): 
                if raises:
                    raise raises
            def fetchall(self): return rows or []
            def __enter__(self): return self
            def __exit__(self, *a): return False

        from contextlib import contextmanager
        @contextmanager
        def fake_cur():
            if raises:
                raise raises
            yield FakeCur()

        with mock.patch.object(brief, "cur", fake_cur):
            return brief._macro_block()

    def test_renders_every_series_with_direction(self):
        block = self._block(rows=[
            ("dxy", "2026-08-31", 99.513, -0.27),
            ("sox", "2026-08-31", 11535.05, -0.45),
            ("tsm_adr", "2026-08-31", 415.32, -0.5),
            ("us10y", "2026-08-31", 4.758, 2.02),
            ("usdtwd", "2026-08-31", 31.65, 0.12),
        ])
        assert "SOX 11,535.05" in block and "▼0.45%" in block
        assert "US 10Y 4.758" in block and "▲2.02%" in block
        assert "USD/TWD 31.650" in block   # FX quoted to 3dp
        assert "2026-08-31" in block

    def test_missing_table_returns_empty_string_not_an_exception(self):
        """Migration not applied in production is the LIKELY case on day one."""
        assert self._block(raises=RuntimeError('relation "raw_macro" does not exist')) == ""

    def test_empty_table_returns_empty_string(self):
        assert self._block(rows=[]) == ""

    def test_null_pct_renders_the_level_without_a_fake_arrow(self):
        block = self._block(rows=[("sox", "2026-08-31", 11535.05, None)])
        assert "SOX 11,535.05" in block
        assert "▲" not in block and "▼" not in block

    def test_partial_series_renders_what_exists(self):
        block = self._block(rows=[("sox", "2026-08-31", 11535.05, -0.45)])
        assert "SOX" in block and "DXY" not in block


class TestHarvestExitCode:
    """`main()` must report failure, without undoing failure isolation.

    Until 2026-09-01 main() discarded harvest_today()'s return, so a harvest
    that failed every step still exited 0 — green Actions run, green cron,
    no failure alert. The per-step ingestion_log rows were the only trace.
    """

    def _main_with(self, results):
        from unittest import mock

        import src.harvester.daily as daily
        with mock.patch.object(daily, "harvest_today", return_value=results):
            return daily.main()

    def test_clean_run_exits_zero(self):
        assert self._main_with({"t86": 900, "errors": []}) == 0

    def test_any_failed_step_exits_non_zero(self):
        assert self._main_with({"t86": 900, "errors": ["macro: blocked"]}) == 1

    def test_several_failures_still_exit_one(self):
        assert self._main_with({"errors": ["a: x", "b: y", "c: z"]}) == 1

    def test_missing_errors_key_is_treated_as_success(self):
        """Defensive: a results dict without 'errors' must not crash the
        process wrapper on its way to reporting an exit code."""
        assert self._main_with({"t86": 900}) == 0

    def test_partial_success_still_reports_failure(self):
        """The chosen trade, pinned so nobody 'fixes' it later by accident:
        data landing for other steps does NOT make the run green."""
        assert self._main_with({"t86": 900, "indices": 40,
                                "errors": ["macro: 403"]}) == 1


class TestHarvestFailureIsDeferredNotAmputating:
    """The harvest may fail the RUN, but must never skip Risk Guard.

    `src.harvester.daily` now exits non-zero when a sub-step failed. A bare
    failing step in daily_harvest.yml would stop the job — and the very next
    step is the Risk Guard post-close pipeline, which that file itself marks
    "NOT continue-on-error: a silent failure there is a stop-loss alert that
    never fired". So the failure is absorbed at the harvest step and re-raised
    by a verdict step at the end.

    Scanned as text rather than with PyYAML: CI installs neither requirements
    file with PyYAML, and a test that only passes locally is worse than none
    (see tests/test_workflow_telegram_guard.py).
    """

    import pathlib
    WF = (pathlib.Path(__file__).resolve().parent.parent
          / ".github" / "workflows" / "daily_harvest.yml")

    def _text(self):
        return self.WF.read_text(encoding="utf-8")

    def test_harvest_step_absorbs_its_own_failure(self):
        text = self._text()
        i = text.index("- name: Run daily harvest")
        j = text.index("- name: Generate post-close brief")
        step = text[i:j]
        assert "continue-on-error: true" in step, (
            "the harvest step must absorb its failure, or a failing harvest "
            "stops the job and Risk Guard never runs"
        )
        assert "id: harvest" in step, "the verdict step needs this id"

    def test_a_verdict_step_re_raises_the_failure(self):
        text = self._text()
        assert "- name: Harvest verdict" in text
        i = text.index("- name: Harvest verdict")
        assert "steps.harvest.outcome != 'success'" in text[i:i + 800], (
            "the verdict must read `outcome`, not `conclusion` — "
            "continue-on-error rewrites conclusion to success"
        )

    def test_the_verdict_comes_after_risk_guard(self):
        """Order is the whole point. A verdict before Risk Guard would be the
        bare failing step this indirection exists to avoid."""
        text = self._text()
        assert text.index("- name: Risk Guard post-close pipeline") < \
               text.index("- name: Harvest verdict")

    def test_the_verdict_comes_before_notify_on_failure(self):
        """`Notify on failure` runs `if: failure()`, so the verdict must have
        already failed the job for the alert to fire."""
        text = self._text()
        assert text.index("- name: Harvest verdict") < \
               text.index("- name: Notify on failure")

    def test_zeabur_chain_does_not_abort_before_risk_guard(self):
        import pathlib
        chain = (pathlib.Path(__file__).resolve().parent.parent
                 / "deploy" / "daily-chain.sh").read_text(encoding="utf-8")
        assert "soft python -m src.harvester.daily" in chain, (
            "`hard` would abort the chain before riskguard.pipeline"
        )
        assert "hard python -m riskguard.pipeline" in chain, (
            "Risk Guard itself should stay hard — its failure IS fatal"
        )


class TestBriefSeparatesOvernightFromRegional(TestBriefMacroBlock):
    """The pre-market brief goes out at 08:30 Taipei.

    By then the US and Europe have CLOSED — genuinely overnight, and able to
    inform today's open. Tokyo, Seoul, Shanghai and Hong Kong have NOT OPENED,
    so their newest stored row is a previous close, exactly as old as Taiwan's
    own. Both are worth reading. Putting them on one line under 隔夜 would
    assert the regional closes are overnight news about today.
    """

    ALL = [
        ("sox", "2026-08-31", 11535.05, -0.45),
        ("estoxx50", "2026-08-31", 5420.1, 0.22),
        ("kospi", "2026-08-31", 3210.4, 0.80),
        ("nikkei", "2026-08-31", 42100.0, 0.30),
        ("hangseng", "2026-08-31", 25330.0, -0.10),
    ]

    def test_the_overnight_line_never_carries_a_same_session_market(self):
        block = self._block(rows=self.ALL)
        overnight = [ln for ln in block.splitlines() if "隔夜" in ln]
        assert len(overnight) == 1
        for label in ("KOSPI", "Nikkei", "Hang Seng"):
            assert label not in overnight[0], (
                f"{label} trades alongside Taipei and must not be called 隔夜"
            )

    def test_the_regional_line_says_the_market_has_not_opened_yet(self):
        block = self._block(rows=self.ALL)
        regional = [ln for ln in block.splitlines() if "亞洲" in ln]
        assert len(regional) == 1
        assert "KOSPI 3,210.40" in regional[0] and "Nikkei" in regional[0]
        assert "尚未開盤" in regional[0]

    def test_europe_counts_as_overnight_because_it_closes_before_the_open(self):
        block = self._block(rows=self.ALL)
        overnight = next(ln for ln in block.splitlines() if "隔夜" in ln)
        assert "Euro Stoxx 50 5,420.10" in overnight

    def test_only_overnight_data_emits_only_the_overnight_line(self):
        block = self._block(rows=[("sox", "2026-08-31", 11535.05, -0.45)])
        assert "隔夜" in block and "亞洲" not in block

    def test_only_regional_data_emits_only_the_regional_line(self):
        """Plausible in production: Yahoo serving Asia while the US feed 429s."""
        block = self._block(rows=[("kospi", "2026-08-31", 3210.4, 0.8)])
        assert "亞洲" in block and "隔夜" not in block

    def test_still_empty_when_the_table_is(self):
        assert self._block(rows=[]) == ""


class TestGlobalMarketCoverage:
    """Japan / Korea / China / Europe joined the table on 2026-09-01.

    The additions are cheap; the CLASSIFICATION is what these tests defend.
    """

    def test_every_requested_market_is_actually_covered(self):
        for market in ("us", "europe", "japan", "korea", "china", "hong_kong"):
            assert macro.series_in_market(market), f"{market} has no series"

    def test_the_asian_peers_trade_alongside_taipei_not_before_it(self):
        """THE invariant of this change.

        Tokyo, Seoul, Shanghai and Hong Kong are open at the same time as the
        TWSE. Classifying one of them `before_open` would license the brief and
        the model to call a live, still-moving index "overnight" — a false
        statement about the world, not a formatting slip.
        """
        for key in ("nikkei", "kospi", "shanghai", "hangseng"):
            assert macro.SERIES_META[key]["when_known"] == macro.SAME_SESSION, (
                f"{key} trades during the Taipei session and cannot be "
                f"'known before the open'"
            )

    def test_us_and_europe_had_closed_before_taipei_opened(self):
        for key in ("sox", "nasdaq", "tsm_adr", "us10y", "estoxx50"):
            assert macro.SERIES_META[key]["when_known"] == macro.BEFORE_OPEN

    def test_before_open_series_excludes_every_same_session_market(self):
        before = set(macro.before_open_series())
        assert before.isdisjoint({"nikkei", "kospi", "shanghai", "hangseng"})
        assert {"sox", "estoxx50"} <= before

    def test_unknown_market_is_empty_not_an_exception(self):
        assert macro.series_in_market("mars") == []
        assert macro.series_in_market("") == []

    def test_market_lookup_is_case_and_space_tolerant(self):
        assert macro.series_in_market("  Korea ") == ["kospi"]

    def test_every_series_carries_a_complete_metadata_row(self):
        for key, meta in macro.SERIES_META.items():
            for field in ("symbol", "vendor", "market", "label", "when_known"):
                assert meta.get(field), f"{key} is missing {field}"
            assert meta["when_known"] in (macro.BEFORE_OPEN, macro.SAME_SESSION)
            assert meta["vendor"] in ("yahoo", "fred")

    def test_vendor_maps_are_derived_from_the_metadata_not_hand_written(self):
        """The four-parallel-maps failure mode, closed off by construction."""
        assert set(macro.YAHOO_SERIES) | set(macro.FRED_SERIES) == set(macro.ALL_SERIES)
        for key, symbol in macro.YAHOO_SERIES.items():
            assert macro.SERIES_META[key]["symbol"] == symbol


class TestUtcDateHoldsForAsianSessions:
    """`_utc_date` stamps a bar by its UTC date, which is only the market's own
    session date while its OPEN falls on the same UTC day. True for every
    market here — and the reason the docstring warns about the ASX."""

    def _epoch(self, y, m, d, hh, mm, tz_offset_hours):
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=tz_offset_hours))
        return int(datetime(y, m, d, hh, mm, tzinfo=tz).timestamp())

    def test_tokyo_open_stamps_the_tokyo_session_date(self):
        # 2026-08-31 09:00 JST (UTC+9) == 2026-08-31 00:00 UTC
        assert macro._utc_date(self._epoch(2026, 8, 31, 9, 0, 9)) == "2026-08-31"

    def test_seoul_open_stamps_the_seoul_session_date(self):
        assert macro._utc_date(self._epoch(2026, 8, 31, 9, 0, 9)) == "2026-08-31"

    def test_hong_kong_open_stamps_the_same_date(self):
        # 09:30 HKT (UTC+8) == 01:30 UTC
        assert macro._utc_date(self._epoch(2026, 8, 31, 9, 30, 8)) == "2026-08-31"

    def test_frankfurt_open_stamps_the_same_date(self):
        # 09:00 CEST (UTC+2) == 07:00 UTC
        assert macro._utc_date(self._epoch(2026, 8, 31, 9, 0, 2)) == "2026-08-31"

    def test_new_york_open_stamps_the_same_date(self):
        # 09:30 EDT (UTC-4) == 13:30 UTC
        assert macro._utc_date(self._epoch(2026, 8, 31, 9, 30, -4)) == "2026-08-31"

    def test_a_pre_utc_midnight_open_would_be_stamped_a_day_early(self):
        """Documents the trap rather than pretending it cannot happen: the ASX
        opens 10:00 AEDT == 23:00 UTC the PREVIOUS day. Nothing here uses it;
        whoever adds it must convert through the exchange timezone instead."""
        assert macro._utc_date(self._epoch(2026, 8, 31, 10, 0, 11)) == "2026-08-30"


class TestHarvesterServerMetadataMirror:
    """`index.py` cannot import `src/` (the Docker build context is
    `mcp_server/`), so the macro metadata is a MIRROR. Mirrors drift — this is
    the same guard `tests/test_capabilities.py` puts on the tool registry."""

    def _index(self):
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        import index
        return index

    def test_series_match_in_both_directions(self):
        index = self._index()
        assert set(index._MACRO_SERIES) == set(macro.ALL_SERIES)

    def test_market_and_timing_agree_for_every_series(self):
        """A series the server calls `before_open` while the harvester calls it
        `same_session` is worse than a missing series: it is confidently wrong."""
        index = self._index()
        for key, meta in macro.SERIES_META.items():
            market, when_known = index._MACRO_META[key]
            assert market == meta["market"], f"{key}: market disagrees"
            assert when_known == meta["when_known"], f"{key}: when_known disagrees"

    def test_every_series_is_explained_to_the_model(self):
        index = self._index()
        for key in macro.ALL_SERIES:
            assert key in index._GLOSS_MACRO, f"{key} has no glossary entry"

    def test_the_freshness_stamp_no_longer_claims_everything_is_overnight(self):
        """`_freshness` used to read "US session close, known before the Taipei
        open" — true of the original five US/FX series, false the moment Seoul
        and Tokyo were added. It must now defer to the per-row field."""
        from unittest import mock
        index = self._index()
        with mock.patch.object(index.usage_mod, "record"), \
             mock.patch.object(index.db_v2, "query_macro_latest", return_value=[]):
            fresh = index.q_macro()["_freshness"]
        assert "before the Taipei open" not in fresh
        assert "when_known" in fresh


class TestQMacroMarketFilter:
    def _index(self):
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        import index
        return index

    _ROWS = [
        {"date": "2026-08-31", "series": "sox", "close": 11535.05, "pct_change": -0.45},
        {"date": "2026-08-31", "series": "kospi", "close": 3210.4, "pct_change": 0.8},
        {"date": "2026-08-31", "series": "nikkei", "close": 42100.0, "pct_change": 0.3},
    ]

    def _call(self, **kwargs):
        from unittest import mock
        index = self._index()
        with mock.patch.object(index.usage_mod, "record"), \
             mock.patch.object(index.db_v2, "query_macro_latest",
                               return_value=[dict(r) for r in self._ROWS]), \
             mock.patch.object(index.db_v2, "query_macro",
                               return_value=[dict(r) for r in self._ROWS]):
            return index.q_macro(**kwargs)

    def test_market_filter_narrows_to_that_market(self):
        out = self._call(market="korea")
        assert [r["series"] for r in out["macro"]] == ["kospi"]

    def test_unknown_market_lists_the_real_ones_instead_of_returning_nothing(self):
        out = self._call(market="atlantis")
        assert "error" in out and "korea" in out["markets_available"]

    def test_every_row_is_annotated_with_when_known(self):
        """The model must be able to tell a live peer from an overnight close
        without consulting the docstring."""
        out = self._call()
        by = {r["series"]: r for r in out["macro"]}
        assert by["sox"]["when_known"] == "before_open"
        assert by["kospi"]["when_known"] == "same_session"
        assert by["nikkei"]["market"] == "japan"

    def test_no_filter_returns_everything(self):
        out = self._call()
        assert out["count"] == 3
