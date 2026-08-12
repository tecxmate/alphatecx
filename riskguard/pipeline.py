"""Risk Guard cron entry points (PRD §3).

    python -m riskguard.pipeline --mode post_close   # M1 + M2 + M2b + held_pct
    python -m riskguard.pipeline --mode pre_market   # light + position summary

Deviation from PRD §3, stated plainly: the PRD schedules these on Vercel Cron at
15:30 / 08:30. This repo has no Vercel cron — `mcp_server/vercel.json` defines
only rewrites, and every scheduled job already runs on GitHub Actions
(.github/workflows/daily_harvest.yml, 16:30 Taipei). post_close is appended to
that workflow instead, so it inherits the Neon IPv4 /etc/hosts pin, the
gssencmode=disable DSN, and the Telegram secrets. Cost: M1 lands at ~16:40
rather than 15:30. For a system whose output is "what to do at tomorrow's open",
that hour is not load-bearing.

Everything is idempotent. A re-run recomputes the same light, hits the alert
unique index, and sends nothing twice.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from mcp_server.api.rg import light as light_mod
from mcp_server.api.rg import messages, scoring, settlement, stops
from riskguard import sources, store
from src.alerts.telegram import send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("riskguard.pipeline")

_TPE = ZoneInfo("Asia/Taipei")


def _today() -> str:
    return datetime.now(_TPE).date().isoformat()


def _plus_days(iso: str, n: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def _emit(kind: str, severity: str, message: str, *, ticker_id=None,
          payload=None, date_iso=None, dedup_key=None) -> bool:
    """Record then push. Returns True if this alert was newly delivered.

    A None id means the unique index rejected it as a same-day duplicate, which
    is the intended silence on a pipeline re-run — not an error.
    """
    alert_id = store.record_alert(kind, severity, message, ticker_id=ticker_id,
                                  payload=payload, date_iso=date_iso,
                                  dedup_key=dedup_key)
    if alert_id is None:
        # Already recorded today. Silence is the intended de-dup ONLY if the
        # earlier run actually delivered it. It often had not: the Zeabur `cron`
        # service runs this same chain with TELEGRAM_TOKEN deliberately unset (so
        # a double run cannot double-buzz), so `send` returns False and the row
        # lands unpushed — and then the GitHub Actions run, the one that DOES
        # hold the token, hit this branch and returned without ever sending.
        # Every alert stayed pushed:false, and flush_undelivered only sweeps
        # severity='critical', so anything softer was lost outright.
        # Observed live 2026-08-10. Whoever gets here holding a working token
        # finishes the delivery; a run without one still changes nothing.
        existing = store.find_alert(kind, dedup_key or ticker_id or "",
                                    date_iso=date_iso)
        if existing and not existing["pushed"] and existing.get("message"):
            if send(existing["message"]):
                store.mark_pushed(existing["id"])
                log.info("alert %s/%s was recorded undelivered — sent now",
                         kind, ticker_id)
                return True
            log.warning("alert %s/%s still undelivered after retry", kind, ticker_id)
            return False
        log.info("alert %s/%s already recorded and delivered — not resending",
                 kind, ticker_id)
        return False
    if send(message):
        store.mark_pushed(alert_id)
        return True
    log.warning("alert %s recorded (id=%s) but Telegram send failed", kind, alert_id)
    return False


def flush_undelivered() -> int:
    """Re-send critical alerts that were recorded but never delivered.

    PRD §6: 「先寫 rg_alerts 再發,補發 critical」. Without this the write-then-send
    order is a trap rather than a safety net — a Telegram outage at 16:40 leaves
    the row unpushed, and the next run's ON CONFLICT suppresses the re-record,
    so the exit alert would never reach the phone and nothing would retry it.
    """
    pending = store.unpushed_critical()
    sent = 0
    for row in pending:
        if not row.get("message"):
            continue
        if send(row["message"]):
            store.mark_pushed(row["id"])
            sent += 1
    if pending:
        log.info("補發: %d undelivered critical alerts, %d sent", len(pending), sent)
    return sent


# ── M1 ──────────────────────────────────────────────────────────────────────

def run_risk_light(as_of: str) -> dict:
    """Compute, store, and (on a change) push today's market risk light."""
    yyyymmdd = as_of.replace("-", "")
    breadth = sources.fetch_breadth(yyyymmdd)
    # 30 calendar days back comfortably covers the 5-session lookback across a
    # long weekend or a typhoon closure, in one request.
    fut_series = sources.fetch_foreign_futures_oi_series(_plus_days(as_of, -30), as_of)

    metrics = store.build_metrics(as_of, breadth, fut_series)
    score, reasons = scoring.score_day(metrics)

    prev = store.prev_market_day(as_of)
    prev_light = prev["risk_light"] if prev else None
    ctx = light_mod.build_index_context(metrics["_closes"])
    ctx["prev_score"] = prev["risk_score"] if prev else None
    ctx["close_above_ma20"] = (
        metrics["taiex_close"] is not None and metrics["ma20"] is not None
        and metrics["taiex_close"] >= metrics["ma20"]
    )

    resolved, why = light_mod.resolve_light(score, prev_light, ctx)
    store.upsert_market_daily(metrics, resolved, score, reasons)
    log.info("M1 %s: score=%s raw=%s light=%s (%s)",
             as_of, score, scoring.light_from_score(score), resolved, why)

    missing = scoring.missing_subitems(reasons)
    if resolved != prev_light:
        msg = messages.format_light_change(prev_light, resolved, score, reasons, missing)
        _emit("risk_light_change", "warn" if resolved != "green" else "info",
              msg + f"\n<i>{why}</i>", date_iso=as_of, dedup_key=resolved)

    return {"date": as_of, "score": score, "light": resolved,
            "prev_light": prev_light, "reason": why, "data_missing": missing}


# ── M2 ──────────────────────────────────────────────────────────────────────

def run_stop_check(as_of: str, light: str | None = None) -> int:
    positions = store.active_positions()
    closes = store.closes_for([p["ticker_id"] for p in positions], as_of)
    alerts = stops.evaluate(positions, closes)
    sent = 0
    for a in alerts:
        if _emit(a["kind"], a["severity"], messages.format_alert(a, light),
                 ticker_id=a["ticker_id"], payload=a, date_iso=as_of):
            sent += 1

    # A position with no price was not checked. Saying so is the whole point:
    # otherwise "0 stop alerts" reads as "nothing breached" when it actually
    # means "nothing was looked at".
    for p in stops.unpriced(positions, closes):
        if _emit("stop_unchecked", "warn",
                 messages.format_alert({
                     "kind": "stop_unchecked",
                     "ticker_id": p["ticker_id"], "name": p.get("name"),
                     "severity": "warn",
                     "detail": f"{as_of} 無收盤價,停損未檢查",
                     "action": ("此檔沒有 OHLCV 資料(raw_twse_ohlcv 只涵蓋分類供應鏈"
                                "universe + 0050)。請改在券商端掛觸價條件單,不要依賴本系統。"),
                 }, light),
                 ticker_id=p["ticker_id"], date_iso=as_of):
            sent += 1

    log.info("M2 %s: %d stop alerts, %d sent", as_of, len(alerts), sent)
    return sent


# ── M2b ─────────────────────────────────────────────────────────────────────

def run_settlement_check(as_of: str, light: str | None = None) -> int:
    schedule = store.settlement_schedule(as_of)
    if not schedule:
        log.info("M2b %s: no upcoming settlements", as_of)
        return 0

    balance = store.latest_balance()
    days = store.trading_days(as_of, _plus_days(as_of, 21))
    alerts = settlement.check_gap(schedule, balance, as_of, days)
    sent = 0
    for a in alerts:
        # Keyed on the settlement date: two shortfalls on different dates are
        # two distinct warnings, not one repeated.
        if _emit(a["kind"], a["severity"], messages.format_alert(a, light),
                 payload=a, date_iso=as_of, dedup_key=str(a["date"])):
            sent += 1
    log.info("M2b %s: %d settlement alerts, %d sent", as_of, len(alerts), sent)
    return sent


# ── Modes ───────────────────────────────────────────────────────────────────

def post_close(as_of: str | None = None) -> dict:
    """15:30-equivalent run. Each stage is isolated: a failure in one must not
    prevent the others, because a dead TAIFEX endpoint cancelling that day's
    stop-loss check is exactly the compound failure this system exists to avoid.
    """
    as_of = as_of or store.last_trading_day()
    log.info("post_close pipeline for %s", as_of)
    result: dict = {"date": as_of, "errors": []}

    try:
        result["risk_light"] = run_risk_light(as_of)
    except Exception as e:
        log.exception("M1 failed")
        result["errors"].append(f"M1: {e}")

    light = (result.get("risk_light") or {}).get("light")

    # flush_undelivered runs last so it also picks up anything this run recorded
    # but failed to send.
    for name, fn in (("M2", lambda: run_stop_check(as_of, light)),
                     ("M2b", lambda: run_settlement_check(as_of, light)),
                     ("held_pct", lambda: store.snapshot_held_pct(as_of)),
                     ("resend", flush_undelivered)):
        try:
            result[name] = fn()
        except Exception as e:
            log.exception("%s failed", name)
            result["errors"].append(f"{name}: {e}")

    return result


def pre_market(as_of: str | None = None) -> dict:
    """08:30-equivalent run: restate a red light and show where the lines sit.

    Red is repeated every morning for as long as it lasts (PRD §5 M1). Yellow
    and green are not — a light that speaks every day stops being a signal.
    """
    as_of = as_of or store.last_trading_day()
    prev = store.prev_market_day(_plus_days(as_of, 1))
    if not prev:
        log.info("pre_market: no risk light computed yet")
        return {"date": as_of, "pushed": False}

    # Runs whatever the light is: an exit alert stranded by last night's
    # Telegram outage has to reach the phone before the 09:00 open, and that is
    # true on a green day too.
    resent = flush_undelivered()

    if prev["risk_light"] != "red":
        log.info("pre_market: light is %s — no restatement", prev["risk_light"])
        return {"date": as_of, "pushed": False, "light": prev["risk_light"],
                "resent": resent}

    positions = store.active_positions()
    closes = store.closes_for([p["ticker_id"] for p in positions], as_of)
    rows = stops.distances(positions, closes)

    lines = [f"🔴 <b>盤前重申 — 市場燈號 red</b> (score {prev['risk_score']})"]
    held = [r for r in rows if r["kind"] == "position"]
    if held:
        for r in held:
            near = (f"距出場線 {r['pct_to_exit']:+.1f}%"
                    if r["pct_to_exit"] is not None else "未設線")
            lines.append(f"  {r['name'] or ''}({r['ticker_id']}) 收 {r['close']} — {near}")
    else:
        lines.append("  目前空手,無持倉風險")

    note = store.no_trade_reason(as_of)
    if note:
        lines.append(f"  📿 今日節律否決:{note}")
    lines.append("👉 禁新倉,先確認每一檔的條件單已掛在券商端。")
    lines.append(f"<i>{messages.sunzi_for('risk_light_red')}</i>")

    pushed = _emit("risk_light_restate", "warn", "\n".join(lines), date_iso=as_of,
                   dedup_key="red")
    return {"date": as_of, "pushed": pushed, "light": prev["risk_light"],
            "resent": resent}


def main() -> None:
    ap = argparse.ArgumentParser(description="Risk Guard pipeline")
    ap.add_argument("--mode", choices=["post_close", "pre_market"], default="post_close")
    ap.add_argument("--date", help="ISO date to run for (default: last trading day)")
    args = ap.parse_args()

    result = post_close(args.date) if args.mode == "post_close" else pre_market(args.date)
    log.info("done: %s", result)
    if result.get("errors"):
        # Non-zero exit so the workflow step is visibly red — but only after
        # every stage has had its turn.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
