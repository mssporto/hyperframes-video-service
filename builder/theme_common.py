"""Brand-agnostic WCAG-contrast primitives used by video_theme.

Pure functions, no I/O, no client/tenant concept -- deterministic guarantee
that any theme's text/background pairings stay readable regardless of what
an LLM proposed.
"""

import re

_MIN_CONTRAST_RATIO = 4.5

_HEX_RE = re.compile(r"^#([0-9A-Fa-f]{6})$")


def _relative_luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b):
    """WCAG contrast ratio between two `#RRGGBB` colours, always >= 1.0."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _readable_text_for(bg_hex, proposed_text_hex):
    """Return proposed_text_hex if it clears the minimum contrast against
    bg_hex; otherwise force whichever of pure black/white contrasts more,
    guaranteeing a readable pair regardless of what was proposed.
    """
    if _HEX_RE.match(proposed_text_hex or "") and contrast_ratio(bg_hex, proposed_text_hex) >= _MIN_CONTRAST_RATIO:
        return proposed_text_hex
    return "#FFFFFF" if contrast_ratio(bg_hex, "#FFFFFF") >= contrast_ratio(bg_hex, "#000000") else "#000000"
