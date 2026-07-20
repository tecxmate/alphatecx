import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp_server.api import session_state as ss
from src.harvester import twse

_TPE = ZoneInfo("Asia/Taipei")


def at(h, m, *, day=15):
    # 2026-07-15 is a Wednesday.
    return datetime(2026, 7, day, h, m, tzinfo=_TPE)


class PhaseTests(unittest.TestCase):
    def test_pre_open_auction_is_indicative(self):
        phase, indic, warn = ss.phase_for(at(8, 45), True)
        self.assertEqual(phase, "pre_open_auction")
        self.assertTrue(indic)
        self.assertIn("試撮", warn)

    def test_regular_session_is_a_real_price(self):
        phase, indic, warn = ss.phase_for(at(10, 30), True)
        self.assertEqual(phase, "regular")
        self.assertFalse(indic)
        self.assertIsNone(warn)

    def test_boundaries_are_half_open(self):
        # 09:00 sharp is regular, not still pre-open; 13:30 sharp is after-hours.
        self.assertEqual(ss.phase_for(at(9, 0), True)[0], "regular")
        self.assertEqual(ss.phase_for(at(13, 30), True)[0], "after_hours")
        self.assertEqual(ss.phase_for(at(14, 30), True)[0], "closed")

    def test_before_open_and_after_close_are_closed(self):
        self.assertEqual(ss.phase_for(at(8, 0), True)[0], "closed")
        self.assertEqual(ss.phase_for(at(15, 0), True)[0], "closed")

    def test_holiday_is_closed_at_every_clock_time(self):
        # A holiday at 10:30 is still shut — is_trading_day gates everything.
        phase, indic, warn = ss.phase_for(at(10, 30), False)
        self.assertEqual(phase, "closed")
        self.assertFalse(indic)

    def test_build_state_carries_source_and_indicative_flag(self):
        s = ss.build_state(at(8, 45), True, "calendar")
        self.assertEqual(s["phase"], "pre_open_auction")
        self.assertTrue(s["price_is_indicative"])
        self.assertEqual(s["calendar_source"], "calendar")
        self.assertEqual(s["date"], "2026-07-15")


class HolidayClassifierTests(unittest.TestCase):
    """The schedule lists open reference days next to real closures; only
    開始交易/最後交易 rows trade. See twse.fetch_twse_holidays."""

    def _classify(self, name):
        # Mirror the fetcher's rule without a network call.
        return not any(m in name for m in twse._OPEN_REFERENCE_MARKERS)

    def test_statutory_holiday_is_a_closure(self):
        self.assertTrue(self._classify("端午節"))
        self.assertTrue(self._classify("農曆除夕及春節"))

    def test_settlement_only_day_is_a_closure(self):
        # '市場無交易' contains 交易 but not 開始/最後交易 — must stay closed.
        self.assertTrue(self._classify("市場無交易，僅辦理結算交割作業"))

    def test_resumption_and_last_trading_days_are_open(self):
        self.assertFalse(self._classify("農曆春節後開始交易日"))
        self.assertFalse(self._classify("農曆春節前最後交易日"))


if __name__ == "__main__":
    unittest.main()
