"""The operator console shell — one navigation frame around every web surface.

Before this, the web surfaces were five unrelated documents at three different
path prefixes (`/d/`, `/g/`, `/t/`), each a full HTML page with its own header
and no link to the others. Finding anything meant knowing its URL, and there was
no page that told you what existed. This module supplies the missing frame:

  * `NAV` is the information architecture in one place — the single list every
    surface renders from, so a new page appears in every page's sidebar at once.
  * `shell()` wraps content Claude-side pages own outright (home, system map).
  * `inject_nav()` retrofits the same bar onto the pre-rendered documents built
    by `src.dashboard.*`, which are generated on the harvester side and cannot
    import this module (see the deployment split in CLAUDE.md).

Every nav link is RELATIVE (`./`, `./graph`). That is what lets a static file
generated hours earlier by a different process, with no knowledge of the bearer
token, still link correctly once served under `/d/<token>/` — the alternative
was threading the token through the generators and rebuilding on rotation.

Palette follows the Taiwan exchange convention deliberately: red is up, green is
down. A Western red/green scheme reads inverted to this system's only audience.
"""
from __future__ import annotations

from html import escape

# ── Information architecture ────────────────────────────────────────────────
# (key, relative href, label, one-line purpose shown on the console home)
NAV: list[tuple[str, str, str, str]] = [
    ("home",    "./",         "Overview",   "Pipeline health and where everything lives"),
    ("flow",    "./flow",     "Flow",       "Watchlist, theses, discovery and lead-lag"),
    ("graph",   "./graph",    "Graph",      "3D correlation map of the classified universe"),
    ("tickers", "./tickers",  "Tickers",    "Every pre-rendered per-ticker detail page"),
    ("system",  "./system",   "System",     "How the pipeline works and what the tools answer"),
]

_SHELL_CSS = """
:root{
  --paper:#F1F2F4; --surface:#FFF; --surface-2:#E8EAEE; --ink:#14181D;
  --slate:#5B6672; --line:#D3D7DD; --up:#C4342F; --down:#2A7A6B; --amber:#A8791F;
  --nav-w:212px;
  --data:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --body:system-ui,-apple-system,"Segoe UI","PingFang TC",sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#101318; --surface:#171B21; --surface-2:#1F242B; --ink:#E9ECF0;
  --slate:#99A3AF; --line:#2B313A; --up:#F2685F; --down:#5FBBA6; --amber:#D9AB4E;
}}
:root[data-theme="dark"]{
  --paper:#101318; --surface:#171B21; --surface-2:#1F242B; --ink:#E9ECF0;
  --slate:#99A3AF; --line:#2B313A; --up:#F2685F; --down:#5FBBA6; --amber:#D9AB4E;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);
  font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
:focus-visible{outline:2px solid var(--up);outline-offset:2px}

/* Sidebar — the frame every surface shares */
.atx-nav{position:fixed;inset:0 auto 0 0;width:var(--nav-w);background:var(--surface);
  border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:50}
.atx-brand{padding:16px 18px 14px;border-bottom:1px solid var(--line)}
.atx-brand b{display:block;font-size:14px;letter-spacing:-.01em}
.atx-brand span{display:block;font-family:var(--data);font-size:10px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--slate);margin-top:3px}
.atx-links{display:flex;flex-direction:column;padding:8px;gap:1px;flex:1}
.atx-links a{display:block;padding:7px 10px;border-radius:3px;text-decoration:none;
  font-size:13px;color:var(--slate)}
.atx-links a:hover{background:var(--surface-2);color:var(--ink)}
.atx-links a[aria-current="page"]{background:var(--surface-2);color:var(--ink);
  font-weight:600;box-shadow:inset 2px 0 0 var(--up)}
.atx-foot{padding:10px 12px;border-top:1px solid var(--line);display:flex;
  align-items:center;justify-content:space-between;gap:8px}
.atx-foot button{font-family:var(--data);font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;background:none;border:1px solid var(--line);color:var(--slate);
  padding:4px 8px;border-radius:3px;cursor:pointer}
.atx-foot button:hover{color:var(--ink);border-color:var(--slate)}

.atx-main{margin-left:var(--nav-w);min-height:100vh}
.atx-page{padding:26px 30px 60px;max-width:1180px}
.atx-h{margin:0 0 4px;font-size:21px;letter-spacing:-.015em}
.atx-sub{margin:0 0 24px;color:var(--slate);font-size:13px;max-width:62ch}

@media (max-width:860px){
  .atx-nav{position:static;width:auto;flex-direction:row;align-items:center;
    border-right:0;border-bottom:1px solid var(--line);overflow-x:auto}
  .atx-brand{border-bottom:0;border-right:1px solid var(--line);white-space:nowrap;padding:10px 14px}
  .atx-links{flex-direction:row;flex:1}
  .atx-links a{white-space:nowrap}
  .atx-links a[aria-current="page"]{box-shadow:inset 0 -2px 0 var(--up)}
  .atx-main{margin-left:0}
  .atx-page{padding:18px 16px 48px}
}
"""

_THEME_JS = """
(function(){
  var K='atx-theme',r=document.documentElement,s=null;
  try{s=localStorage.getItem(K)}catch(e){}
  if(s){r.setAttribute('data-theme',s)}
  var b=document.getElementById('atx-theme');
  if(!b)return;
  function lab(){
    var d=r.getAttribute('data-theme');
    if(!d)d=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
    b.textContent=d==='dark'?'Light':'Dark';
  }
  lab();
  b.addEventListener('click',function(){
    var d=r.getAttribute('data-theme');
    if(!d)d=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
    var n=d==='dark'?'light':'dark';
    r.setAttribute('data-theme',n);
    try{localStorage.setItem(K,n)}catch(e){}
    lab();
  });
})();
"""


def nav_html(active: str) -> str:
    """The sidebar. `active` marks the current page for both styling and a11y."""
    links = "".join(
        '<a href="{href}"{cur}>{label}</a>'.format(
            href=escape(href),
            cur=' aria-current="page"' if key == active else "",
            label=escape(label),
        )
        for key, href, label, _ in NAV
    )
    return (
        '<nav class="atx-nav" aria-label="Console">'
        '<div class="atx-brand"><b>alphatecx</b><span>Console</span></div>'
        f'<div class="atx-links">{links}</div>'
        '<div class="atx-foot">'
        '<button id="atx-theme" type="button">Dark</button>'
        '</div></nav>'
    )


def shell(title: str, active: str, body: str, *, heading: str = "",
          subtitle: str = "", extra_css: str = "") -> str:
    """A full console page. Used by surfaces this module owns outright."""
    head = ""
    if heading:
        head = f'<h1 class="atx-h">{escape(heading)}</h1>'
        if subtitle:
            head += f'<p class="atx-sub">{escape(subtitle)}</p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title>'
        f'<style>{_SHELL_CSS}{extra_css}</style></head><body>'
        f'{nav_html(active)}'
        f'<main class="atx-main"><div class="atx-page">{head}{body}</div></main>'
        f'<script>{_THEME_JS}</script></body></html>'
    )


def inject_nav(html: str, active: str) -> str:
    """Retrofit the console frame onto a page generated elsewhere.

    The flow dashboard, the 3D graph and the per-ticker pages are complete HTML
    documents produced by `src.dashboard.*` and `graph_view` — rewriting them all
    to use `shell()` would mean touching four generators and regenerating every
    committed static file. Instead the nav is spliced in after `<body>` and the
    content offset by the sidebar width.

    Returns the input unchanged when there is no `<body>` to splice into, so a
    malformed or unexpected document degrades to "no nav" rather than to a
    corrupted page.
    """
    lower = html.lower()
    idx = lower.find("<body")
    if idx == -1:
        return html
    end = lower.find(">", idx)
    if end == -1:
        return html
    end += 1
    # Scope the offset to a wrapper so the host page's own body rules survive.
    css = (
        f"<style>{_SHELL_CSS}"
        ".atx-nav{font-size:14px}"
        "body>*:not(.atx-nav):not(script){margin-left:var(--nav-w)}"
        "@media (max-width:860px){body>*:not(.atx-nav):not(script){margin-left:0}}"
        "</style>"
    )
    tail = f"<script>{_THEME_JS}</script>"
    return html[:end] + css + nav_html(active) + html[end:] + tail
