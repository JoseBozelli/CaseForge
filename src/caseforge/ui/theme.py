"""Visual theme for the operator console: fonts, colors and small HTML components.

Every value inserted into HTML is escaped: run records contain model-written text.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

ACCENT = "#1a5c3a"
FONTS = (
    "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600"
    "&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500&display=swap"
)
STATUS_STYLES = {
    "completed": ("#e6f2ea", ACCENT),
    "awaiting_approval": ("#fdf3e1", "#8a5a00"),
    "halted": ("#fbe7e6", "#9b2c2c"),
    "interrupted": ("#eef0f2", "#4a5560"),
}

CSS = f"""
<style>
@import url('{FONTS}');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
  font-family: 'Outfit', 'Poppins', sans-serif; font-weight: 300;
}}
h1, h2, h3 {{
  font-family: 'Cormorant Garamond', 'Lora', serif !important; font-weight: 600 !important;
  color: #1f2421; letter-spacing: 0.01em;
}}
code, pre, [data-testid="stMetricValue"] {{ font-family: 'DM Mono', monospace !important; }}
#MainMenu, footer, [data-testid="stDeployButton"] {{ visibility: hidden; }}
[data-testid="stSidebar"] {{ background: #f1f4f0; border-right: 1px solid #e3e7e1; }}
.block-container {{ padding-top: 2rem; max-width: 1200px; }}
.cf-brand {{
  font-family: 'Cormorant Garamond', serif; font-size: 1.7rem; font-weight: 600;
  color: {ACCENT};
}}
.cf-card {{
  background: #ffffff; border: 1px solid #e3e7e1; border-radius: 14px; padding: 1rem 1.2rem;
  box-shadow: 0 1px 2px rgba(16,24,20,0.04), 0 4px 16px rgba(16,24,20,0.04); margin-bottom: 1rem;
}}
.cf-card h4 {{
  margin: 0 0 0.35rem 0; font-family: 'Outfit', sans-serif; font-weight: 500; font-size: 0.75rem;
  letter-spacing: 0.08em; text-transform: uppercase; color: #5b665f;
}}
.cf-value {{ font-family: 'DM Mono', monospace; font-size: 1.05rem; color: #1f2421; }}
.cf-muted {{ color: #5b665f; font-size: 0.85rem; }}
.cf-badge {{
  display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px;
  font-size: 0.8rem; font-weight: 500; vertical-align: middle;
}}
.cf-steps {{
  list-style: none; padding-left: 0; margin: 0.3rem 0 0 0.4rem;
  border-left: 2px solid #d6ded8;
}}
.cf-steps li {{ position: relative; padding: 0.35rem 0 0.35rem 1rem; }}
.cf-steps li::before {{
  content: ""; position: absolute; left: -6px; top: 0.8rem; width: 10px; height: 10px;
  border-radius: 50%; background: {ACCENT};
}}
</style>
"""


def esc(value: Any) -> str:
    return html.escape(str(value))


def badge(status: str) -> str:
    background, color = STATUS_STYLES.get(status, ("#eef0f2", "#4a5560"))
    return (
        f'<span class="cf-badge" style="background:{background};color:{color}">'
        f"{esc(status.replace('_', ' '))}</span>"
    )


def card(title: str, value: Any, note: Any = None) -> str:
    extra = f'<div class="cf-muted">{esc(note)}</div>' if note else ""
    return (
        f'<div class="cf-card"><h4>{esc(title)}</h4>'
        f'<div class="cf-value">{esc(value)}</div>{extra}</div>'
    )


def timeline(trace: Sequence[Mapping[str, Any]]) -> str:
    items = []
    for step in trace:
        details = ", ".join(f"{esc(k)}: {esc(v)}" for k, v in step.items() if k != "node")
        node = esc(step.get("node", ""))
        items.append(f"<li><strong>{node}</strong> <span class='cf-muted'>{details}</span></li>")
    return f"<ul class='cf-steps'>{''.join(items)}</ul>"
