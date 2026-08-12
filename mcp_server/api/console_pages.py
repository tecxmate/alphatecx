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
from html import escape

try:
    import db_v2
    from console import NAV, shell
except ModuleNotFoundError:      # package import path used by local tests
    from . import db_v2
    from .console import NAV, shell

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
table.freshness td.n{font-family:var(--data);font-variant-numeric:tabular-nums;text-align:right}
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

def _pipeline_rows() -> list[dict] | None:
    """Per-table freshness, or None when the database cannot be reached."""
    try:
        return db_v2.query_data_status()
    except Exception:               # noqa: BLE001 — a console must not 500
        log.exception("console overview: data status unavailable")
        return None


def overview_html(ticker_count: int) -> str:
    rows = _pipeline_rows()

    if rows is None:
        cards = (
            '<dl class="cards"><div class="card"><dt>Pipeline</dt>'
            '<dd class="bad">unreachable</dd>'
            '<span class="sub">the database did not answer — the page still lists '
            'what exists</span></div></dl>'
        )
        table = ""
    else:
        tables = len(rows)
        total = sum(int(r.get("row_count") or 0) for r in rows)
        latest = max((str(r.get("latest_date") or "") for r in rows), default="")
        cards = (
            '<dl class="cards">'
            f'<div class="card"><dt>Tables tracked</dt><dd>{tables}</dd></div>'
            f'<div class="card"><dt>Rows stored</dt><dd>{total:,}</dd></div>'
            f'<div class="card"><dt>Most recent session</dt><dd>{escape(latest) or "—"}'
            '<span class="sub">Asia/Taipei</span></dd></div>'
            f'<div class="card"><dt>Ticker pages</dt><dd>{ticker_count}</dd>'
            '<span class="sub">pre-rendered nightly</span></div>'
            '</dl>'
        )
        body = "".join(
            "<tr><td>{name}</td><td class='n'>{n:,}</td><td class='n'>{d}</td></tr>".format(
                name=escape(str(r.get("table_name") or r.get("source") or "—")),
                n=int(r.get("row_count") or 0),
                d=escape(str(r.get("latest_date") or "—")),
            )
            for r in rows
        )
        table = (
            '<p class="sec">Freshness by table</p><div class="scroll">'
            '<table class="freshness"><thead><tr><th>Table</th><th style="text-align:right">Rows</th>'
            '<th style="text-align:right">Latest</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>'
        )

    tiles = "".join(
        f'<a class="tile" href="{escape(href)}"><b>{escape(label)}</b>'
        f'<span>{escape(purpose)}</span></a>'
        for key, href, label, purpose in NAV if key != "home"
    )

    body = (
        f'{cards}'
        f'<p class="sec">Surfaces</p><div class="tiles">{tiles}</div>'
        f'{table}'
    )
    return shell(
        "alphatecx Console", "home", body,
        heading="Overview",
        subtitle="Pipeline health and every surface in one place. Data is harvested "
                 "after the Taipei close; dates below are exchange sessions, not UTC.",
        extra_css=_OVERVIEW_CSS,
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
