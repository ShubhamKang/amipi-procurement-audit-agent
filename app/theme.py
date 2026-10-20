"""Visual identity: ivory, champagne gold and midnight, with gemstone status colours.

Ruby = FLAG, Topaz = NEEDS_REVIEW, Emerald = WITHIN_TOLERANCE, Sapphire = informational.
All colours are paired with text labels (never colour alone) and meet WCAG AA contrast on ivory.
"""
from __future__ import annotations

import html

GOLD = "#A8862F"
GOLD_DEEP = "#7A5F1E"
MIDNIGHT = "#141B2D"
IVORY = "#FBF8F2"
RUBY = "#9B1B30"
TOPAZ = "#8A5A00"
EMERALD = "#1F6B4F"
SAPPHIRE = "#1F4E8C"

STATUS = {
    "FLAG": ("Ruby", RUBY, "#FBEAEC", "Flagged"),
    "NEEDS_REVIEW": ("Topaz", TOPAZ, "#FDF3DF", "Needs review"),
    "WITHIN_TOLERANCE": ("Emerald", EMERALD, "#E6F3EC", "Within tolerance"),
}
PRIORITY = {"P1": RUBY, "P2": TOPAZ, "P3": SAPPHIRE}
DECISION = {"pending": ("#5E5649", "#EFEAE0"), "approved": (EMERALD, "#E6F3EC"), "rejected": (RUBY, "#FBEAEC"),
            "escalated": (SAPPHIRE, "#E7EEF8"), "needs_info": (TOPAZ, "#FDF3DF")}

DIAMOND_SVG = """
<svg width="{s}" height="{s}" viewBox="0 0 64 64" role="img" aria-label="diamond" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g{uid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#F6E7B8"/><stop offset=".5" stop-color="#C9A24A"/><stop offset="1" stop-color="#7A5F1E"/>
    </linearGradient>
  </defs>
  <path d="M14 8h36l12 16-30 34L2 24z" fill="url(#g{uid})" stroke="#5C4714" stroke-width="1.2"/>
  <path d="M2 24h60M14 8l8 16 10 34M50 8l-8 16-10 34M22 24l10-16 10 16" fill="none" stroke="#FFF8E1" stroke-opacity=".85" stroke-width="1.1"/>
</svg>
"""


def diamond(size: int = 40, uid: str = "a") -> str:
    return DIAMOND_SVG.format(s=size, uid=uid)


def esc(v: object) -> str:
    """Escape any document-derived value before HTML rendering (vendor text is untrusted)."""
    return html.escape("" if v is None else str(v))


def status_chip(status: str) -> str:
    gem, fg, bg, label = STATUS.get(status, ("", "#333", "#eee", status))
    return (f'<span class="chip" style="color:{fg};background:{bg};border-color:{fg}33">'
            f'<span class="gem" style="background:{fg}"></span>{esc(label)}<span class="gemname">· {gem}</span></span>')


def priority_chip(p: str) -> str:
    c = PRIORITY.get(p, "#555")
    return f'<span class="chip pri" style="color:#fff;background:{c};border-color:{c}">{esc(p)}</span>'


def decision_chip(d: str, stale: bool = False) -> str:
    fg, bg = DECISION.get(d, ("#333", "#eee"))
    label = d.replace("_", " ").title() + (" · stale" if stale else "")
    return f'<span class="chip" style="color:{fg};background:{bg};border-color:{fg}33">{esc(label)}</span>'


def code_chip(code: str, severity: str = "info") -> str:
    col = {"critical": RUBY, "high": RUBY, "medium": TOPAZ, "low": SAPPHIRE, "info": "#5E5649"}.get(severity, "#5E5649")
    return f'<span class="code" style="color:{col};border-color:{col}55">{esc(code)}</span>'


# Typography (all sans, classic maison style):
#   Josefin Sans – Art-Deco display caps (wordmark, labels, tabs)
#   Jost         – geometric, Futura-like headings and figures
#   Mulish       – quiet, highly legible body text
DISPLAY = "'Josefin Sans', 'Futura', 'Century Gothic', sans-serif"
HEAD = "'Jost', 'Futura', 'Avenir Next', sans-serif"
BODY = "'Mulish', 'Avenir', 'Segoe UI', system-ui, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@400;600;700&family=Jost:wght@400;500;600&family=Mulish:wght@400;500;600;700&display=swap');

:root {{ --gold:{GOLD}; --gold-deep:{GOLD_DEEP}; --midnight:{MIDNIGHT}; --ivory:{IVORY}; --rule:#D9CCAE; --paper:#FFFDF8; }}
html, body, [class*="css"], .stMarkdown, .stText, p, li, label, input, textarea, .stSelectbox, .stDataFrame {{
  font-family: {BODY};
}}
h1, h2, h3, h4 {{ font-family: {HEAD} !important; font-weight:500 !important; color: var(--midnight); letter-spacing:.2px; }}
.stApp {{ background: var(--ivory); }}

/* ---------- full-width canvas: remove Streamlit's side gutters ---------- */
.block-container, [data-testid="stMainBlockContainer"] {{
  max-width: 100% !important; padding: 0.9rem 1.4rem 2rem 1.4rem !important;
}}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}

/* ---------- masthead: midnight band framed by a double gold rule ---------- */
.hero {{
  position: relative; padding: 22px 28px; margin: 0 0 0 0; background: var(--midnight);
  border-top: 3px double var(--gold); border-bottom: 3px double var(--gold);
}}
.hero:before, .hero:after {{
  content:""; position:absolute; width:18px; height:18px; border: 1px solid var(--gold);
}}
.hero:before {{ top:8px; left:8px; border-right:0; border-bottom:0; }}
.hero:after {{ bottom:8px; right:8px; border-left:0; border-top:0; }}
.hero .row {{ display:flex; align-items:center; gap:20px; }}
.hero .eyebrow {{ font-family:{DISPLAY}; font-size:.7rem; letter-spacing:5px; text-transform:uppercase; color:var(--gold); }}
.hero h1 {{ font-family:{DISPLAY} !important; color:#F3E6C4 !important; margin:4px 0 2px; font-size:1.75rem; white-space:nowrap;
  font-weight:600 !important; letter-spacing:4px; text-transform:uppercase; line-height:1.15; padding:0; }}
.hero .tag {{ color:#C9BEA2; font-size:.9rem; letter-spacing:.3px; }}
.hero .meta {{ margin-left:auto; text-align:right; color:#A99E84; font-size:.74rem; line-height:1.8;
  border-left:1px solid rgba(168,134,47,.5); padding-left:20px; text-transform:uppercase; letter-spacing:1.5px; }}
.hero .meta b {{ color:#F3E6C4; font-weight:600; font-family:{HEAD}; letter-spacing:.5px; text-transform:none; font-size:.82rem; }}
.wordmark {{ font-family:{DISPLAY}; font-size:1.25rem; font-weight:700; letter-spacing:6px; color:#F3E6C4; line-height:1; }}
.goldline {{ height:0; border:0; border-top:1px solid var(--gold); margin: 6px 0 14px; }}

/* ---------- KPI ledger: one ruled strip, no floating cards ---------- */
.kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 0 0 18px;
  background: var(--paper); border-bottom:1px solid var(--rule); }}
.kpi {{ display:flex; flex-direction:column; padding:14px 18px 12px; border-right:1px solid var(--rule); position:relative; }}
.kpi:last-child {{ border-right:0; }}
.kpi:before {{ content:""; position:absolute; top:16px; left:18px; width:7px; height:7px; transform:rotate(45deg); background:var(--accent, var(--gold)); }}
.kpi .label {{ font-family:{DISPLAY}; font-size:.64rem; text-transform:uppercase; letter-spacing:1.6px; color:#6E6352; padding-left:16px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .value {{ font-family:{HEAD}; font-size:2rem; font-weight:400; color: var(--midnight); line-height:1.2;
  font-variant-numeric: tabular-nums lining-nums; margin-top:4px; }}
.kpi .sub {{ font-size:.74rem; color:#7B705E; }}

/* ---------- chips: lozenge tags with a cut-gem marker ---------- */
.chip {{ display:inline-flex; align-items:center; gap:7px; padding:3px 10px; border-radius:2px; border:1px solid;
  font-family:{DISPLAY}; font-size:.7rem; font-weight:600; letter-spacing:1.2px; text-transform:uppercase; white-space:nowrap; }}
.chip .gem {{ width:8px; height:8px; transform: rotate(45deg); display:inline-block; }}
.chip .gemname {{ font-weight:400; opacity:.7; }}
.chip.pri {{ padding:3px 8px; letter-spacing:1.5px; }}
.code {{ display:inline-block; font: 600 .68rem {HEAD}; letter-spacing:.6px; padding:2px 7px; margin:2px 4px 2px 0;
  border-radius:0; border:1px solid; background:var(--paper); }}

/* ---------- panels: ruled paper sheets ---------- */
.panel {{ background:var(--paper); border:1px solid var(--rule); border-top:2px solid var(--midnight); padding:16px 20px; margin-bottom:14px; }}
.panel h3 {{ margin: 0 0 10px; font-family:{DISPLAY} !important; font-size:.82rem; font-weight:700 !important;
  letter-spacing:3px; text-transform:uppercase; color:var(--gold-deep); padding-bottom:8px; border-bottom:1px solid var(--rule); }}
.panel .muted {{ color:#6E6352; font-size:.85rem; }}
.facet {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px dotted var(--rule); font-size:.88rem; }}
.facet:last-child {{ border-bottom:0; }}
.facet span:first-child {{ color:#6E6352; }}
.facet span:last-child {{ font-weight:600; color:var(--midnight); text-align:right; }}
.amount {{ font-family:{HEAD}; font-size:1.85rem; font-weight:400; font-variant-numeric: tabular-nums; }}
.var-pos {{ color:{RUBY}; }} .var-neg {{ color:{SAPPHIRE}; }} .var-zero {{ color:{EMERALD}; }}

.calc {{ width:100%; border-collapse:collapse; font-size:.87rem; }}
.calc td {{ padding:6px 4px; border-bottom:1px dotted var(--rule); }}
.calc td:last-child {{ text-align:right; font-family:{HEAD}; font-variant-numeric: tabular-nums; font-weight:500; }}
.calc tr.total td {{ border-top:3px double var(--gold); border-bottom:0; font-size:1rem; font-weight:600; }}
.calc .f {{ color:#7B705E; font-size:.76rem; }}

.ev {{ border-left:2px solid var(--gold); background:#F8F2E3; padding:8px 12px; margin:8px 0; }}
.ev .src {{ font-family:{DISPLAY}; font-size:.66rem; letter-spacing:1.8px; color:var(--gold-deep); font-weight:700; text-transform:uppercase; }}
.ev .q {{ font-size:.85rem; color:#2E2820; margin-top:3px; word-break: break-word; }}
.cite {{ border-left-color:{SAPPHIRE}; background:#EFF3F9; }}
.cite .src {{ color:{SAPPHIRE}; }}
.warn {{ border-left-color:{RUBY}; background:#FAECEE; }}
.warn .src {{ color:{RUBY}; }}

.explain {{ background:var(--paper); border:1px solid var(--rule); border-left:3px double var(--gold); padding:12px 16px; font-size:.92rem; }}
.explain .who {{ font-family:{DISPLAY}; font-size:.64rem; letter-spacing:2.2px; text-transform:uppercase; color:var(--gold-deep); margin-bottom:4px; }}

.ornament {{ text-align:center; color:var(--gold); letter-spacing:12px; font-size:.7rem; margin: 8px 0 4px; }}
.footer {{ text-align:center; color:#8B806C; font-family:{DISPLAY}; font-size:.68rem; letter-spacing:2px; text-transform:uppercase; margin-top:28px; }}

/* ---------- sidebar: midnight vitrine ---------- */
section[data-testid="stSidebar"] {{ background: var(--midnight); border-right:1px solid var(--gold); }}
section[data-testid="stSidebar"] * {{ color:#E2D8BF !important; }}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
  font-family:{DISPLAY} !important; color:#F3E6C4 !important; letter-spacing:3px; text-transform:uppercase; font-size:.95rem !important; }}
section[data-testid="stSidebar"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] input {{ background:#1D2539 !important; border-color:#4A4636 !important; border-radius:2px !important; }}
section[data-testid="stSidebar"] .stButton button {{ width:100%; }}
section[data-testid="stSidebar"] .stButton button, section[data-testid="stSidebar"] .stButton button * {{ color:#141B2D !important; }}
section[data-testid="stSidebar"] div[data-testid="stExpander"],
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary {{ background:#1A2134 !important; border-color:#4A4636 !important; }}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] button {{ background:#262F48 !important; }}
section[data-testid="stSidebar"] [data-testid="stAlert"] * {{ color:#141B2D !important; }}

/* ---------- buttons, tabs, tables ---------- */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {{
  border-radius:2px; border:1px solid var(--gold); color:#141B2D; background:#E9D597;
  font-family:{DISPLAY}; font-weight:700; letter-spacing:2px; text-transform:uppercase; font-size:.74rem; box-shadow:none;
}}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
  border-color:var(--midnight); color:#F3E6C4; background:var(--midnight);
}}
.stButton button:hover *, .stDownloadButton button:hover *, .stFormSubmitButton button:hover * {{ color:#F3E6C4 !important; }}
.stButton button:focus-visible, .stDownloadButton button:focus-visible {{ outline: 3px solid {SAPPHIRE}; outline-offset:2px; }}
.stTabs [data-baseweb="tab-list"] {{ gap:0; border-bottom:1px solid var(--rule); }}
.stTabs [data-baseweb="tab"] {{ font-family:{DISPLAY}; font-size:.78rem; font-weight:600; letter-spacing:2.4px;
  text-transform:uppercase; color:#6E6352; padding: 10px 20px; }}
.stTabs [data-baseweb="tab"] p {{ font-family:{DISPLAY}; font-size:.78rem; letter-spacing:2.4px; }}
.stTabs [aria-selected="true"] {{ color: var(--midnight) !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--gold) !important; height:2px; }}
div[data-testid="stExpander"] {{ border:1px solid var(--rule); border-radius:0; background:var(--paper); }}
div[data-testid="stDataFrame"] {{ border:1px solid var(--rule); border-radius:0; }}
[data-baseweb="input"], [data-baseweb="select"] > div, textarea {{ border-radius:2px !important; }}
</style>
"""
