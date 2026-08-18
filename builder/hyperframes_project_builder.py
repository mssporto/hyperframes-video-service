"""Deterministic assembler for HyperFrames video projects -- no LLM calls.

Takes a structured "video plan" (see schema below) and produces a complete,
real HyperFrames project directory: `index.html` (host wiring),
`hyperframes.json`, `meta.json`, and `compositions/frames/<frameId>.html` per
frame -- each the matching template from `templates/{body,asset,closing}/`
with every placeholder substituted per the rules in `templates/CONTRACT.md`.
This module is a mechanical implementation of that contract; it does not
reinterpret it -- read CONTRACT.md for the substitution rules themselves.

VIDEO PLAN SCHEMA
-----------------
A video plan is a plain dict:

    {
      "project_id": "my-video",       # used for meta.json id/name; default "hyperframes-project"
      "frames": [ <frame plan>, ... ] # required, non-empty
    }

Each frame plan is a dict:

    {
      "template": "body-word-emphasis",  # required -- a key of TEMPLATE_REGISTRY
      "id": "s01",                       # optional -- default "s01", "s02", ... by position
      "tokens": {"HEADLINE": "..."},     # scalar placeholder values (no {{ }}); required
                                          # keys per template are TEMPLATE_REGISTRY[name]["required_tokens"]
      "items": [{"...": "..."}],         # required ONLY for the 3 repeat-block templates
                                          # (body-sequential-list, body-step-list,
                                          # close-social-proof) -- one dict per repeated item;
                                          # the actual key NAME varies by template (e.g.
                                          # "LINE_TEXT" for body-sequential-list, "STEP_LABEL"
                                          # for body-step-list) -- see each template's
                                          # TEMPLATE_REGISTRY["repeat_required"] entry
      "asset_path": "/abs/path.png",     # required ONLY for asset-* templates -- source image
                                          # file, copied into the project's assets/ dir
      "transition": "cut",               # optional -- "cut" (default) | "crossfade" | "push-up"
    }

The top-level plan dict may also carry an optional "audio" key, independent
of any frame:

    "audio": {
      "bed_path": "/abs/path/bed.mp3",     # optional -- background bed, physically
                                            # trimmed (not just data-duration'd) to
                                            # fit the video's computed total_duration
      "bed_volume": 0.55,                  # optional -- default 0.55
      "outro_path": "/abs/path/outro.mp3", # optional -- short sting, starts exactly
                                            # where the bed stops (or the video ends)
      "outro_volume": 1.0,                 # optional -- default 1.0
    }

If "audio" is omitted entirely, build_project() writes no <audio> elements.

The top-level plan dict may also carry an optional "icon_library" key:

    "icon_library": [
      {"file": "/abs/path/icon.svg", "keywords": ["word", "phrase", ...]},
      ...
    ]

If present, any body-word-emphasis or body-step-list frame/row whose own
text scores at least one keyword hit gets that icon's real SVG content
auto-injected into its ICON_SVG token -- UNLESS the caller already supplied
an explicit ICON_SVG value for that frame/row, which is always respected
as-is and never overridden. Its raw SVG is rewritten (see `_theme_icon_svg`)
so its stroke/fill colours retarget to the theme's `--theme-accent` instead
of whatever colour the source icon file shipped with -- an explicitly
supplied ICON_SVG is never rewritten.

The top-level plan dict may also carry an optional "icon_sfx" key, keyed by
template name:

    "icon_sfx": {
      "body-word-emphasis": {"file": "/abs/path/pop.mp3", "volume": 0.45},
      "body-step-list": {"file": "/abs/path/click-soft.mp3", "volume": 0.45},
    }

For any frame/row that actually received a real icon (per "icon_library"
above) whose template has an entry here, a short <audio> cue is added at
the host level, timed to land exactly when that icon's own entrance
animation starts (TEMPLATE_REGISTRY's per-template "icon_sfx_offset").

`{{FRAME_ID}}` and `{{PROGRESS_PCT}}` are always computed by this module, never
supplied by the caller. `{{ASSET_SRC}}` is computed for asset templates after the
source file is copied -- do not put it in `tokens`.

Call `build_project(plan, output_dir, theme=...)` to write the project, then
`zip_project(...)` to package it for the render service (see `service/app.py`).
`theme` is optional -- omit it (or pass None) to use `builder.video_theme.DEFAULT_THEME`.
"""

import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(os.path.dirname(_HERE), "templates")

# 0.35s is the house-style overlap for crossfade/push transitions.
_TRANSITION_OVERLAP_SECONDS = 0.35

# Every template's assembly rules, keyed by the template name a video plan
# names in "template". "slot_seconds" is either a fixed float or a callable of
# item-count -> float, per CONTRACT.md's "Slot" column. "repeat_block" is the
# marker name used by templates that host a variable-length list; absent for
# the other 11. "is_asset" templates require "asset_path" and get {{ASSET_SRC}}
# computed rather than supplied.
#
# One exception to the "callable of item-count -> float" rule: close-social-proof's
# on-screen landing time also depends on how long its LEAD_IN token is (its GSAP
# timeline staggers the lead-in reveal per word before the names start landing),
# so its callable takes (n_items, lead_in_words) -- see the build_project() call
# site's template-name special-case, and the mirrored formula comment on the
# lambda below.
TEMPLATE_REGISTRY = {
    "body-stroke-hook": {
        "path": "body/body-stroke-hook.html",
        "slot_seconds": 3.2,
        "required_tokens": ["HEADLINE_TOP", "HEADLINE_PAYOFF"],
        "optional_tokens": {},
    },
    "body-word-emphasis": {
        "path": "body/body-word-emphasis.html",
        "slot_seconds": 3.0,
        "required_tokens": ["HEADLINE"],
        "optional_tokens": {"ICON_SVG": ""},
        "icon_match_token": "HEADLINE",  # which scalar token's text to match icon_library keywords against
        "icon_sfx_offset": 0.3,  # matches the template's own icon tl.fromTo(...) start time
    },
    "body-split-contrast": {
        "path": "body/body-split-contrast.html",
        "slot_seconds": 3.4,
        "required_tokens": ["CLAUSE_A", "CLAUSE_B"],
        "optional_tokens": {},
    },
    "body-bridge": {
        "path": "body/body-bridge.html",
        "slot_seconds": 2.2,
        "required_tokens": ["HEADLINE"],
        "optional_tokens": {},
    },
    "body-standout-line": {
        "path": "body/body-standout-line.html",
        "slot_seconds": 3.6,
        "required_tokens": ["LINE_1"],
        "optional_tokens": {"LINE_2": "", "LINE_3": ""},
    },
    "body-sequential-list": {
        "path": "body/body-sequential-list.html",
        "slot_seconds": lambda n: 1.0 + 0.5 * n,
        "required_tokens": [],
        "optional_tokens": {},
        "repeat_block": "line",
        "repeat_required": ["LINE_TEXT"],
        "repeat_optional": {},
    },
    "body-step-list": {
        "path": "body/body-step-list.html",
        "slot_seconds": lambda n: 1.0 + 1.2 * n,
        "required_tokens": [],
        "optional_tokens": {},
        "repeat_block": "row",
        "repeat_required": ["STEP_LABEL"],
        "repeat_optional": {"ICON_SVG": ""},
        "icon_match_item_token": "STEP_LABEL",  # which per-item token's text to match, per row
        "icon_sfx_offset": lambda row_index: 0.4 + row_index * 1.2 + 0.05,  # matches each row's icon tween start
    },
    "asset-reveal": {
        "path": "asset/asset-reveal.html",
        "slot_seconds": 3.4,
        "required_tokens": ["HEADLINE", "ASSET_ALT"],
        "optional_tokens": {},
        "is_asset": True,
    },
    "asset-card": {
        "path": "asset/asset-card.html",
        "slot_seconds": 3.2,
        "required_tokens": ["HEADLINE", "ASSET_ALT"],
        "optional_tokens": {},
        "is_asset": True,
    },
    "asset-comparison": {
        "path": "asset/asset-comparison.html",
        "slot_seconds": 3.2,
        "required_tokens": ["HEADLINE", "ASSET_ALT"],
        "optional_tokens": {},
        "is_asset": True,
    },
    "asset-fullbleed": {
        "path": "asset/asset-fullbleed.html",
        "slot_seconds": 3.4,
        "required_tokens": ["HEADLINE", "ASSET_ALT"],
        "optional_tokens": {},
        "is_asset": True,
    },
    "asset-letterbox": {
        "path": "asset/asset-letterbox.html",
        "slot_seconds": 3.4,
        "required_tokens": ["HEADLINE_ABOVE", "HEADLINE_BELOW", "ASSET_ALT"],
        "optional_tokens": {},
        "is_asset": True,
    },
    "close-social-proof": {
        "path": "closing/close-social-proof.html",
        # Mirrors the template's own GSAP timeline (close-social-proof.html's
        # <script>, "leadEnd"/"NAME_STEP") so the registered duration always
        # covers the real landing time instead of assuming a fixed lead-in
        # length: leadEnd = 0.4 + lead_in_words*0.18 + 0.2, the last name's row
        # lands at leadEnd + (n-1)*0.35, and its highlight-sweep bar (started
        # 0.15s after the row, 0.4s long) finishes 0.55s after that -- giving
        # 0.8 + 0.18*lead_in_words + 0.35*n, plus a 0.3s cushion so a cut never
        # lands exactly on the sweep's last frame. Keep in sync with that
        # <script> block if its constants ever change.
        "slot_seconds": lambda n, lead_in_words: 0.8 + 0.18 * lead_in_words + 0.35 * n + 0.3,
        "required_tokens": ["TAG_LABEL", "LEAD_IN"],
        "optional_tokens": {},
        "repeat_block": "name",
        "repeat_required": ["NAME"],
        "repeat_optional": {},
    },
    "close-cta": {
        "path": "closing/close-cta.html",
        "slot_seconds": 3.8,
        "required_tokens": ["HEADLINE", "CTA_TEXT"],
        "optional_tokens": {},
    },
}

_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _format_seconds(value):
    """Render a timing number the way index.html expects: whole seconds with
    no trailing ".0" (e.g. "0", "3.2").
    """
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _body_search_start(html):
    """Index to start searching from to skip the `<head>` doc comment.

    Every source template's `<head>` carries a human-readable comment that
    describes the repeat-block convention using the exact marker syntax as
    prose, and separately mentions the literal text "<template>". A plain
    `str.find()` over the whole file can match those prose mentions instead
    of the real marker/tag later in the body. Anchoring the search at
    `<body>` (present in every template's fixed document shell) avoids that.
    """
    body_start = html.find("<body>")
    return body_start if body_start != -1 else 0


# ── Substitution primitives (CONTRACT.md §2) ─────────────────────────────────

def expand_repeat_block(html, block_name, items, required_keys, optional_defaults):
    """Expand a `<!-- hf:repeat:<block_name> start/end -->` region into N clones.

    Extracts the exact markup between the marker comments (the specimen),
    clones it once per item substituting that item's per-item tokens, and
    replaces the whole region -- markers included -- with the concatenation.
    Per CONTRACT.md §2c this MUST run before the global scalar-substitution
    pass (substitute_scalars): per-item tokens have no single global value
    until the specimen has been cloned once per item.
    """
    start_marker = f"<!-- hf:repeat:{block_name} start -->"
    end_marker = f"<!-- hf:repeat:{block_name} end -->"
    search_from = _body_search_start(html)
    start_idx = html.find(start_marker, search_from)
    end_marker_idx = html.find(end_marker, search_from)
    if start_idx == -1 or end_marker_idx == -1:
        raise ValueError(f"Repeat block markers for '{block_name}' not found in template")

    specimen = html[start_idx + len(start_marker):end_marker_idx]
    end_idx = end_marker_idx + len(end_marker)

    clones = []
    for i, item in enumerate(items):
        missing = [k for k in required_keys if k not in item]
        if missing:
            raise ValueError(f"Repeat item {i} for block '{block_name}' missing required key(s): {missing}")
        values = dict(optional_defaults)
        values.update(item)
        clone = specimen
        for key, value in values.items():
            clone = clone.replace("{{%s}}" % key, value)
        clones.append(clone)

    return html[:start_idx] + "".join(clones) + html[end_idx:]


def substitute_scalars(html, tokens):
    """Global scalar-substitution pass. Run AFTER any repeat-block expansion
    (CONTRACT.md §2c) -- it replaces every `{{NAME}}` occurrence in the whole
    file, including inside an already-expanded repeated region.
    """
    result = html
    for key, value in tokens.items():
        result = result.replace("{{%s}}" % key, value)
    return result


def find_unresolved_placeholders(html):
    """Return the sorted set of any `{{TOKEN}}`-shaped text still left in html.

    A non-empty result after a full substitution pass means a required token
    was never supplied -- callers should treat that as a bug, not render it.
    """
    return sorted(set(_PLACEHOLDER_RE.findall(html)))


def _template_body(html):
    """Return the substring inside the outermost `<template>...</template>`.

    Every source template's `<head>` carries a human-readable doc comment that
    mentions per-item token names as prose describing the repeat block --
    those are never meant to be substituted. Unresolved-placeholder checks
    should only look at this load-bearing region, not the doc comment.
    """
    search_from = _body_search_start(html)
    start = html.find("<template>", search_from)
    end = html.rfind("</template>")
    if start == -1 or end == -1:
        return html
    return html[start:end + len("</template>")]


def compute_progress_pct(position, total, template_name):
    """The frame's position in the whole video, per CONTRACT.md §2b.

    `position` is the 1-based frame number (so frame 3 of 8 => "37.5%").
    `close-cta` always returns "100%" regardless of position/total, per spec.
    """
    if template_name == "close-cta":
        return "100%"
    pct = position / total * 100
    if pct == int(pct):
        return f"{int(pct)}%"
    return f"{round(pct, 1)}%"


def _validate_frame_id(frame_id):
    if not _ID_RE.match(frame_id):
        raise ValueError(f"Invalid frame id {frame_id!r}: must be a valid CSS/HTML id")


def _validate_emphasis_brackets(text):
    """Every `[[` needs a matching `]]` somewhere in the same token (CONTRACT.md §2d)."""
    if text.count("[[") != text.count("]]"):
        raise ValueError(f"Unbalanced [[ ]] emphasis marker in text: {text!r}")


def _same_file_contents(path_a, path_b):
    try:
        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _probe_audio_duration(path):
    """Return the real duration of an audio file in seconds, via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"ffprobe failed to read duration of {path!r}: {exc}") from exc
    return float(result.stdout.strip())


def _trim_audio(src, dest, max_seconds):
    """Write a copy of `src` to `dest`, trimmed to at most `max_seconds`
    (ffmpeg -t). data-duration alone does not trim a longer source file's
    actual playback, so the file itself must be physically cut. If `src` is
    already shorter than `max_seconds`, ffmpeg passes it through unchanged
    rather than erroring or padding -- callers must re-probe `dest`'s real
    duration afterward rather than assuming it equals `max_seconds`.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-t", str(max_seconds), dest],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"ffmpeg failed to trim {src!r} to {dest!r}: {exc}") from exc


def _fit_bed_audio(src, dest, target_seconds):
    """Write a copy of `src` to `dest`, LOOPED (ffmpeg -stream_loop) as many
    times as needed to fill `target_seconds`, then trimmed to exactly that
    length -- a source shorter than the target is not left to play once and
    go silent for the remainder.

    Only ever used for the BED track. The outro must never loop (it's a
    one-shot sting meant to play exactly once at the very end) -- that path
    still calls _trim_audio, unchanged.

    A source already >= target_seconds behaves identically to _trim_audio
    (ffmpeg reaches -t's cutoff before ever looping back to the start).
    """
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, "-t", str(target_seconds), dest],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"ffmpeg failed to loop/trim {src!r} to {dest!r}: {exc}") from exc


def pick_audio_file(files, strategy, index=None):
    """Pick one file path from `files` per `strategy`. Only "fixed" is
    implemented today (always returns files[0], regardless of `index`).
    `index` is accepted now so a future "rotate" strategy (using it as a
    rotation counter) doesn't need a signature change later.
    """
    if strategy == "fixed":
        return files[0]
    raise ValueError(f"Unknown audio selection strategy: {strategy!r}")


def pick_icon_for_text(text, icon_library):
    """Score each icon_library entry ({"file": str, "keywords": [str, ...]})
    against text by counting case-insensitive keyword substring hits, return
    the highest-scoring entry's raw SVG file content, or None if every entry
    scores zero (or icon_library is empty/falsy). Ties break by first-in-list
    order -- deterministic, no randomness.
    """
    if not icon_library:
        return None
    lowered = text.lower()
    best_score = 0
    best_file = None
    for entry in icon_library:
        score = sum(1 for kw in entry["keywords"] if kw.lower() in lowered)
        if score > best_score:
            best_score = score
            best_file = entry["file"]
    if best_file is None:
        return None
    try:
        with open(best_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# Matches a hardcoded hex colour on a fill/stroke attribute -- #RGB or #RRGGBB,
# case-insensitive. Deliberately does NOT match fill="none"/stroke="none":
# "none" is an intentional no-paint, not a colour to retarget.
_ICON_HEX_COLOR_ATTR_RE = re.compile(
    r'\b(fill|stroke)="#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})"', re.IGNORECASE
)
_ICON_SVG_OPEN_TAG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ICON_STYLE_ATTR_RE = re.compile(r'style="([^"]*)"', re.IGNORECASE)


def _theme_icon_svg(svg_markup):
    """Rewrite an already-selected icon's raw SVG markup so it follows the
    theme's accent instead of whatever colour the source file hardcoded:

      1. Replace hardcoded fill="#RGB"/"#RRGGBB" and stroke="#RGB"/"#RRGGBB"
         attribute values with currentColor (case-insensitive hex).
         fill="none"/stroke="none" are left alone.
      2. Add (or merge into) a style attribute on the SVG root tag so
         currentColor actually resolves to something: style="color:
         var(--theme-accent)". `color` is inherited and CSS custom
         properties resolve through the cascade, so setting it on the SVG
         root itself is correct regardless of what markup wraps the icon in
         a given template, and an inline style always wins the cascade.
    """
    if not svg_markup:
        return svg_markup

    svg_markup = _ICON_HEX_COLOR_ATTR_RE.sub(
        lambda m: f'{m.group(1)}="currentColor"', svg_markup
    )

    def _inject_accent_style(match):
        tag = match.group(0)
        style_match = _ICON_STYLE_ATTR_RE.search(tag)
        if style_match:
            existing = style_match.group(1).strip().rstrip(";").strip()
            merged = (
                f"{existing}; color: var(--theme-accent)"
                if existing
                else "color: var(--theme-accent)"
            )
            return _ICON_STYLE_ATTR_RE.sub(f'style="{merged}"', tag, count=1)
        return re.sub(
            r"^<svg\b", '<svg style="color: var(--theme-accent)"', tag,
            count=1, flags=re.IGNORECASE,
        )

    return _ICON_SVG_OPEN_TAG_RE.sub(_inject_accent_style, svg_markup, count=1)


def _prepare_audio(audio_plan, output_dir, total_duration):
    """Resolve plan["audio"] (optional) into the list of <audio> elements
    _write_index_html() should emit. Returns [] if audio_plan is falsy.

    The render window is [0, total_duration) -- so the outro can never START
    at total_duration (that's entirely outside the window and would never
    play); it must be tucked inside the window, ending exactly where the
    window ends. When both bed and outro are given, the bed is therefore
    trimmed to `total_duration - outro_duration`, not the full
    total_duration, and the outro starts at that same point.

    The bed is physically looped-and-trimmed to fit its target exactly (see
    _fit_bed_audio's docstring -- a bed source shorter than its target loops
    to fill the whole span rather than playing once and going silent); the
    outro is copied as-is since it's already short and fixed-length, and
    must never loop.
    """
    if not audio_plan:
        return []

    # Validate both paths (if given) upfront, before either one's side
    # effects fire. Otherwise a valid bed_path with a missing outro_path
    # would leave a half-built assets/audio/ dir behind when build_project()
    # aborts on the outro's ValueError.
    bed_path = audio_plan.get("bed_path")
    if bed_path and not os.path.isfile(bed_path):
        raise ValueError(f"'audio.bed_path' must point to an existing file: {bed_path!r}")

    outro_path = audio_plan.get("outro_path")
    if outro_path and not os.path.isfile(outro_path):
        raise ValueError(f"'audio.outro_path' must point to an existing file: {outro_path!r}")

    # The outro's real duration has to be known before the bed's trim target
    # can be computed, so probe the source file (copying it afterward doesn't
    # change its length -- either order of probe vs. copy is fine here).
    outro_duration = _probe_audio_duration(outro_path) if outro_path else None

    assets_dir = os.path.join(output_dir, "assets", "audio")
    elements = []

    if bed_path:
        bed_target = (
            max(0, total_duration - outro_duration) if outro_duration is not None else total_duration
        )
        os.makedirs(assets_dir, exist_ok=True)
        bed_dest = os.path.join(assets_dir, os.path.basename(bed_path))
        _fit_bed_audio(bed_path, bed_dest, bed_target)
        elements.append({
            "id": "el-audio-bed",
            "src": f"assets/audio/{os.path.basename(bed_dest)}",
            "start": 0,
            "duration": _probe_audio_duration(bed_dest),
            "volume": audio_plan.get("bed_volume", 0.55),
        })

    if outro_path:
        outro_start = max(0, total_duration - outro_duration)
        os.makedirs(assets_dir, exist_ok=True)
        basename = os.path.basename(outro_path)
        dest_name = basename
        outro_dest = os.path.join(assets_dir, dest_name)
        if os.path.exists(outro_dest) and not _same_file_contents(outro_dest, outro_path):
            dest_name = f"outro-{basename}"
            outro_dest = os.path.join(assets_dir, dest_name)
        shutil.copyfile(outro_path, outro_dest)
        elements.append({
            "id": "el-audio-outro",
            "src": f"assets/audio/{dest_name}",
            "start": outro_start,
            "duration": _probe_audio_duration(outro_dest),
            "volume": audio_plan.get("outro_volume", 1.0),
        })

    return elements


def _prepare_icon_sfx(events, schedule, output_dir):
    """Resolve pending icon-SFX events (recorded during build_project()'s
    per-frame loop, before frame start times were known) into the <audio>
    elements _write_index_html() should emit.

    events: list of {"frame_id": str, "local_offset": float, "sfx_path": str,
    "volume": float} -- one per frame/row that actually received a real
    icon AND whose template has an entry in plan["icon_sfx"].
    schedule: the already-computed per-frame schedule (gives each frame_id's
    real absolute host-timeline start, needed to convert each event's local
    offset into an absolute one).

    Each unique sfx_path is copied into assets/sfx/ once, reused across
    every event that references it.
    """
    if not events:
        return []

    frame_starts = {s["frame_id"]: s["start"] for s in schedule}
    sfx_dir = os.path.join(output_dir, "assets", "sfx")
    dest_cache = {}
    elements = []

    for i, ev in enumerate(events):
        sfx_path = ev["sfx_path"]
        if sfx_path not in dest_cache:
            os.makedirs(sfx_dir, exist_ok=True)
            basename = os.path.basename(sfx_path)
            dest_name = basename
            dest_path = os.path.join(sfx_dir, dest_name)
            if os.path.exists(dest_path) and not _same_file_contents(dest_path, sfx_path):
                dest_name = f"{i}-{basename}"
                dest_path = os.path.join(sfx_dir, dest_name)
            shutil.copyfile(sfx_path, dest_path)
            dest_cache[sfx_path] = dest_path

        dest_path = dest_cache[sfx_path]
        elements.append({
            "id": f"el-icon-sfx-{i}",
            "src": f"assets/sfx/{os.path.basename(dest_path)}",
            "start": round(frame_starts[ev["frame_id"]] + ev["local_offset"], 3),
            "duration": _probe_audio_duration(dest_path),
            "volume": ev["volume"],
        })

    return elements


# ── Project assembly ─────────────────────────────────────────────────────────

def build_project(plan, output_dir, theme=None):
    """Build a complete HyperFrames project directory at output_dir from a
    video plan (see module docstring for the schema). Returns a summary dict:
    {"frame_ids": [...], "total_duration": <seconds>}.

    `theme` is a `builder.video_theme` theme dict (bg/text/lead_text/accent/
    accent_text/font_family/logo_url). Omit it (or pass None) to use
    `builder.video_theme.DEFAULT_THEME`.
    """
    frames = plan.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Video plan must have a non-empty 'frames' list")

    from builder.video_theme import DEFAULT_THEME
    from builder.video_theme import theme_tokens as _resolve_theme_tokens
    theme_tokens = _resolve_theme_tokens(theme or DEFAULT_THEME)

    project_id = plan.get("project_id", "hyperframes-project")
    total = len(frames)

    os.makedirs(output_dir, exist_ok=True)
    frames_dir = os.path.join(output_dir, "compositions", "frames")
    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(frames_dir, exist_ok=True)

    resolved = []
    seen_ids = set()
    pending_icon_sfx = []

    for i, frame_plan in enumerate(frames):
        template_name = frame_plan.get("template")
        if template_name not in TEMPLATE_REGISTRY:
            raise ValueError(f"Frame {i}: unknown template {template_name!r}")
        spec = TEMPLATE_REGISTRY[template_name]

        frame_id = frame_plan.get("id") or f"s{i + 1:02d}"
        _validate_frame_id(frame_id)
        if frame_id in seen_ids:
            raise ValueError(f"Duplicate frame id: {frame_id!r}")
        seen_ids.add(frame_id)

        tokens = dict(frame_plan.get("tokens", {}))
        missing = [k for k in spec["required_tokens"] if k not in tokens]
        if missing:
            raise ValueError(f"Frame {frame_id} ({template_name}): missing required token(s) {missing}")
        icon_match_token = spec.get("icon_match_token")
        icon_library = plan.get("icon_library")
        icon_sfx_config = plan.get("icon_sfx", {}).get(template_name)
        if (
            icon_match_token
            and icon_library
            and "ICON_SVG" not in frame_plan.get("tokens", {})
        ):
            matched_icon = pick_icon_for_text(tokens.get(icon_match_token, ""), icon_library)
            if matched_icon:
                matched_icon = _theme_icon_svg(matched_icon)
                tokens["ICON_SVG"] = matched_icon
                if icon_sfx_config:
                    offset = spec.get("icon_sfx_offset")
                    pending_icon_sfx.append({
                        "frame_id": frame_id,
                        "local_offset": offset,
                        "sfx_path": icon_sfx_config["file"],
                        "volume": icon_sfx_config.get("volume", 0.45),
                    })

        for key, default in spec.get("optional_tokens", {}).items():
            tokens.setdefault(key, default)
        for value in tokens.values():
            if isinstance(value, str):
                _validate_emphasis_brackets(value)

        if spec.get("is_asset"):
            asset_path = frame_plan.get("asset_path")
            if not asset_path or not os.path.isfile(asset_path):
                raise ValueError(f"Frame {frame_id} ({template_name}): 'asset_path' must point to an existing file")
            os.makedirs(assets_dir, exist_ok=True)
            basename = os.path.basename(asset_path)
            dest_name = basename
            dest_path = os.path.join(assets_dir, dest_name)
            if os.path.exists(dest_path) and not _same_file_contents(dest_path, asset_path):
                dest_name = f"{frame_id}-{basename}"
                dest_path = os.path.join(assets_dir, dest_name)
            shutil.copyfile(asset_path, dest_path)
            # The file on disk keeps its real name (collision-checked above against
            # that real name); only the HTML reference needs URL-safety, since a raw
            # space or '#' in an <img src="..."> breaks resolution.
            tokens["ASSET_SRC"] = f"assets/{quote(dest_name)}"

        template_path = os.path.join(TEMPLATES_DIR, spec["path"])
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        repeat_block = spec.get("repeat_block")
        n_items = 1
        if repeat_block:
            items = frame_plan.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError(f"Frame {frame_id} ({template_name}): 'items' must be a non-empty list")
            for item in items:
                for value in item.values():
                    if isinstance(value, str):
                        _validate_emphasis_brackets(value)

            icon_match_item_token = spec.get("icon_match_item_token")
            if icon_match_item_token and icon_library:
                items = [dict(item) for item in items]  # copy before mutating
                for row_index, item in enumerate(items):
                    if "ICON_SVG" not in item:
                        matched_icon = pick_icon_for_text(item.get(icon_match_item_token, ""), icon_library)
                        if matched_icon:
                            matched_icon = _theme_icon_svg(matched_icon)
                            item["ICON_SVG"] = matched_icon
                            if icon_sfx_config:
                                offset_spec = spec.get("icon_sfx_offset")
                                offset = offset_spec(row_index) if callable(offset_spec) else offset_spec
                                pending_icon_sfx.append({
                                    "frame_id": frame_id,
                                    "local_offset": offset,
                                    "sfx_path": icon_sfx_config["file"],
                                    "volume": icon_sfx_config.get("volume", 0.45),
                                })

            n_items = len(items)
            # Repeat-block expansion FIRST, per CONTRACT.md §2c.
            html = expand_repeat_block(
                html, repeat_block, items, spec["repeat_required"], spec.get("repeat_optional", {})
            )

        # THEN the single global scalar-substitution pass over the whole file.
        position = i + 1
        global_tokens = dict(tokens)
        global_tokens.update(theme_tokens)
        global_tokens["FRAME_ID"] = frame_id
        global_tokens["PROGRESS_PCT"] = compute_progress_pct(position, total, template_name)
        html = substitute_scalars(html, global_tokens)

        leftover = find_unresolved_placeholders(_template_body(html))
        if leftover:
            raise ValueError(f"Frame {frame_id} ({template_name}): unresolved placeholder(s) {leftover}")

        with open(os.path.join(frames_dir, f"{frame_id}.html"), "w", encoding="utf-8") as f:
            f.write(html)

        slot = spec["slot_seconds"]
        if template_name == "close-social-proof":
            # LEAD_IN's word count drives the template's own lead-in stagger
            # (see TEMPLATE_REGISTRY entry above), so it has to reach the
            # duration calculation too, not just n_items.
            lead_in_words = len(tokens["LEAD_IN"].split())
            duration = slot(n_items, lead_in_words)
        else:
            duration = slot(n_items) if callable(slot) else slot
        resolved.append({
            "frame_id": frame_id,
            "template": template_name,
            "duration": round(duration, 3),
            "transition": frame_plan.get("transition", "cut"),
        })

    schedule = _compute_schedule(resolved)
    total_duration = round(schedule[-1]["start"] + schedule[-1]["duration"], 3)

    audio_elements = _prepare_audio(plan.get("audio"), output_dir, total_duration)
    audio_elements += _prepare_icon_sfx(pending_icon_sfx, schedule, output_dir)

    _write_index_html(output_dir, schedule, total_duration, audio_elements)
    _write_hyperframes_json(output_dir)
    _write_meta_json(output_dir, project_id)

    return {"frame_ids": [r["frame_id"] for r in resolved], "total_duration": total_duration}


def _compute_schedule(resolved):
    """Assign cumulative data-start/data-track-index to each frame.

    Plain cuts: each frame starts where the previous one ended (CONTRACT.md
    §5). "crossfade"/"push-up" transitions overlap the previous frame by
    _TRANSITION_OVERLAP_SECONDS.
    """
    schedule = []
    cursor = 0.0
    for idx, r in enumerate(resolved):
        transition = r["transition"]
        if idx == 0 or transition == "cut":
            start = cursor
        else:
            start = cursor - _TRANSITION_OVERLAP_SECONDS
        schedule.append({**r, "start": round(start, 3), "track_index": idx + 1})
        cursor = start + r["duration"]
    return schedule


def _write_index_html(output_dir, schedule, total_duration, audio_elements):
    scene_divs = []
    transition_snippets = []
    for s in schedule:
        start_str = _format_seconds(s["start"])
        duration_str = _format_seconds(s["duration"])
        scene_divs.append(
            f'      <div id="el-{s["frame_id"]}" class="scene" '
            f'data-composition-id="{s["frame_id"]}" '
            f'data-composition-src="compositions/frames/{s["frame_id"]}.html" '
            f'data-start="{start_str}" data-duration="{duration_str}" '
            f'data-track-index="{s["track_index"]}" '
            f'data-width="1080" data-height="1920"></div>'
        )
        if s["transition"] == "crossfade":
            transition_snippets.append(
                f'      gsap.set("#el-{s["frame_id"]}", {{ opacity: 0 }});\n'
                f'      tl.fromTo("#el-{s["frame_id"]}", {{ opacity: 0 }}, '
                f'{{ opacity: 1, duration: {_TRANSITION_OVERLAP_SECONDS}, ease: "none" }}, {start_str});'
            )
        elif s["transition"] == "push-up":
            transition_snippets.append(
                f'      gsap.set("#el-{s["frame_id"]}", {{ y: "100%" }});\n'
                f'      tl.fromTo("#el-{s["frame_id"]}", {{ y: "100%" }}, '
                f'{{ y: "0%", duration: {_TRANSITION_OVERLAP_SECONDS}, ease: "power2.out" }}, {start_str});'
            )

    audio_divs = []
    for i, a in enumerate(audio_elements):
        audio_divs.append(
            f'      <audio id="{a["id"]}" src="{a["src"]}" '
            f'data-start="{_format_seconds(a["start"])}" '
            f'data-duration="{_format_seconds(a["duration"])}" '
            f'data-track-index="{len(schedule) + i + 1}" '
            f'data-volume="{_format_seconds(a["volume"])}"></audio>'
        )

    scenes_html = "\n\n".join(scene_divs)
    audio_html = ("\n\n" + "\n\n".join(audio_divs)) if audio_divs else ""
    transitions_js = ("\n\n".join(transition_snippets) + "\n") if transition_snippets else ""

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=1080, height=1920">\n'
        '    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" '
        'integrity="sha384-sG0Hv1tP1lZCk9KQmrIbY/XNwi+OY84GQqhMscbnsoBFqAz8KNCil1kvfL3Hbbk2" '
        'crossorigin="anonymous"></script>\n'
        "    <style>\n"
        "      * { margin: 0; padding: 0; box-sizing: border-box; }\n"
        "      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000000; }\n"
        "      #root { position: relative; width: 1080px; height: 1920px; overflow: hidden; background: #000000; }\n"
        "      .scene { position: absolute; inset: 0; width: 100%; height: 100%; will-change: transform, opacity; }\n"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        f'    <div id="root" data-composition-id="main" data-start="0" '
        f'data-duration="{_format_seconds(total_duration)}" data-width="1080" data-height="1920">\n'
        f"{scenes_html}{audio_html}\n"
        "    </div>\n\n"
        "    <script>\n"
        "      window.__timelines = window.__timelines || {};\n"
        "      const tl = gsap.timeline({ paused: true });\n\n"
        f"{transitions_js}"
        '      window.__timelines["main"] = tl;\n'
        "    </script>\n"
        "  </body>\n"
        "</html>\n"
    )
    with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def _write_hyperframes_json(output_dir):
    content = {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
    }
    with open(os.path.join(output_dir, "hyperframes.json"), "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2)
        f.write("\n")


def _write_meta_json(output_dir, project_id):
    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    content = {"id": project_id, "name": project_id, "createdAt": created_at}
    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2)
        f.write("\n")


def zip_project(project_dir, zip_path):
    """Zip the whole project directory with files at the zip root -- the
    shape the render service's `create` endpoint expects (it also accepts
    one level of nesting, but root is simplest). Returns zip_path.
    """
    project_dir = os.path.abspath(project_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(project_dir):
            for name in files:
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, project_dir)
                zf.write(full_path, rel_path)
    return zip_path
