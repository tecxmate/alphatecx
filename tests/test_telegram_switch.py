"""The TELEGRAM_ENABLED kill switch (src/config.py, src/alerts/telegram.py).

Every outbound Telegram message in this repo — Risk Guard stop alerts, the
post-close brief, the daily summary, the thesis heartbeat and the news poller's
watchlist pushes — funnels through `send()`/`send_daily_summary()`, which gate on
`telegram_configured()`. The switch is added there so one flag silences all of
them and no send site needs to know about it.

The distinction these tests pin: "switched off" and "misconfigured" must not look
the same. Collapsing them is exactly how every Risk Guard alert sat at
pushed:false for weeks while the notify-on-failure path — which depended on the
same token — was itself silently dead.
"""
import importlib
import unittest
from contextlib import contextmanager
from unittest import mock


@contextmanager
def telegram_env(**env):
    """Patch the environment, reload both modules under it, and KEEP the patch
    active for the caller's assertions.

    The patch cannot be released early: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are
    module-level and captured at import, but `telegram_enabled()` reads
    os.getenv on every call — so a helper that reloads and then restores the
    environment tests the restored value, not the one it set up.
    """
    with mock.patch.dict("os.environ", env, clear=False):
        import src.config as config
        importlib.reload(config)
        import src.alerts.telegram as tg
        importlib.reload(tg)
        try:
            yield config, tg
        finally:
            importlib.reload(config)
            importlib.reload(tg)


class EnabledFlagTests(unittest.TestCase):
    def test_default_is_enabled(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_ENABLED", None)
            import src.config as config
            importlib.reload(config)
            self.assertTrue(config.telegram_enabled())

    def test_falsey_spellings_all_disable(self):
        for value in ("false", "False", "FALSE", "0", "no", "off", " off "):
            with telegram_env(TELEGRAM_ENABLED=value) as (config, _):
                self.assertFalse(config.telegram_enabled(), f"{value!r} should disable")

    def test_anything_else_leaves_it_on(self):
        for value in ("true", "1", "yes", "on"):
            with telegram_env(TELEGRAM_ENABLED=value) as (config, _):
                self.assertTrue(config.telegram_enabled(), f"{value!r} should enable")

    def test_disabling_makes_configured_false_even_with_a_good_token(self):
        with telegram_env(TELEGRAM_ENABLED="false", TELEGRAM_TOKEN="123:abc",
                          TELEGRAM_CHAT_ID="42") as (config, _):
            self.assertFalse(config.telegram_configured())


class SendBehaviourTests(unittest.TestCase):
    def test_disabled_send_makes_no_network_call(self):
        with telegram_env(TELEGRAM_ENABLED="false", TELEGRAM_TOKEN="123:abc",
                          TELEGRAM_CHAT_ID="42") as (_, tg):
            with mock.patch.object(tg, "requests") as req:
                self.assertFalse(tg.send("hello"))
                req.post.assert_not_called()

    def test_switched_off_logs_at_info_not_warning(self):
        # A deliberate off is routine. Warning-level noise on every scheduled run
        # trains an operator to ignore the channel that reports real breakage.
        with telegram_env(TELEGRAM_ENABLED="false", TELEGRAM_TOKEN="123:abc",
                          TELEGRAM_CHAT_ID="42") as (_, tg):
            with self.assertLogs("telegram", level="INFO") as cm:
                tg.send("hello")
        self.assertTrue(any("disabled" in m.lower() for m in cm.output))
        self.assertFalse(any(r.startswith("WARNING") for r in cm.output))

    def test_missing_token_still_warns(self):
        # The other case: a system that believes it is alerting and is not.
        with telegram_env(TELEGRAM_ENABLED="true", TELEGRAM_TOKEN="",
                          TELEGRAM_CHAT_ID="") as (_, tg):
            with self.assertLogs("telegram", level="WARNING") as cm:
                tg.send("hello")
        self.assertTrue(any("not configured" in m for m in cm.output))

    def test_enabled_with_a_token_still_attempts_delivery(self):
        with telegram_env(TELEGRAM_ENABLED="true", TELEGRAM_TOKEN="123:abc",
                          TELEGRAM_CHAT_ID="42") as (_, tg):
            with mock.patch.object(tg, "requests") as req:
                req.post.return_value.raise_for_status.return_value = None
                self.assertTrue(tg.send("hello"))
                req.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
