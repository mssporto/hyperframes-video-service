"""Brand-agnostic visual theme for the HyperFrames templates in `templates/`.

Every template in this repo is theme-driven (colour, font, and logo are all
`{{THEME_*}}`/`{{LOGO_MARKUP}}` placeholders, never hardcoded) -- there is no
separate "house style" template set to fall back to. A theme is a plain dict:

    bg           the single flat ground        (never force-corrected)
    text         primary headline text         (AA-enforced vs bg)
    lead_text    secondary / lead-in text      (AA-enforced vs bg)
    accent       the single brand accent       (never force-corrected)
    accent_text  text/icon colour ON accent    (AA-enforced vs accent)
    font_family  brand typeface (CSS value)
    logo_url     a real logo URL, or "" for no logo

An LLM can propose bg/text/accent/font from free-text brand guidelines
(derive_theme, below); deterministic code then GUARANTEES every
text/background pairing clears WCAG AA, forcing the TEXT colour (never a
background, never the accent) to pure black or white if the model's proposal
fails. If you don't want to run an LLM at all, just build a theme dict by
hand (or start from DEFAULT_THEME) and pass it straight to
builder.hyperframes_project_builder.build_project().
"""

import json
import re

from builder.theme_common import _HEX_RE, _readable_text_for, contrast_ratio  # noqa: F401
from builder.llm_providers import call_text_capability

# A ready-to-use neutral theme -- pick this when you don't want to configure
# (or LLM-derive) a brand theme at all. Dark ground, white text, a plain
# blue accent, system font stack, no logo.
DEFAULT_THEME = {
    "bg": "#111111",
    "text": "#FFFFFF",
    "lead_text": "#9A9A9A",
    "accent": "#3B82F6",
    "accent_text": "#FFFFFF",
    "font_family": "Inter, ui-sans-serif, system-ui, sans-serif",
    "logo_url": "",
}

_FONT_GENERICS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy",
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded",
    "-apple-system", "blinkmacsystemfont",
}

_SYSTEM = (
    "You are a brand-colour interpreter for short-form vertical video. Given a "
    "brand's visual guidelines (colours, typography), propose a single-ground "
    "video theme: one flat background colour that fills every frame, the primary "
    "headline text colour on it, a secondary 'lead-in' text colour on it (a "
    "quieter, de-emphasised tone -- e.g. a mid grey -- used for supporting "
    "lines), one single accent colour (the brand's signature colour, used for "
    "emphasis words, the progress bar, and a solid call-to-action rectangle), "
    "the text colour that sits ON that accent rectangle, and the brand's primary "
    "typeface.\n\n"
    "Return ONLY this JSON object, no fences, no commentary:\n"
    '{"bg": "#RRGGBB", "text": "#RRGGBB", "lead_text": "#RRGGBB", '
    '"accent": "#RRGGBB", "accent_text": "#RRGGBB", '
    '"font_family": "string, real CSS font-family value with a generic '
    'fallback, e.g. \\"Lato, ui-sans-serif, system-ui, sans-serif\\""}'
)


def parse_theme_response(text):
    """Parse the model's proposed video-theme JSON; raise ValueError if impossible."""
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.DOTALL)
    if fence:
        s = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", s, re.DOTALL)
        if brace:
            s = brace.group(0)
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse theme JSON: {e}") from e

    required = ("bg", "text", "lead_text", "accent", "accent_text", "font_family")
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValueError(f"Theme JSON missing required field(s): {missing}")
    if not _HEX_RE.match(data["bg"]):
        raise ValueError(f"bg is not a #RRGGBB hex colour: {data['bg']!r}")
    if not _HEX_RE.match(data["accent"]):
        raise ValueError(f"accent is not a #RRGGBB hex colour: {data['accent']!r}")
    return data


def enforce_readable_theme(proposed):
    """Given a parsed theme proposal, return a theme dict guaranteed to pass
    WCAG AA contrast on every text/ground pairing -- forcing TEXT colour only,
    never a background and never the accent, so the brand's real colour
    choices are preserved.
    """
    return {
        "bg": proposed["bg"],
        "text": _readable_text_for(proposed["bg"], proposed.get("text")),
        "lead_text": _readable_text_for(proposed["bg"], proposed.get("lead_text")),
        "accent": proposed["accent"],
        "accent_text": _readable_text_for(proposed["accent"], proposed.get("accent_text")),
        "font_family": proposed["font_family"],
    }


def font_import_statement(font_family):
    """Derive a Google Fonts `@import url(...)` statement for a theme's
    primary family, or "" when there is nothing to fetch (a generic/system
    keyword, or an empty family).
    """
    first = (font_family or "").split(",")[0].strip().strip('"').strip("'")
    if not first or first.lower() in _FONT_GENERICS:
        return ""
    family = re.sub(r"\s+", "+", first)
    return (
        '@import url("https://fonts.googleapis.com/css2?family='
        f'{family}:wght@500;600;700;800&display=swap");'
    )


def logo_markup(logo_url):
    """Build the {{LOGO_MARKUP}} substitution value. Empty string renders the
    slot empty rather than inventing a mark ("omit rather than invent").
    """
    if not logo_url:
        return ""
    return f'<img src="{logo_url}" alt="" />'


def theme_tokens(theme):
    """Turn a theme dict into the flat `{{TOKEN}}: value}` map the templates
    substitute. These are global tokens -- the same for every frame.
    """
    return {
        "THEME_BG": theme["bg"],
        "THEME_TEXT": theme["text"],
        "THEME_LEAD_TEXT": theme["lead_text"],
        "THEME_ACCENT": theme["accent"],
        "THEME_ACCENT_TEXT": theme["accent_text"],
        "THEME_FONT": theme["font_family"],
        "THEME_FONT_IMPORT": font_import_statement(theme["font_family"]),
        "LOGO_MARKUP": logo_markup(theme.get("logo_url", "")),
    }


def derive_theme(
    brand_guidelines, api_key, model,
    fallback_model=None, provider="openrouter", logo_url="",
):
    """Propose a video theme from free-text brand guidelines via LLM, enforce
    readability deterministically, and attach a logo URL you already have.

    `brand_guidelines` is plain text describing the brand's colours/typography
    (however you want to source it -- a paragraph, a style guide excerpt, a
    couple of bullet points). This function does no fetching of its own.
    """
    proposed = call_text_capability(
        provider, api_key, model, _SYSTEM, brand_guidelines,
        fallback_model=fallback_model, timeout=60.0, parse=parse_theme_response,
    )
    theme = enforce_readable_theme(proposed)
    theme["logo_url"] = logo_url
    return theme
