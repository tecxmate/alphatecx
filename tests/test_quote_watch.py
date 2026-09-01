"""Intraday stop watcher (src/quote_watch.py).

The two properties that matter most:
- a missing quote can never produce a breach (None → skipped, same contract as
  rg's post-close pass), and
- one line, one day, one buzz — the rg_alerts dedup applies with `intraday_`
  kinds so the post-close verdict still fires as its own alert.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from src import quote_watch

_TPE = ZoneInfo("Asia/Taipei")


def _tue(hh: int, mm: int) -> datetime:
    # 2026-08-11 was a Tuesday.
    return datetime(2026, 8, 11, hh, mm, tzinfo=_TPE)


def _no_holidays():
    return mock.patch.object(quote_watch, "_is_trading_day", return_value=True)


class TestMarketHours:
    def test_inside_session_on_a_weekday(self):
        with _no_holidays():
            assert quote_watch.market_open_now(_tue(9, 0))
            assert quote_watch.market_open_now(_tue(13, 35))

    def test_outside_session(self):
        with _no_holidays():
            assert not quote_watch.market_open_now(_tue(8, 59))
            assert not quote_watch.market_open_now(_tue(13, 36))
            assert not quote_watch.market_open_now(_tue(20, 0))

    def test_weekend_never_needs_the_holiday_table(self):
        sat = datetime(2026, 8, 15, 10, 0, tzinfo=_TPE)
        # No mock: weekday() < 5 short-circuits before any DB touch.
        quote_watch._holiday_cache.clear()
        assert not quote_watch.market_open_now(sat)

    def test_holiday_closes_the_market(self):
        quote_watch._holiday_cache.clear()
        quote_watch._holiday_cache[date(2026, 8, 11)] = False
        assert not quote_watch.market_open_now(_tue(10, 0))
        quote_watch._holiday_cache.clear()

    def test_unreachable_holiday_table_fails_open_to_weekday(self):
        """session_state's degraded mode, mirrored: a DB blip costs a few
        quote calls on a holiday, never a silent watcher on a trading day."""
        quote_watch._holiday_cache.clear()
        with mock.patch.dict("sys.modules", {"src.harvester.loader": None}):
            assert quote_watch._is_trading_day(date(2026, 8, 11)) is True
        quote_watch._holiday_cache.clear()


class TestEnabledGate:
    def test_no_key_means_idle(self, monkeypatch):
        monkeypatch.delenv("FUGLE_API_KEY", raising=False)
        monkeypatch.delenv("QUOTE_WATCH_ENABLED", raising=False)
        assert not quote_watch.enabled()

    def test_explicit_off_wins_over_key(self, monkeypatch):
        monkeypatch.setenv("FUGLE_API_KEY", "k")
        monkeypatch.setenv("QUOTE_WATCH_ENABLED", "false")
        assert not quote_watch.enabled()

    def test_key_plus_default_is_on(self, monkeypatch):
        monkeypatch.setenv("FUGLE_API_KEY", "k")
        monkeypatch.delenv("QUOTE_WATCH_ENABLED", raising=False)
        assert quote_watch.enabled()


class TestFetchLastPrice:
    def test_http_error_returns_none_not_raise(self):
        resp = mock.Mock(status_code=429)
        with mock.patch.object(quote_watch.requests, "get", return_value=resp):
            assert quote_watch.fetch_last_price("2330", "k") is None

    def test_network_failure_returns_none(self):
        with mock.patch.object(
            quote_watch.requests, "get", side_effect=OSError("boom")
        ):
            assert quote_watch.fetch_last_price("2330", "k") is None

    def test_missing_last_price_field_returns_none(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"referencePrice": 100}
        with mock.patch.object(quote_watch.requests, "get", return_value=resp):
            assert quote_watch.fetch_last_price("2330", "k") is None


class TestCheckOnce:
    """Drive check_once with the store and Fugle mocked, rg.stops REAL —
    the breach semantics under test are the shared ones, not a re-mock of
    them (this suite has been burned by mocks that encode the author's
    assumption; see tests/test_console_pages.py)."""

    POSITION = {
        "ticker_id": "2324", "name": "仁寶", "kind": "position", "active": True,
        "cost": 40.0, "warn_price": 38.0, "exit_price": 36.0,
        "hard_stop_pct": 10, "qty_lots": 1,
    }

    def _run(self, price, record_returns=7, existing=None, monkeypatch=None):
        monkeypatch.setenv("FUGLE_API_KEY", "k")
        monkeypatch.delenv("QUOTE_WATCH_ENABLED", raising=False)
        import riskguard.store as store
        sent = []
        with _no_holidays(), \
             mock.patch.object(store, "active_positions",
                               return_value=[dict(self.POSITION)]), \
             mock.patch.object(quote_watch, "fetch_last_price",
                               return_value=price), \
             mock.patch.object(store, "record_alert",
                               return_value=record_returns) as record, \
             mock.patch.object(store, "find_alert", return_value=existing), \
             mock.patch.object(store, "mark_pushed") as mark, \
             mock.patch.object(quote_watch, "send",
                               side_effect=lambda m, category: sent.append(m) or True) as snd:
            pushed = quote_watch.check_once(now=_tue(10, 0))
        return pushed, sent, record, mark, snd

    def test_price_below_exit_line_alerts_once(self, monkeypatch):
        pushed, sent, record, mark, _ = self._run(35.5, monkeypatch=monkeypatch)
        assert pushed == 1
        assert "出場線" in sent[0]
        # The honesty line: intraday is not the close, and says so.
        assert "盤中價" in sent[0]
        assert record.call_args.args[0] == "intraday_stop_exit"
        mark.assert_called_once_with(7)

    def test_price_above_all_lines_stays_silent(self, monkeypatch):
        pushed, sent, *_ = self._run(41.0, monkeypatch=monkeypatch)
        assert pushed == 0 and sent == []

    def test_no_quote_is_not_a_breach(self, monkeypatch):
        """The property the whole module bends around."""
        pushed, sent, *_ = self._run(None, monkeypatch=monkeypatch)
        assert pushed == 0 and sent == []

    def test_duplicate_same_day_alert_is_not_resent_when_delivered(self, monkeypatch):
        pushed, sent, *_ = self._run(
            35.5, record_returns=None,
            existing={"id": 7, "pushed": True, "message": "x"},
            monkeypatch=monkeypatch,
        )
        assert pushed == 0 and sent == []

    def test_duplicate_is_resent_when_first_attempt_never_delivered(self, monkeypatch):
        """pipeline._emit's rule, honoured here too: a recorded-but-unpushed
        alert is a failed send, not a handled one."""
        pushed, sent, _, mark, _ = self._run(
            35.5, record_returns=None,
            existing={"id": 7, "pushed": False, "message": "retry me"},
            monkeypatch=monkeypatch,
        )
        assert pushed == 1 and sent == ["retry me"]
        mark.assert_called_once_with(7)

    def test_closed_market_does_no_work_at_all(self, monkeypatch):
        monkeypatch.setenv("FUGLE_API_KEY", "k")
        import riskguard.store as store
        with mock.patch.object(store, "active_positions") as pos:
            assert quote_watch.check_once(now=_tue(14, 30)) == 0
            pos.assert_not_called()
