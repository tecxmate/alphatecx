"""The two console surfaces built from live state rather than pre-rendered.

`overview` answers "is this thing healthy and what is here" — the page that did
not exist, which is why finding anything meant knowing its URL. `system_map`
answers "how does this work", generated from the SAME tool registry the MCP
server serves, so it cannot drift the way a hand-maintained diagram would (and
the way `sc_capabilities` itself silently did, to 33 of 48 tools).

Both fail soft: the database is not reachable from every environment that can
serve a page, and a console that 500s when Postgres blinks is worse than one
that says the pipeline is unreachable.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

_TPE = ZoneInfo("Asia/Taipei")

try:
    import db_v2
    from console import NAV, shell
    from rg import config as cfg
    from rg import db as rg_db
except ModuleNotFoundError:      # package import path used by local tests
    from . import db_v2
    from .console import NAV, shell
    from .rg import config as cfg
    from .rg import db as rg_db

log = logging.getLogger("console_pages")

_OVERVIEW_CSS = """
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(212px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden;margin-bottom:26px}
.card{background:var(--surface);padding:13px 15px}
.card dt{font-family:var(--data);font-size:10px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--slate);margin:0 0 5px}
.card dd{margin:0;font-family:var(--data);font-size:19px;font-variant-numeric:tabular-nums;
  letter-spacing:-.01em}
.card .sub{display:block;font-size:11px;color:var(--slate);margin-top:2px;letter-spacing:0}
.ok{color:var(--down)} .warn{color:var(--amber)} .bad{color:var(--up)}

.sec{font-family:var(--data);font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--slate);margin:0 0 9px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(238px,1fr));gap:9px;margin-bottom:26px}
.tile{display:block;background:var(--surface);border:1px solid var(--line);border-radius:3px;
  padding:14px 15px;text-decoration:none}
.tile:hover{border-color:var(--slate)}
.tile b{display:block;font-size:13px;margin-bottom:3px}
.tile span{display:block;font-size:12px;color:var(--slate);line-height:1.45}

table.freshness{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--surface);
  border:1px solid var(--line);border-radius:3px}
table.freshness th,table.freshness td{text-align:left;padding:7px 12px;border-bottom:1px solid var(--line)}
table.freshness tr:last-child td{border-bottom:0}
table.freshness th{font-family:var(--data);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--slate);font-weight:500}
table.freshness td.n{font-family:var(--data);font-variant-numeric:tabular-nums;text-align:right;
  vertical-align:top}
table.freshness td b{display:block;font-size:13px}
table.freshness .what{display:block;color:var(--slate);font-size:12px;line-height:1.45;
  margin:2px 0 3px;max-width:62ch}
table.freshness code{font-family:var(--data);font-size:10.5px;color:var(--slate)}
.note{color:var(--slate);font-size:12.5px;margin:0 0 12px;max-width:66ch}
.note code{font-family:var(--data);font-size:11.5px}
.scroll{overflow-x:auto}
"""

_SYSTEM_CSS = """
.prose{max-width:64ch}
.prose p{margin:0 0 14px;color:var(--slate)}
.prose p strong{color:var(--ink);font-weight:600}
figure{margin:0 0 30px}
.scroll{overflow-x:auto}
figure svg{display:block;max-width:100%;height:auto;min-width:520px;color:var(--ink)}
figcaption{font-size:12px;color:var(--slate);margin-top:10px;max-width:60ch}
.fams{display:grid;grid-template-columns:repeat(auto-fit,minmax(258px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden}
.fam{background:var(--surface);padding:14px 16px}
.fam-h{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:6px}
.fam-k{font-family:var(--data);font-size:12px;color:var(--up)}
.fam-n{font-family:var(--data);font-size:10px;color:var(--slate);font-variant-numeric:tabular-nums}
.fam .ask{font-size:13px;margin:0 0 5px}
.fam .tools{font-family:var(--data);font-size:10.5px;color:var(--slate);line-height:1.6;
  word-break:break-word}
.limits{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:12px;max-width:64ch}
.limits li{display:grid;grid-template-columns:3px 1fr;gap:12px}
.limits .bar{background:var(--down);border-radius:2px}
.limits b{font-size:13px} .limits p{margin:2px 0 0;font-size:12.5px;color:var(--slate)}
"""

# Plain-language framing per tool family. The tool NAMES come from the live
# registry; only the human explanation lives here, so a new tool shows up in its
# family automatically even before anyone writes prose for it.
_FAMILIES: list[tuple[str, str, str]] = [
    ("core", "Is this name worth a look?",
     "Ticker lookup, beginner stock card, quotes, price history, dividend dates, "
     "the limit-up board, market-wide flow screens, and the session clock that flags "
     "pre-open simulated prices as not-real."),
    ("q_", "Is it cheap, and does the setup hold up?",
     "Valuation, technical indicators, screeners, backtests, market regime, quality "
     "score, lead-lag pairs, cointegration, factor alpha and PCA decomposition."),
    ("sc_", "Who else moves when TSMC moves?",
     "The AI supply-chain map across four pillars — semiconductor, infrastructure, "
     "equipment, energy — with sector and per-ticker institutional flow."),
    ("rg_", "Is now a bad time to be buying anything?",
     "Risk Guard: the market risk light and its five subitems, monitored positions "
     "with exit lines, the alert stream, and an entry checklist that never says buy."),
    ("n_", "Did something happen to this name?",
     "Recent articles across 12 feeds matched to tickers, plus per-source freshness "
     "so a feed that went quiet is visible rather than silently absent."),
    ("w_", "Keep an eye on this one for me.",
     "A watchlist that persists across conversations — add and archive from inside "
     "the chat."),
    ("u_", "Everything known about the universe, joined.",
     "One unified read across classification, watch state and computed signals."),
    ("d_", "What did the desk say yesterday?",
     "Scheduled pre-market, intraday and post-close briefs, by date."),
    ("raw_", "Show me the working, not the summary.",
     "The raw per-ticker institutional flow time series."),
]


def _family_of(tool: str) -> str:
    prefix = tool.split("_")[0] + "_"
    return prefix if prefix in {f[0] for f in _FAMILIES} else "core"


# ── Overview ────────────────────────────────────────────────────────────────

# What each harvested table actually holds, in the words someone who does not
# work on the pipeline would use. A row count means nothing without this.
_TABLE_MEANING: dict[str, tuple[str, str]] = {
    "raw_twse_t86": (
        "Institutional flow",
        "Who bought and sold each stock — foreign investors, investment trusts and "
        "dealers — one row per stock per session. The single most-used table here."),
    "raw_twse_ohlcv": (
        "Daily prices",
        "Open, high, low, close and volume per stock per session. Everything that "
        "draws a chart or computes an indicator reads this."),
    "raw_twse_holdings": (
        "Foreign ownership",
        "What percentage of each company foreign investors hold, and how much room "
        "is left before the statutory ceiling."),
    "raw_twse_margin": (
        "Margin balance",
        "How much stock is being bought with borrowed money. Rising leverage into a "
        "falling market is the classic un-capitulated-retail signal."),
    "raw_monthly_revenue": (
        "Monthly revenue",
        "Self-reported monthly sales per listed company (MOPS), the earliest public "
        "read on whether a business is actually growing."),
    "dim_ticker": (
        "Company directory",
        "Every listed code with its Chinese and English name, market and supply-chain "
        "classification. What turns '2330' into 台積電."),
}


def _freshness_words(latest: str | None, today: str) -> tuple[str, str]:
    """(css class, plain-language age) for a session date.

    Says "yesterday's session" rather than printing a date and leaving the reader
    to work out whether that is normal. Taiwan trades weekdays, so a Monday
    reading Friday's session is healthy, not three days stale — the wording is
    deliberately vague about weekends instead of being confidently wrong.
    """
    if not latest:
        return "bad", "never ingested"
    try:
        d0 = date.fromisoformat(str(latest)[:10])
        d1 = date.fromisoformat(today[:10])
    except ValueError:
        return "", str(latest)
    gap = (d1 - d0).days
    if gap <= 0:
        return "ok", "today's session"
    if gap == 1:
        return "ok", "yesterday's session"
    if gap <= 4:
        return "ok", f"{gap} days ago — normal across a weekend"
    if gap <= 8:
        return "warn", f"{gap} days ago — later than expected"
    return "bad", f"{gap} days ago — the harvest has stalled"


def overview_html(ticker_count: int) -> str:
    """Pipeline health, explained. Every number says what it counts and whether
    its value is healthy — a bare row count tells an operator nothing."""
    today = datetime.now(_TPE).date().isoformat()
    try:
        status = db_v2.query_data_status()
    except Exception:               # noqa: BLE001 — a console must not 500
        log.exception("console overview: data status unavailable")
        status = None

    tiles = "".join(
        f'<a class="tile" href="{escape(href)}"><b>{escape(label)}</b>'
        f'<span>{escape(purpose)}</span></a>'
        for key, href, label, purpose in NAV if key != "home"
    )
    surfaces = f'<p class="sec">Where everything lives</p><div class="tiles">{tiles}</div>'

    if status is None:
        return shell(
            "alphatecx Console", "home",
            '<dl class="cards"><div class="card"><dt>Pipeline</dt>'
            '<dd class="bad">unreachable</dd><span class="sub">The database did not '
            'answer. Every surface below still works from cached files; anything '
            'needing live data will not.</span></div></dl>' + surfaces,
            heading="Overview",
            subtitle="Pipeline health and every surface in one place.",
            extra_css=_OVERVIEW_CSS,
        )

    counts = status.get("table_counts") or {}
    latest_t86 = status.get("latest_t86_date")
    cls, words = _freshness_words(latest_t86, today)
    total = sum(int(v or 0) for v in counts.values())

    cards = (
        '<dl class="cards">'
        f'<div class="card"><dt>Latest session held</dt><dd class="{cls}">'
        f'{escape(str(latest_t86 or "—"))}</dd>'
        f'<span class="sub">{escape(words)}</span></div>'
        f'<div class="card"><dt>Rows across the pipeline</dt><dd>{total:,}</dd>'
        '<span class="sub">approximate live count, all harvested tables</span></div>'
        f'<div class="card"><dt>Companies classified</dt><dd>{int(counts.get("dim_ticker") or 0):,}</dd>'
        '<span class="sub">codes with a name and market attached</span></div>'
        f'<div class="card"><dt>Ticker pages built</dt><dd>{ticker_count}</dd>'
        '<span class="sub">pre-rendered nightly, one per covered name</span></div>'
        '</dl>'
    )

    rows_html = ""
    for table, n in counts.items():
        label, meaning = _TABLE_MEANING.get(table, (table, ""))
        rows_html += (
            f'<tr><td><b>{escape(label)}</b><span class="what">{escape(meaning)}</span>'
            f'<code>{escape(table)}</code></td>'
            f'<td class="n">{int(n or 0):,}</td></tr>'
        )
    table_html = (
        '<p class="sec">What is stored, and what it is</p><div class="scroll">'
        '<table class="freshness"><thead><tr><th>Dataset</th>'
        '<th style="text-align:right">Rows</th></tr></thead>'
        f'<tbody>{rows_html}</tbody></table></div>'
    )

    ing = status.get("recent_ingestions") or []
    ing_rows = "".join(
        '<tr><td><code>{src}</code></td><td>{d}</td><td class="n">{n:,}</td>'
        '<td class="{cls}">{st}</td></tr>'.format(
            src=escape(str(r.get("source") or "—")),
            d=escape(str(r.get("target_date") or "—")),
            n=int(r.get("rows_upserted") or 0),
            cls="ok" if str(r.get("status")) == "ok" else "warn",
            st=escape(str(r.get("status") or "—")),
        )
        for r in ing
    )
    ing_html = (
        '<p class="sec">Last few harvest runs</p>'
        '<p class="note">Each run pulls one source for one session. '
        '<code>empty</code> on a real trading day means the exchange had not '
        'published yet — the next run retries it.</p><div class="scroll">'
        '<table class="freshness"><thead><tr><th>Source</th><th>Session</th>'
        '<th style="text-align:right">Rows</th><th>Result</th></tr></thead>'
        f'<tbody>{ing_rows}</tbody></table></div>'
    ) if ing_rows else ""

    return shell(
        "alphatecx Console", "home", cards + surfaces + table_html + ing_html,
        heading="Overview",
        subtitle="Is the pipeline healthy, and what is in it. Dates are Taipei "
                 "exchange sessions, never UTC — a Taiwan session labelled in UTC is "
                 "wrong for about eight hours of every day.",
        extra_css=_OVERVIEW_CSS,
    )


# ── Market ──────────────────────────────────────────────────────────────────
#
# The self-explaining page. Every subitem states three things a bare number
# cannot: what it measures, the rule it is judged by (thresholds read from
# rg.config, never retyped here — a page that disagrees with the scorer is worse
# than no page), and what today's reading means against that rule.

_MARKET_CSS = """
.light-hero{display:flex;align-items:center;gap:18px;background:var(--surface);
  border:1px solid var(--line);border-radius:3px;padding:18px 20px;margin-bottom:8px;flex-wrap:wrap}
.orb{width:52px;height:52px;border-radius:50%;flex:none;box-shadow:0 0 0 5px color-mix(in srgb,currentColor 16%,transparent)}
.orb.green{color:var(--down);background:var(--down)}
.orb.yellow{color:var(--amber);background:var(--amber)}
.orb.red{color:var(--up);background:var(--up)}
.light-txt{flex:1;min-width:230px}
.light-txt h2{margin:0;font-size:19px;letter-spacing:-.01em}
.light-txt p{margin:3px 0 0;color:var(--slate);font-size:13px}
.score{font-family:var(--data);font-size:31px;font-variant-numeric:tabular-nums;text-align:right}
.score span{display:block;font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--slate)}
.scale{display:flex;gap:2px;margin:14px 0 26px;font-family:var(--data);font-size:10.5px}
.scale div{flex:1;padding:6px 9px;border:1px solid var(--line);color:var(--slate);background:var(--surface)}
.scale div.act{color:var(--ink);border-color:currentColor;font-weight:600}
.scale div.g.act{color:var(--down)} .scale div.y.act{color:var(--amber)} .scale div.r.act{color:var(--up)}

.sub{background:var(--surface);border:1px solid var(--line);border-radius:3px;
  padding:15px 17px;margin-bottom:9px}
.sub-top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.sub-top b{font-size:14px}
.sub-pts{margin-left:auto;font-family:var(--data);font-size:12px;padding:2px 8px;border-radius:999px;
  border:1px solid var(--line);color:var(--slate)}
.sub-pts.scored{color:var(--up);border-color:currentColor}
.sub-pts.missing{color:var(--amber);border-color:currentColor}
.what{display:block;color:var(--slate);font-size:12.5px;margin:6px 0 0;line-height:1.5}
.rule{display:block;font-family:var(--data);font-size:11.5px;color:var(--slate);
  margin-top:9px;padding:7px 10px;background:var(--surface-2);border-radius:3px;line-height:1.55}
.rule b{color:var(--ink)}
.saw{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px}
.saw div{font-family:var(--data);font-size:12px}
.saw dt{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--slate)}
.saw dd{margin:2px 0 0;font-variant-numeric:tabular-nums}
.verdict{margin-top:10px;font-size:12.5px;padding-left:11px;border-left:2px solid var(--line)}
.verdict.hit{border-color:var(--up)}
.note{color:var(--slate);font-size:12.5px;margin:0 0 14px;max-width:64ch}
.note code{font-size:11.5px}
"""

# name -> (heading, what it measures in plain words, how the rule reads).
# The rule strings interpolate rg.config so this page cannot drift from the
# scorer that actually produced the number.
_SUBITEM_DOC: dict[str, tuple[str, str, str]] = {
    "trend": (
        "Trend — is the index above its own averages?",
        "Compares the TAIEX against its 20-day and 60-day moving averages. An index "
        "under its long average is not a forecast; it is the market having already "
        "changed character.",
        "Scores <b>{p_short}</b> point below the {ma_short}-day average, "
        "<b>{p_long}</b> below the {ma_long}-day.",
    ),
    "breadth": (
        "Breadth — is the whole market rising, or just the giants?",
        "The share of stocks advancing rather than falling. A headline index can be "
        "held up by two or three heavyweights while most of the market sinks; breadth "
        "is what exposes that.",
        "Scores <b>{p_bad}</b> when the {win}-day advancing share is under "
        "<b>{bad:.0%}</b>, <b>{p_weak}</b> under <b>{weak:.0%}</b>. A single very "
        "bad day (under <b>{day_bad:.0%}</b>) also scores.",
    ),
    "margin": (
        "Margin — is borrowed money still buying a falling market?",
        "Margin balance is stock bought with borrowed money. Rising leverage in a "
        "rising market is ordinary participation. Rising leverage while the index "
        "falls is retail that has not yet given up — historically what precedes the "
        "give-up.",
        "Scores <b>{pts}</b> only when BOTH are true: {win}-day margin growth above "
        "<b>+{growth:.1f}%</b> AND the index fell over the same {win} days. TWSE "
        "publishes this after the harvest window, so a balance up to "
        "<b>{lag}</b> sessions old is accepted as current.",
    ),
    "futures": (
        "Futures — how are foreign institutions positioned?",
        "Net open interest of foreign investors in TAIEX futures. Negative means net "
        "short. This scores the <em>change</em>, not the level: the level has sat "
        "deeply short through both rallies and crashes, so it says almost nothing on "
        "its own.",
        "Scores <b>{p_heavy}</b> when foreigners added more than <b>{heavy:,}</b> "
        "contracts to their net short over {win} sessions, <b>{p_mild}</b> above "
        "<b>{mild:,}</b>.",
    ),
    "day_drop": (
        "Day drop — did today alone do damage?",
        "The single-session move in the index. A large one-day fall changes the risk "
        "picture immediately, before any multi-day average has had time to react.",
        "Scores <b>{p_heavy}</b> below <b>{heavy:.1f}%</b> on the day, "
        "<b>{p_mild}</b> below <b>{mild:.1f}%</b>.",
    ),
}


def _rule_text(name: str) -> str:
    """Fill a subitem's rule from rg.config so the page always states the real
    thresholds — including any an operator has since tuned."""
    try:
        if name == "trend":
            return _SUBITEM_DOC[name][2].format(
                p_short=cfg.PTS_BELOW_MA_SHORT, p_long=cfg.PTS_BELOW_MA_LONG,
                ma_short=cfg.MA_SHORT, ma_long=cfg.MA_LONG)
        if name == "breadth":
            return _SUBITEM_DOC[name][2].format(
                p_bad=cfg.PTS_BREADTH_BAD, p_weak=cfg.PTS_BREADTH_WEAK,
                win=cfg.BREADTH_WINDOW, bad=cfg.BREADTH_BAD, weak=cfg.BREADTH_WEAK,
                day_bad=cfg.BREADTH_DAY_BAD)
        if name == "margin":
            return _SUBITEM_DOC[name][2].format(
                pts=cfg.PTS_MARGIN, win=cfg.MARGIN_WINDOW,
                growth=cfg.MARGIN_GROWTH_PCT, lag=cfg.MARGIN_MAX_LAG_SESSIONS)
        if name == "futures":
            return _SUBITEM_DOC[name][2].format(
                p_heavy=cfg.PTS_FUT_HEAVY, p_mild=cfg.PTS_FUT_MILD,
                heavy=cfg.FUT_ADD_SHORT_HEAVY, mild=cfg.FUT_ADD_SHORT_MILD,
                win=cfg.FUT_CHANGE_WINDOW)
        if name == "day_drop":
            return _SUBITEM_DOC[name][2].format(
                p_heavy=cfg.PTS_DAY_HEAVY, p_mild=cfg.PTS_DAY_MILD,
                heavy=cfg.DAY_DROP_HEAVY, mild=cfg.DAY_DROP_MILD)
    except Exception:               # noqa: BLE001 — a missing constant must not
        log.exception("rule text failed for %s", name)   # break the whole page
    return ""


_LIGHT_MEANING = {
    "green": ("Normal conditions", "Nothing in the five checks is flashing. This is "
              "not a signal to buy — it is the absence of a reason to stop."),
    "yellow": ("Caution", "At least one check is stressed. Size positions smaller "
               "and expect the exit lines to matter."),
    "red": ("No new positions", "The market has changed character. However good a "
            "single name looks, this system's answer to a new entry is no."),
}

_NUM_LABEL = {
    "ma20": "20-day average", "ma60": "60-day average", "close": "TAIEX close",
    "adv_ratio_5d": "5-day advancing share", "adv_ratio_today": "today's share",
    "window": "window (sessions)", "margin_chg_5d_pct": "margin change 5d",
    "taiex_ret_5d_pct": "index return 5d", "margin_as_of": "margin dated",
    "fut_foreign_net_oi": "foreign net OI", "fut_net_oi_chg_5d": "net OI change 5d",
    "threshold": "threshold", "taiex_pct": "today's move",
}


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:,.4g}" if isinstance(v, float) else f"{v:,}"
    return str(v)


def market_html() -> str:
    """Today's market risk light, with every number explaining itself."""
    try:
        market = rg_db.latest_market_daily()
    except Exception:               # noqa: BLE001
        log.exception("console market: risk light unavailable")
        market = None

    if not market:
        return shell(
            "Market", "market",
            '<p class="note">No risk light has been computed yet, or the database is '
            'unreachable. The light is scored after the Taipei close by '
            '<code>python -m riskguard.pipeline --mode post_close</code>.</p>',
            heading="Market risk light",
            subtitle="Scored after every close from five independent checks.",
            extra_css=_MARKET_CSS,
        )

    light = str(market.get("risk_light") or "green")
    score = int(market.get("risk_score") or 0)
    title, meaning = _LIGHT_MEANING.get(light, ("Unknown", ""))
    as_of = escape(str(market.get("date") or "—"))

    hero = (
        f'<div class="light-hero"><div class="orb {escape(light)}"></div>'
        f'<div class="light-txt"><h2>{escape(title)}</h2><p>{escape(meaning)}</p></div>'
        f'<div class="score">{score}<span>risk score</span></div></div>'
    )
    scale = (
        '<div class="scale">'
        f'<div class="g{" act" if light == "green" else ""}">GREEN &nbsp;0–{cfg.SCORE_YELLOW - 1} pts</div>'
        f'<div class="y{" act" if light == "yellow" else ""}">YELLOW &nbsp;{cfg.SCORE_YELLOW} pts</div>'
        f'<div class="r{" act" if light == "red" else ""}">RED &nbsp;{cfg.SCORE_RED}+ pts</div>'
        '</div>'
    )

    subs = ""
    for r in (market.get("reasons") or []):
        name = str(r.get("name") or "")
        head, what, _ = _SUBITEM_DOC.get(name, (name, "", ""))
        pts = int(r.get("points") or 0)
        missing = bool(r.get("data_missing"))
        cls = "missing" if missing else ("scored" if pts else "")
        badge = "no data" if missing else (f"+{pts} pts" if pts else "0 pts")
        saw = "".join(
            f'<div><dt>{escape(_NUM_LABEL.get(k, k))}</dt><dd>{escape(_fmt(v))}</dd></div>'
            for k, v in (r.get("inputs") or {}).items()
        )
        if missing:
            verdict = ("This check could not run — the input was missing. It is "
                       "reported as absent rather than scored zero, because a "
                       "missing reading substituted with a neutral one reads as "
                       "'calm', and calm is the dangerous default for a warning system.")
        elif pts:
            verdict = f"Triggered: {r.get('detail') or ''} — added {pts} to the score."
        else:
            verdict = f"Not triggered: {r.get('detail') or ''}"
        subs += (
            f'<div class="sub"><div class="sub-top"><b>{escape(head)}</b>'
            f'<span class="sub-pts {cls}">{escape(badge)}</span></div>'
            f'<span class="what">{what}</span>'
            f'<span class="rule">{_rule_text(name)}</span>'
            f'<dl class="saw">{saw}</dl>'
            f'<p class="verdict{" hit" if pts else ""}">{escape(verdict)}</p></div>'
        )

    body = (
        f'<p class="note">Scored from the session of <b>{as_of}</b>. Every check below '
        'shows what it measures, the exact rule it is judged by, the numbers it saw, '
        'and why it did or did not add to the score. Thresholds are read from the '
        'scorer\'s own configuration, so this page cannot disagree with the number '
        'at the top.</p>'
        + hero + scale
        + '<p class="sec">The five checks</p>' + subs
        + '<p class="note" style="margin-top:20px">Risk Guard never emits a buy '
        'signal. Its best possible verdict is that nothing is stopping you — that is '
        'enforced in code, not a stylistic preference.</p>'
    )
    return shell(
        "Market", "market", body,
        heading="Market risk light",
        subtitle="A whole-market caution gauge, scored after the close from five "
                 "independent checks. It is about market conditions, not any one stock.",
        extra_css=_MARKET_CSS,
    )


# ── System map ──────────────────────────────────────────────────────────────

_FLOW_SVG = """
<figure><div class="scroll">
<svg viewBox="0 0 880 300" role="img" aria-label="Four data sources feed a scheduled harvester
that upserts into Postgres. That half runs nightly. At question time Claude calls the read-only
MCP tools, which read the database and return a stamped answer without contacting the exchange.">
<defs><marker id="ca" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
  orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>
<text x="208" y="22" text-anchor="middle" font-size="11" font-family="ui-monospace,monospace"
  letter-spacing="1.4" fill="currentColor" opacity=".6">AHEAD OF TIME — ON A SCHEDULE</text>
<text x="682" y="22" text-anchor="middle" font-size="11" font-family="ui-monospace,monospace"
  letter-spacing="1.4" fill="currentColor" opacity=".6">AT QUESTION TIME — MILLISECONDS</text>
<line x1="516" y1="36" x2="516" y2="272" stroke="currentColor" stroke-dasharray="3 5" opacity=".35"/>
<g font-size="11" font-family="ui-monospace,monospace">
<rect x="14" y="56" width="112" height="28" rx="3" fill="none" stroke="currentColor" opacity=".55"/>
<text x="70" y="74" text-anchor="middle" fill="currentColor">TWSE / TPEX</text>
<rect x="14" y="94" width="112" height="28" rx="3" fill="none" stroke="currentColor" opacity=".55"/>
<text x="70" y="112" text-anchor="middle" fill="currentColor">TAIFEX</text>
<rect x="14" y="132" width="112" height="28" rx="3" fill="none" stroke="currentColor" opacity=".55"/>
<text x="70" y="150" text-anchor="middle" fill="currentColor">MOPS · FinMind</text>
<rect x="14" y="170" width="112" height="28" rx="3" fill="none" stroke="currentColor" opacity=".55"/>
<text x="70" y="188" text-anchor="middle" fill="currentColor">12 news feeds</text>
</g>
<g stroke="currentColor" stroke-width="1.3" fill="none" marker-end="url(#ca)" opacity=".7">
<path d="M 132 70 C 158 70, 164 112, 186 120"/><path d="M 132 108 C 154 108, 162 118, 186 122"/>
<path d="M 132 146 C 154 146, 162 134, 186 128"/><path d="M 132 184 C 158 184, 164 142, 186 130"/>
</g>
<rect x="190" y="96" width="118" height="58" rx="3" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="249" y="120" text-anchor="middle" font-size="12" font-family="ui-monospace,monospace"
  fill="currentColor">harvester</text>
<text x="249" y="138" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace"
  fill="currentColor" opacity=".6">16:30 Taipei</text>
<line x1="310" y1="125" x2="374" y2="125" stroke="currentColor" stroke-width="1.3"
  marker-end="url(#ca)" opacity=".7"/>
<text x="342" y="117" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace"
  fill="currentColor" opacity=".7">upserts</text>
<g stroke="currentColor" stroke-width="1.5" fill="none">
<ellipse cx="440" cy="104" rx="54" ry="12"/>
<path d="M 386 104 L 386 146 A 54 12 0 0 0 494 146 L 494 104"/></g>
<text x="440" y="133" text-anchor="middle" font-size="12" font-family="ui-monospace,monospace"
  fill="currentColor">Postgres</text>
<line x1="496" y1="125" x2="574" y2="125" stroke="currentColor" stroke-width="1.3"
  marker-end="url(#ca)" opacity=".7"/>
<text x="537" y="117" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace"
  fill="currentColor" opacity=".7">reads</text>
<rect x="578" y="96" width="122" height="58" rx="3" fill="none" stroke="#C4342F" stroke-width="2"/>
<text x="639" y="120" text-anchor="middle" font-size="12" font-family="ui-monospace,monospace"
  fill="#C4342F">{n} MCP tools</text>
<text x="639" y="138" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace"
  fill="#C4342F" opacity=".8">read-only</text>
<line x1="702" y1="125" x2="762" y2="125" stroke="currentColor" stroke-width="1.3"
  marker-end="url(#ca)" opacity=".7"/>
<text x="732" y="117" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace"
  fill="currentColor" opacity=".7">stamped</text>
<rect x="766" y="96" width="84" height="58" rx="3" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="808" y="130" text-anchor="middle" font-size="12" font-family="ui-monospace,monospace"
  fill="currentColor">Claude</text>
<text x="639" y="256" text-anchor="middle" font-size="11" font-family="ui-monospace,monospace"
  fill="currentColor" opacity=".7">no exchange call happens while you wait</text>
</svg></div>
<figcaption>Everything left of the dashed line runs on a schedule whether or not anyone is asking.
Everything right of it runs when someone does, and never touches the exchange — which is why
answers arrive at conversation speed and exchange rate limits never reach a customer.</figcaption>
</figure>
"""


def system_map_html(tool_names: list[str]) -> str:
    """The 'how does this work' page, built from the live tool registry."""
    by_family: dict[str, list[str]] = {}
    for t in sorted(tool_names):
        by_family.setdefault(_family_of(t), []).append(t)

    fams = ""
    for key, ask, blurb in _FAMILIES:
        tools = by_family.get(key, [])
        if not tools:
            continue
        fams += (
            '<div class="fam"><div class="fam-h">'
            f'<span class="fam-k">{escape(key)}</span>'
            f'<span class="fam-n">{len(tools)} tools</span></div>'
            f'<p class="ask">{escape(ask)}</p>'
            f'<p class="tools">{escape(", ".join(tools))}</p>'
            f'<p class="tools" style="color:var(--slate);margin-top:6px">{escape(blurb)}</p>'
            '</div>'
        )

    limits = "".join(
        f'<li><span class="bar"></span><span><b>{escape(t)}</b><p>{escape(d)}</p></span></li>'
        for t, d in [
            ("Institutional flow is end-of-day. Structurally.",
             "The exchange publishes the T86 institutional-flow file once a day, near 15:00. "
             "No amount of engineering makes a flow signal intraday."),
            ("Most data is T+1.",
             "You are reading the previous trading day unless a tool says otherwise, and every "
             "response states which session it read."),
            ("Coverage is deepest on the AI supply chain.",
             "Flow screening spans the whole TWSE/TPEX market; the curated classification covers "
             "the AI names. Outside them tools answer 'unclassified' rather than guessing."),
            ("Risk Guard never emits a buy signal.",
             "Its best possible verdict is that nothing is stopping you. That is enforced in "
             "code, not a stylistic preference."),
        ]
    )

    body = (
        '<div class="prose">'
        '<p>A language model can reason about the Taiwan market but cannot see it. The exchange '
        'publishes on its own clock and rate-limits its endpoints, so the work happens '
        '<strong>before</strong> the question: a scheduled harvester pulls each session into '
        'Postgres and pre-computes the views questions actually hit.</p></div>'
        + _FLOW_SVG.replace("{n}", str(len(tool_names)))
        + '<p class="sec">What the tools answer</p>'
        f'<div class="fams">{fams}</div>'
        '<p class="sec" style="margin-top:28px">Provenance</p>'
        '<div class="prose"><p>No tool can return data without also returning where it came from '
        'and which session it belongs to — <strong>_source</strong>, <strong>_as_of</strong>, '
        '<strong>_freshness</strong> and a disclaimer ride on every response through a single '
        'choke point in the code. Dates are Taipei wall-clock, never UTC: labelling a Taiwan '
        'session with a UTC date gets it wrong for roughly eight hours of every day.</p></div>'
        '<p class="sec" style="margin-top:28px">Honest limits</p>'
        f'<ul class="limits">{limits}</ul>'
    )
    return shell(
        "System Map", "system", body,
        heading="System map",
        subtitle="How data reaches an answer, and what the surface can and cannot do. "
                 "Tool families are generated from the live registry, so this page cannot "
                 "drift from what the server actually serves.",
        extra_css=_SYSTEM_CSS,
    )
