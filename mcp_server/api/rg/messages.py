"""Telegram message formatting (PRD §6).

Fixed shape, one line each:
    [燈號emoji] [嚴重度] 股名(代碼) | 事實 | 要做的動作 | 兵法一句

The action line is mandatory. A push that states a fact without naming the next
physical action is what produced the four-day stall on the 28.6 exit — the
information was there and the hand still did not move. `format_alert` therefore
falls back to an explicit "check it yourself" instruction rather than emitting
an actionless message.

The 兵法 line is looked up from config by the alert kind that was already
decided upstream. It is pure decoration and must never be consulted before a
trigger fires (PRD §6 constraint, mirrors the M7 rule).
"""
from __future__ import annotations

from . import config as cfg


def sunzi_for(kind: str) -> str:
    """Copy-layer lookup. Read only here, only after a kind has been decided."""
    return cfg.SUNZI_BY_KIND.get(kind, "")


def _esc(text: object) -> str:
    """Telegram HTML parse_mode needs these three escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _head(alert: dict, light: str | None) -> str:
    sev = cfg.SEVERITY_EMOJI.get(alert.get("severity", "info"), "")
    light_emoji = cfg.LIGHT_EMOJI.get(light or "", "")
    name, ticker = alert.get("name"), alert.get("ticker_id")
    who = f"{_esc(name)}({_esc(ticker)})" if ticker else "大盤"
    return f"{light_emoji}{sev} <b>{who}</b>".strip()


_FACT_BUILDERS = {
    "stop_exit": lambda a: (
        f"收盤 {a['close']} ≤ 出場線 {a['line']}"
        + ("(成本兜底線)" if a.get("line_is_fallback") else "")
    ),
    "stop_warn": lambda a: f"收盤 {a['close']} ≤ 警戒線 {a['line']}",
    "settlement_gap": lambda a: (
        f"{a['date']} 交割淨應付超出餘額 NT${a['shortfall']:,.0f}"
        + (f",距今 {a['days_ahead']} 個交易日" if a.get("days_ahead") is not None else "")
    ),
}


def format_alert(alert: dict, light: str | None = None) -> str:
    """Render one alert. Every message carries a fact line and an action line."""
    kind = alert.get("kind", "")
    builder = _FACT_BUILDERS.get(kind)
    fact = builder(alert) if builder else (alert.get("detail") or kind)
    action = alert.get("action") or "請自行確認持倉狀態並決定動作。"

    lines = [_head(alert, light), _esc(fact), f"👉 {_esc(action)}"]
    quote = sunzi_for(kind)
    if quote:
        lines.append(f"<i>{_esc(quote)}</i>")
    return "\n".join(lines)


def format_light_change(
    prev_light: str | None,
    light: str,
    score: int,
    reasons: list[dict],
    missing: list[str] | None = None,
) -> str:
    """Render an M1 light transition, or a red-light restatement.

    Only transitions are pushed (PRD §5 M1), except that red is restated every
    pre-market for as long as it lasts.
    """
    emoji = cfg.LIGHT_EMOJI.get(light, "")
    prev_emoji = cfg.LIGHT_EMOJI.get(prev_light or "", "")
    arrow = f"{prev_emoji}{prev_light} → " if prev_light and prev_light != light else ""

    action = {
        "red": "禁新倉,建議總持股 ≤50%,停損線上移。",
        "yellow": "新倉減半,停損上移。",
        "green": "維持既有紀律,無額外限制。",
    }[light]

    lines = [f"{emoji} <b>市場風險燈號 {arrow}{emoji}{light}</b>  (score {score})"]
    for r in reasons:
        if r["points"] > 0:
            lines.append(f"  +{r['points']} {_esc(r['detail'])}")
    if not any(r["points"] for r in reasons):
        lines.append("  五項子指標均未扣分")
    lines.append(f"👉 {action}")

    if missing:
        lines.append(f"⚠️ 資料缺漏(未計分):{_esc('、'.join(missing))}")

    kind = "risk_light_red" if light == "red" else (
        "risk_light_green" if light == "green" else "")
    quote = sunzi_for(kind)
    if quote:
        lines.append(f"<i>{_esc(quote)}</i>")
    return "\n".join(lines)


def format_checklist(result: dict) -> str:
    """Render a /check result. Never contains a buy suggestion — see checklist."""
    mark = {"pass": "✅", "fail": "❌", "skipped": "➖"}
    who = f"{_esc(result.get('name') or '')}({_esc(result.get('ticker_id'))})"
    lines = [f"<b>進場 checklist — {who}</b>"]
    for q in result["questions"]:
        lines.append(f"{mark[q['status']]} {_esc(q['question'])} — {_esc(q['detail'])}")
    for w in result.get("warnings", []):
        lines.append(_esc(w))
    lines.append(f"👉 <b>{_esc(result['summary'])}</b>")
    if result["verdict"] == "blocked":
        quote = sunzi_for("checklist_block")
        if quote:
            lines.append(f"<i>{_esc(quote)}</i>")
    return "\n".join(lines)
