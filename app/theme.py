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


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

:root {{ --gold:{GOLD}; --gold-deep:{GOLD_DEEP}; --midnight:{MIDNIGHT}; --ivory:{IVORY}; }}
html, body, [class*="css"], .stMarkdown, .stText, p, li, label, input, textarea, .stSelectbox, .stDataFrame {{
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
h1, h2, h3, h4, .serif {{ font-family: 'Cormorant Garamond', 'Times New Roman', serif !important; letter-spacing:.2px; color: var(--midnight); }}
.stApp {{
  background:
    radial-gradient(1200px 400px at 85% -10%, rgba(201,162,74,.12), transparent 60%),
    radial-gradient(900px 300px at -10% 0%, rgba(20,27,45,.06), transparent 60%),
    var(--ivory);
}}
.block-container {{ padding-top: 1.2rem; max-width: 1400px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* ---------- hero ---------- */
.hero {{
  position: relative; overflow: hidden; border-radius: 18px; padding: 26px 32px; margin-bottom: 18px;
  background: linear-gradient(120deg, #141B2D 0%, #1F2A44 55%, #2B2A3F 100%);
  border: 1px solid rgba(201,162,74,.45); box-shadow: 0 18px 40px -22px rgba(20,27,45,.55);
}}
.hero:after {{
  content:""; position:absolute; inset:0;
  background: repeating-linear-gradient(115deg, rgba(255,255,255,.035) 0 2px, transparent 2px 22px);
  pointer-events:none;
}}
.hero .row {{ display:flex; align-items:center; gap:18px; position:relative; z-index:1; }}
.hero h1 {{ color:#F6E7B8 !important; margin:0; font-size: 2.35rem; font-weight:600; line-height:1.1; }}
.hero .tag {{ color:#D9CDB0; font-size:.95rem; margin-top:4px; letter-spacing:.3px; }}
.hero .meta {{ margin-left:auto; text-align:right; color:#CBBF9F; font-size:.8rem; line-height:1.5; }}
.hero .meta b {{ color:#F6E7B8; font-weight:600; }}
.goldline {{ height:2px; border:0; margin: 8px 0 18px 0;
  background: linear-gradient(90deg, transparent, var(--gold), #F6E7B8, var(--gold), transparent); }}

/* ---------- KPI cards ---------- */
.kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:14px; margin: 6px 0 18px; }}
.kpi {{
  background: #FFFDF8; border:1px solid #E7DCC4; border-radius:14px; padding:14px 16px 12px;
  box-shadow: 0 6px 18px -14px rgba(122,95,30,.45); position:relative;
}}
.kpi:before {{ content:""; position:absolute; top:0; left:16px; right:16px; height:3px; border-radius:0 0 3px 3px; background: var(--accent, var(--gold)); }}
.kpi .label {{ font-size:.72rem; text-transform:uppercase; letter-spacing:1.4px; color:#6E6352; }}
.kpi .value {{ font-family:'Cormorant Garamond', serif; font-size:2rem; font-weight:700; color: var(--midnight); line-height:1.15; }}
.kpi .sub {{ font-size:.78rem; color:#7B705E; }}

/* ---------- chips ---------- */
.chip {{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; border:1px solid;
  font-size:.78rem; font-weight:600; white-space:nowrap; }}
.chip .gem {{ width:9px; height:9px; transform: rotate(45deg); border-radius:2px; display:inline-block; box-shadow: inset 0 0 0 1px rgba(255,255,255,.5); }}
.chip .gemname {{ font-weight:400; opacity:.75; }}
.chip.pri {{ padding:3px 9px; letter-spacing:.5px; }}
.code {{ display:inline-block; font: 500 .72rem 'Inter', monospace; padding:2px 8px; margin:2px 4px 2px 0; border-radius:6px;
  border:1px solid; background:#FFFDF8; }}

/* ---------- panels ---------- */
.panel {{ background:#FFFDF8; border:1px solid #E7DCC4; border-radius:16px; padding:18px 20px; margin-bottom:14px;
  box-shadow: 0 10px 24px -20px rgba(20,27,45,.4); }}
.panel h3 {{ margin: 0 0 8px; font-size:1.45rem; }}
.panel .muted {{ color:#6E6352; font-size:.86rem; }}
.facet {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px dashed #E7DCC4; font-size:.9rem; }}
.facet:last-child {{ border-bottom:0; }}
.facet span:first-child {{ color:#6E6352; }}
.facet span:last-child {{ font-weight:600; color:var(--midnight); text-align:right; }}
.amount {{ font-family:'Cormorant Garamond', serif; font-size:1.9rem; font-weight:700; }}
.var-pos {{ color:{RUBY}; }} .var-neg {{ color:{SAPPHIRE}; }} .var-zero {{ color:{EMERALD}; }}

.calc {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
.calc td {{ padding:6px 4px; border-bottom:1px solid #F0E8D6; }}
.calc td:last-child {{ text-align:right; font-variant-numeric: tabular-nums; font-weight:600; }}
.calc tr.total td {{ border-top:2px solid var(--gold); border-bottom:0; font-size:1rem; }}
.calc .f {{ color:#7B705E; font-size:.78rem; }}

.ev {{ border-left:3px solid var(--gold); background:#FBF6EA; border-radius:0 10px 10px 0; padding:8px 12px; margin:8px 0; }}
.ev .src {{ font-size:.75rem; letter-spacing:.4px; color:var(--gold-deep); font-weight:600; text-transform:uppercase; }}
.ev .q {{ font-size:.86rem; color:#2E2820; margin-top:2px; word-break: break-word; }}
.cite {{ border-left:3px solid {SAPPHIRE}; background:#F1F5FB; }}
.cite .src {{ color:{SAPPHIRE}; }}
.warn {{ border-left:3px solid {RUBY}; background:#FBEAEC; }}
.warn .src {{ color:{RUBY}; }}

.explain {{ background: linear-gradient(135deg,#FFFDF8,#F8F0DC); border:1px solid #E7DCC4; border-radius:14px; padding:14px 16px; font-size:.93rem; }}
.explain .who {{ font-size:.72rem; letter-spacing:1px; text-transform:uppercase; color:var(--gold-deep); margin-bottom:4px; }}

.ornament {{ text-align:center; color:var(--gold); letter-spacing:10px; font-size:.8rem; margin: 6px 0 2px; }}
.footer {{ text-align:center; color:#8B806C; font-size:.78rem; margin-top:28px; }}

/* ---------- streamlit widgets ---------- */
section[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #141B2D 0%, #1C2438 100%); border-right:1px solid rgba(201,162,74,.35); }}
section[data-testid="stSidebar"] * {{ color:#E9DFC6 !important; }}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{ color:#F6E7B8 !important; }}
section[data-testid="stSidebar"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] input {{ background:#222B42 !important; border-color:#4A4636 !important; }}
section[data-testid="stSidebar"] .stButton button {{ width:100%; }}
section[data-testid="stSidebar"] .stButton button, section[data-testid="stSidebar"] .stButton button * {{ color:#141B2D !important; }}
section[data-testid="stSidebar"] div[data-testid="stExpander"] {{ background:#1F2840 !important; border-color:#4A4636 !important; }}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary {{ background:#1F2840 !important; }}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] button {{ background:#2A3450 !important; }}
section[data-testid="stSidebar"] [data-testid="stAlert"] * {{ color:#141B2D !important; }}
.stButton button, .stDownloadButton button, .stFormSubmitButton button {{
  border-radius:999px; border:1px solid var(--gold); color:#141B2D; font-weight:600;
  background: linear-gradient(180deg,#F6E7B8,#D9B969); box-shadow: 0 6px 14px -10px rgba(122,95,30,.9);
}}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
  border-color:var(--gold-deep); color:#141B2D; background: linear-gradient(180deg,#FFF1C9,#CFAE5C);
}}
.stButton button:focus-visible, .stDownloadButton button:focus-visible {{ outline: 3px solid {SAPPHIRE}; outline-offset:2px; }}
.stTabs [data-baseweb="tab-list"] {{ gap:4px; border-bottom:1px solid #E7DCC4; }}
.stTabs [data-baseweb="tab"] {{ font-family:'Cormorant Garamond', serif; font-size:1.15rem; font-weight:600; color:#5E5649; padding: 8px 16px; }}
.stTabs [aria-selected="true"] {{ color: var(--midnight) !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--gold) !important; height:3px; }}
div[data-testid="stExpander"] {{ border:1px solid #E7DCC4; border-radius:12px; background:#FFFDF8; }}
div[data-testid="stDataFrame"] {{ border:1px solid #E7DCC4; border-radius:12px; overflow:hidden; }}
</style>
"""
