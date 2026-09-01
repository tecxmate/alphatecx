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
        """Two vendors is the hedge: a Yahoo outage costs four series, not five."""
        assert "us10y" in macro.FRED_SERIES
        assert "us10y" not in macro.YAHOO_SERIES


class TestFetchSeriesErrorHandling:
    def test_partial_failure_returns_rows_and_errors_not_an_exception(self, monkeypatch):
        """One 429 must not cost the other four series."""
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

    def test_total_failure_is_empty_rows_plus_five_errors_not_a_raise(self, monkeypatch):
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
