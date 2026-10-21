"""Visual identity: two palettes (Ivory & Gold / Onyx & Champagne) with gemstone status colours.

Ruby = FLAG, Topaz = NEEDS_REVIEW, Emerald = WITHIN_TOLERANCE, Sapphire = informational.
Colours are always paired with text labels and were chosen for WCAG AA contrast on their own background.
Styles live in style.css and only reference CSS variables, so a theme switch is a palette swap.
"""
from __future__ import annotations

import html
from pathlib import Path

from streamlit import config as st_config

# Gem accents used by Python-rendered HTML (resolve per theme through CSS variables)
GOLD, RUBY, TOPAZ, EMERALD, SAPPHIRE = "var(--gold)", "var(--ruby)", "var(--topaz)", "var(--emerald)", "var(--sapphire)"

PALETTES = {
    "light": {  # Ivory & Gold — refined boutique light
        "bg": "#F3EFE9", "paper": "#FFFFFF", "raised": "#FAF6EF", "ink": "#211C17", "muted": "#776B5B",
        "rule": "#EADFCB", "gold": "#9C7C2B", "gold-deep": "#6E521A", "gold-soft": "#F7EDD4",
        "hero": "linear-gradient(125deg,#141A2C 0%,#1E274A 58%,#30294A 100%)", "hero-ink": "#F6EAC8", "hero-muted": "#C4B896",
        "side": "linear-gradient(180deg,#121829 0%,#1A2236 100%)", "side-ink": "#E6DCC2", "side-field": "#1F2840",
        "ruby": "#A51E38", "ruby-bg": "#FBEBED", "topaz": "#8A5A00", "topaz-bg": "#FBF0D9",
        "emerald": "#1C6B4C", "emerald-bg": "#E4F1E9", "sapphire": "#1E4F93", "sapphire-bg": "#E9EFFA",
        "shadow": "0 18px 40px -28px rgba(60,45,15,.38)", "btn-ink": "#141B2D",
        "btn": "linear-gradient(180deg,#F4E4B0,#D4B055)", "btn-border": "#8A6A1E",
    },
    "dark": {  # Onyx & Champagne
        "bg": "#0D111B", "paper": "#151B28", "raised": "#1A2132", "ink": "#EEE5D0", "muted": "#A89D86",
        "rule": "#2A3247", "gold": "#D4B35E", "gold-deep": "#E6CB83", "gold-soft": "#2B2618",
        "hero": "linear-gradient(125deg,#161D2E 0%,#1D2338 55%,#2A2436 100%)", "hero-ink": "#F3E6C4", "hero-muted": "#B7AC90",
        "side": "linear-gradient(180deg,#0A0E17 0%,#111727 100%)", "side-ink": "#E2D8BF", "side-field": "#182033",
        "ruby": "#F07D8E", "ruby-bg": "rgba(240,125,142,.12)", "topaz": "#EDB65A", "topaz-bg": "rgba(237,182,90,.12)",
        "emerald": "#5CCB9B", "emerald-bg": "rgba(92,203,155,.12)", "sapphire": "#86AEEB", "sapphire-bg": "rgba(134,174,235,.12)",
        "shadow": "0 16px 36px -22px rgba(0,0,0,.8)", "btn-ink": "#141B2D",
        "btn": "linear-gradient(180deg,#EAD9A2,#C9A54E)", "btn-border": "#F0D98F",
    },
}

# Native Streamlit widgets (dataframes, inputs, selects) follow the Streamlit theme, so mirror the palette there.
NATIVE = {
    "light": {"base": "light", "primaryColor": "#9C7C2B", "backgroundColor": "#F3EFE9", "secondaryBackgroundColor": "#FAF6EF",
              "textColor": "#211C17", "borderColor": "#EADFCB", "dataframeHeaderBackgroundColor": "#F3EBD9"},
    "dark": {"base": "dark", "primaryColor": "#D4B35E", "backgroundColor": "#0D111B", "secondaryBackgroundColor": "#1A2132",
             "textColor": "#EEE5D0", "borderColor": "#2A3247", "dataframeHeaderBackgroundColor": "#1A2132"},
}

STATUS = {"FLAG": ("Ruby", "flag", "Flagged"), "NEEDS_REVIEW": ("Topaz", "review", "Needs review"),
          "WITHIN_TOLERANCE": ("Emerald", "ok", "Within tolerance")}
PRIORITY = {"P1": "flag", "P2": "review", "P3": "info"}
DECISION = {"pending": "neutral", "approved": "ok", "rejected": "flag", "escalated": "info", "needs_info": "review"}
SEVERITY = {"critical": "flag", "high": "flag", "medium": "review", "low": "info", "info": "neutral"}

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

_STYLE = Path(__file__).with_name("style.css")


def diamond(size: int = 40, uid: str = "a") -> str:
    return DIAMOND_SVG.format(s=size, uid=uid)


def esc(v: object) -> str:
    """Escape any document-derived value before HTML rendering (vendor text is untrusted)."""
    return html.escape("" if v is None else str(v))


def css(mode: str) -> str:
    pal = PALETTES[mode]
    root = ":root{" + "".join(f"--{k}:{v};" for k, v in pal.items()) + f"color-scheme:{mode};}}"
    return f"<style>{_STYLE.read_text(encoding='utf-8')}\n{root}</style>"  # @import must stay first


def apply_native_theme(mode: str) -> None:
    """Point Streamlit's own theme at the palette (process-wide; fine for a local single-user tool)."""
    for k, v in NATIVE[mode].items():
        st_config.set_option(f"theme.{k}", v)
    st_config.set_option("theme.baseRadius", "0.75rem")
    # The sidebar is a midnight "vitrine" in both modes
    for k, v in {"backgroundColor": "#121829", "secondaryBackgroundColor": "#1F2840", "textColor": "#E6DCC2",
                 "borderColor": "#3A3A3A", "primaryColor": "#D4B35E"}.items():
        st_config.set_option(f"theme.sidebar.{k}", v)


def native_theme_mode() -> str:
    return "dark" if st_config.get_option("theme.base") == "dark" else "light"


def status_chip(status: str) -> str:
    gem, cls, label = STATUS.get(status, ("", "neutral", status))
    return f'<span class="chip t-{cls}"><span class="gem"></span>{esc(label)}<span class="gemname">· {gem}</span></span>'


def priority_chip(p: str) -> str:
    return f'<span class="chip solid t-{PRIORITY.get(p, "neutral")}">{esc(p)}</span>'


def decision_chip(d: str, stale: bool = False) -> str:
    label = d.replace("_", " ").title() + (" · stale" if stale else "")
    return f'<span class="chip t-{DECISION.get(d, "neutral")}">{esc(label)}</span>'


def code_chip(code: str, severity: str = "info") -> str:
    return f'<span class="code t-{SEVERITY.get(severity, "neutral")}">{esc(code)}</span>'
