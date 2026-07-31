"""M2 — entry checklist (PRD §5 M2, six questions).

The checklist has exactly two possible conclusions and neither of them is a
recommendation to buy. PRD §0 puts it plainly: the only test any feature has to
pass is "does this stop a loss or does it egg the operator on?" So a clean
sheet says 沒有阻止你的理由 — "nothing here stops you" — and never 建議買進.
Those two strings live in config and are asserted in tests, because copy drift
here is how a risk tool quietly becomes a stock tip generator.

A question whose data source is not built yet (M3 sector rank, M6 disposition
status) returns `skipped`, not `fail`. Blocking on an unbuilt module would
train the operator to override the checklist, which is worse than a known gap —
but the gap is always shown, never hidden.
"""
from __future__ import annotations

from . import config as cfg

PASS, FAIL, SKIP = "pass", "fail", "skipped"


def _q(n: int, question: str, status: str, detail: str) -> dict:
    return {"id": n, "question": question, "status": status, "detail": detail}


def _q1_light(f: dict) -> dict:
    light = f.get("risk_light")
    if light is None:
        return _q(1, "市場燈號 🟢?", SKIP, "今日燈號尚未計算")
    if light == "green":
        return _q(1, "市場燈號 🟢?", PASS, "市場燈號 🟢")
    emoji = cfg.LIGHT_EMOJI.get(light, "")
    return _q(1, "市場燈號 🟢?", FAIL, f"市場燈號 {emoji}{light}")


def _q2_sector(f: dict) -> dict:
    rank = f.get("sector_rank")
    if rank is None:
        return _q(2, "族群排名前5?", SKIP, "M3 族群強度尚未上線")
    if rank <= 5:
        return _q(2, "族群排名前5?", PASS, f"族群排名第 {rank}")
    return _q(2, "族群排名前5?", FAIL, f"族群排名第 {rank},非前5")


def _q3_vertical(f: dict) -> dict:
    """The 175 case: 3231 was bought after a four-day +25.9% run, then −12%."""
    gain = f.get("gain_5d_pct")
    label = f"5日漲幅 <{cfg.MAX_5D_GAIN_PCT:.0f}%?"
    if gain is None:
        return _q(3, label, SKIP, "無 5 日報酬資料")
    if gain < cfg.MAX_5D_GAIN_PCT:
        return _q(3, label, PASS, f"5日漲幅 {gain:+.1f}%")
    return _q(3, label, FAIL, f"5日漲幅 {gain:+.1f}% — 垂直段,不追")


def _q4_disposition(f: dict) -> dict:
    flag = f.get("is_disposition")
    if flag is None:
        return _q(4, "非注意/處置股?", SKIP, "M6 公告輪詢尚未上線")
    if flag:
        return _q(4, "非注意/處置股?", FAIL, "已列注意/處置股")
    return _q(4, "非注意/處置股?", PASS, "非注意/處置股")


def _q5_no_trade(f: dict) -> dict:
    """M7 veto. This is the module's ONLY power — it can block a day, and it
    contributes nothing to any score, light, or alert trigger (PRD §5 M7)."""
    reason = f.get("no_trade_reason")
    if reason:
        return _q(5, "今日為可執行日?", FAIL, f"節律否決:{reason}")
    return _q(5, "今日為可執行日?", PASS, "今日可執行")


def _q6_position_size(f: dict) -> dict:
    amount, cash = f.get("buy_amount"), f.get("available_cash")
    label = f"買進金額 ≤ 可用現金 {cfg.MAX_CASH_USE_PCT:.0f}%?"
    if amount is None or cash is None:
        return _q(6, label, SKIP, "未提供買進金額或可用現金")
    if not cash:
        return _q(6, label, FAIL, "可用現金為 0")
    pct = amount / cash * 100
    if pct <= cfg.MAX_CASH_USE_PCT:
        return _q(6, label, PASS, f"佔可用現金 {pct:.0f}%")
    return _q(6, label, FAIL, f"佔可用現金 {pct:.0f}%,超過上限")


_QUESTIONS = (_q1_light, _q2_sector, _q3_vertical, _q4_disposition,
              _q5_no_trade, _q6_position_size)


def evaluate(facts: dict) -> dict:
    """Run the six questions. Any ❌ blocks; unbuilt modules show as skipped.

    `facts` keys: risk_light, sector_rank, gain_5d_pct, is_disposition,
    no_trade_reason, buy_amount, available_cash, blacklisted, blacklist_note.
    """
    questions = [fn(facts) for fn in _QUESTIONS]
    failed = [q for q in questions if q["status"] == FAIL]
    skipped = [q for q in questions if q["status"] == SKIP]

    warnings = []
    if facts.get("blacklisted"):
        warnings.append(f"⛔ {facts.get('blacklist_note') or '已列拉黑名單'}")
    if skipped:
        warnings.append("未驗證項目:" + "、".join(f"Q{q['id']}" for q in skipped))

    if failed:
        reasons = "；".join(q["detail"] for q in failed)
        summary = f"{cfg.VERDICT_BLOCKED}{reasons}"
        verdict = "blocked"
    else:
        summary = cfg.VERDICT_CLEAR
        verdict = "clear"

    return {
        "ticker_id": facts.get("ticker_id"),
        "name": facts.get("name"),
        "verdict": verdict,
        "summary": summary,
        "questions": questions,
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "warnings": warnings,
    }
