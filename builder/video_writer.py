"""Turn a content brief into a full HyperFrames "video plan" -- a title,
description, projectId, and a `frames` array -- ready for the deterministic
assembler in `builder/hyperframes_project_builder.py` (and, downstream of
that, the render service in `service/app.py`).

The frame vocabulary and per-frame token names are the authoritative
HyperFrames template contract in `templates/CONTRACT.md` (14 templates: 7
body + 5 asset + 2 closing).
"""

import json
import re

from builder.hyperframes_project_builder import TEMPLATE_REGISTRY
from builder.llm_providers import call_text_capability

# Frame-vocabulary sets derived from the single source of truth (the assembler's
# registry) so this validator can never drift from what build_project() accepts.
_ASSET_TEMPLATES = frozenset(
    name for name, spec in TEMPLATE_REGISTRY.items() if spec.get("is_asset")
)
_REPEAT_TEMPLATES = frozenset(
    name for name, spec in TEMPLATE_REGISTRY.items() if spec.get("repeat_block")
)


def _social_proof_entries(social_proof):
    """Return the ordered list of sub-blocks that carry real, non-empty
    `items`. Those are the only ones we can render without fabricating
    names -- no social proof configured yields an empty list, and the two
    close-social-proof frames are then skipped entirely (see _build_system).
    """
    if not social_proof:
        return []
    entries = []
    for block in social_proof:
        if block and block.get("items"):
            entries.append(block)
    return entries


def _build_system(display_name, voice_guidance="", social_proof=None, cta_text=""):
    """Build the Video Writer system prompt.

    `display_name` is whoever's voice the writer speaks in (your brand/show
    name). `voice_guidance` is free text -- banned words, tone, style rules.
    `social_proof` is an optional list of {"tag_label": str, "items": [str, ...]}
    blocks (e.g. client names, awards) rendered as close-social-proof frames,
    in the given order. `cta_text` is the closing CTA line (e.g. your domain
    or handle).
    """
    entries = _social_proof_entries(social_proof)
    # Every video stays at 8 frames total: 13 frames at this template set's
    # per-frame cost (~2.2-3.8s each) structurally can't fit a 30s short
    # regardless of content, so the frame count has to come down, not just
    # per-frame wording. When social proof is present, that's up to
    # len(entries) social-proof + content + 1 CTA = 8; when it's absent, the
    # social-proof frames are skipped and the content frames grow to fill
    # the gap.
    n_social = len(entries)
    n_content = 7 - n_social

    closing_lines = []
    for idx, block in enumerate(entries, start=1):
        names = ", ".join(str(n) for n in block["items"])
        tag_label = block.get("tag_label", "")
        closing_lines.append(
            f"{idx}. close-social-proof: tokens {{\"TAG_LABEL\": \"{tag_label}\", "
            "\"LEAD_IN\": \"<a short graphite lead-in clause you compose fresh for "
            "this video -- vary it across videos, never a stock repeated line>\"}, "
            "plus an \"items\" array of {\"NAME\": \"...\"} using EXACTLY these real "
            "names, verbatim and in this order, one per item -- never substitute, "
            f"reorder, abbreviate, or invent others: {names}."
        )
    cta_idx = n_social + 1
    closing_lines.append(
        f"{cta_idx}. close-cta: tokens {{\"HEADLINE\" (the closing hook line, "
        f"3-8 words), \"CTA_TEXT\": \"{cta_text}\"}}.\n"
    )
    if entries:
        closing_count = f"these {cta_idx} frames, in this exact order"
    else:
        closing_count = "this 1 frame"
    closing_block = (
        f"MANDATORY CLOSING SEQUENCE: every video ends with {closing_count}:\n"
        + "\n".join(closing_lines)
        + "Names are TEXT ONLY -- never fabricate logos or asset ids for these "
        "frames. Vary the close-cta hook line across videos.\n\n"
    )

    voice_block = f"Apply this voice/tone guidance: {voice_guidance}\n\n" if voice_guidance else ""

    return (
        f"You are the Video Writer for {display_name}. You write "
        "short-form video scripts (YouTube Shorts) as a JSON 'video plan' for the "
        "HyperFrames render pipeline: a fixed set of parameterised frame templates "
        "assembled by a deterministic tool, not free-form markup.\n\n"
        + voice_block +
        "Write the way a senior expert would speak casually after a good project -- "
        "sharp, specific, never generic. Not a press release, not a bullet list read "
        "aloud.\n\n"
        "GROUND TRUTH RULE: everything you write must come from the input brief. "
        "If a detail isn't in the brief, you don't have it -- no invented quotes, "
        "no invented internal moments. If a frame needs a detail you don't have, "
        "change the frame, don't invent the detail.\n\n"
        f"FRAME COUNT: write exactly {n_content} content frames, plus the "
        f"mandatory closing frame(s) below -- {n_content + cta_idx} frames total.\n\n"
        "RUNTIME BUDGET: the assembled video must stay under 30 seconds total, "
        "hard cap -- a longer one gets rejected outright. Most body/asset/closing "
        "frames run about 3-3.8s each; body-bridge is faster (about 2.2s). The two "
        "list templates (body-sequential-list, body-step-list) run about 1s plus "
        "roughly 0.5-1.2s per item -- keep these to 2-3 items each, and keep the "
        "overall frame count on the lower end of FRAME COUNT above, to leave "
        "runtime for the rest of the video.\n\n"
        "WRITING STYLE:\n"
        "- Each frame is one beat of a spoken story, not a sentence or a summary.\n"
        "- No comma-separated lists inside one text token -- give each idea its own "
        "frame (the list templates below are the one exception).\n"
        "- No transition phrases (\"Then\", \"So\", \"This means\", \"As a result\").\n"
        "- No passive voice (\"was redesigned\" -> \"we redesigned it\").\n"
        "- Body text tokens: keep them short, within each template's word cap; "
        "fewer words is better.\n"
        "- No emojis, no hashtags in frame text, no exclamation marks, no ALL "
        "CAPS -- sentence case throughout.\n"
        "- Template variety: no single body template appears more than twice per "
        "video; use at least 4 distinct body templates. Never two asset frames back "
        "to back.\n\n"
        "FORBIDDEN PATTERNS: \"We did X, Y, and Z.\" / \"The result was...\" / "
        "\"This allowed them to...\" / anything that reads like a project brief.\n\n"
        "EMPHASIS MARKER: inside any display-text token, wrap ONE word -- or one run "
        "of adjacent words -- in double square brackets to render it in the accent "
        "colour, e.g. \"Measure what [[actually]] moves\" or \"Focus on what "
        "[[really matters]]\". One emphasis run per line at most; every \"[[\" must "
        "have a matching \"]]\". Available in every text template except "
        "body-step-list's STEP_LABEL, which has no accent engine and renders literal "
        "brackets if used.\n\n"
        "FRAME OBJECT SHAPE: each frame is "
        '{ "id": "s01", "template": "<name>", "tokens": { ... } } with these '
        "additions where noted below: repeat-list templates add an \"items\" array "
        "instead of putting the list in tokens; asset templates add \"asset\" and "
        "\"assetId\". Ids are s01, s02, ... in order. \"transition\" is optional "
        "(\"cut\" default).\n\n"
        "BODY TEMPLATES (no asset). tokens keys are exact -- use them verbatim:\n"
        "- body-stroke-hook: opening hook. tokens {\"HEADLINE_TOP\" (2-4 words, "
        "stroke setup line), \"HEADLINE_PAYOFF\" (1-3 words, the accent payoff)}.\n"
        "- body-word-emphasis: one idea, one accent word. tokens {\"HEADLINE\" (3-6 "
        "words, use the [[emphasis]] marker on the key word)}.\n"
        "- body-split-contrast: two-part tension. tokens {\"CLAUSE_A\" (setup), "
        "\"CLAUSE_B\" (the turn)}.\n"
        "- body-bridge: fastest momentum beat, one tight line. tokens {\"HEADLINE\" "
        "(2-5 words)}.\n"
        "- body-standout-line: the screenshot-worthy statement, biggest type, up to "
        "3 lines. tokens {\"LINE_1\" (required), \"LINE_2\" (optional), \"LINE_3\" "
        "(optional)} -- omit unused lines.\n"
        "- body-sequential-list: a list that accumulates line by line. NO text in "
        "tokens; instead an \"items\" array of {\"LINE_TEXT\": \"...\"}, one per "
        "line (aim 3 lines, see RUNTIME BUDGET above).\n"
        "- body-step-list: a dense numbered method. The square step badge (1, 2, "
        "3...) is drawn automatically by the template from row order -- never put "
        "a number in STEP_LABEL. NO text in tokens; \"items\" array of "
        "{\"STEP_LABEL\": \"...\"}, one per step (aim 3, see RUNTIME BUDGET above) "
        "-- STEP_LABEL IS the step's real label text, never a bare number, and "
        "never \"LINE_TEXT\" (that key belongs only to body-sequential-list above).\n\n"
        "ASSET FRAME (a portfolio image): include EXACTLY ONE, as the last "
        "content frame before the mandatory closing sequence. "
        "Pick one asset from the list given whose tags/notes fit this video's "
        "narrative, and pick the template whose layout suits it:\n"
        "- asset-reveal: headline up top, asset rises in. tokens {\"HEADLINE\" (3-8 "
        "words), \"ASSET_ALT\" (short alt text)}.\n"
        "- asset-card: headline above, asset in a tinted card. tokens {\"HEADLINE\", "
        "\"ASSET_ALT\"}.\n"
        "- asset-comparison: hard 50/50 split, asset in lower half. tokens "
        "{\"HEADLINE\", \"ASSET_ALT\"}.\n"
        "- asset-fullbleed: asset fills the frame, headline over a scrim. tokens "
        "{\"HEADLINE\", \"ASSET_ALT\"}.\n"
        "- asset-letterbox: asset in a centred band, a line above and below. tokens "
        "{\"HEADLINE_ABOVE\", \"HEADLINE_BELOW\", \"ASSET_ALT\"}.\n"
        "On the asset frame set \"asset\" to the exact filename and \"assetId\" "
        "to whatever id the caller uses to identify it. Never describe the "
        "deliverable type generically. Write it as the natural next beat of the "
        "story, not a caption for the image. If no assets are listed, skip the "
        "asset frame and write another body frame instead.\n\n"
        + closing_block +
        "OUTPUT: return ONLY this JSON object, nothing else:\n"
        "{\n"
        '  "youtubeTitle": "max 60 chars, sentence case, hook-first",\n'
        '  "youtubeDescription": "2-3 sentences, plain prose, no bullets/headers, '
        f"ends with {cta_text} on its own line then 3-5 hashtags including "
        '#Shorts on the line below",\n'
        '  "projectId": "kebab-case slug derived from the video topic",\n'
        '  "frames": [ { "id": "s01", "template": "...", "tokens": { ... } }, ... ]\n'
        "}\n"
        "No fences, no commentary outside the JSON."
    )


def build_prompt(brief, assets_block="", avoid_templates=""):
    """`brief` is a plain dict describing what this video should be about --
    whatever shape you want (topic, angle, key points, source material). It
    is serialized as-is into the prompt.
    """
    avoid_section = f"\n\n{avoid_templates}" if avoid_templates else ""
    assets_section = f"\n\nAssets available:\n{assets_block}" if assets_block else ""
    return (
        f"Brief:\n{json.dumps(brief)}"
        f"{assets_section}"
        f"{avoid_section}"
    )


def _validate_frame(i, frame):
    """Validate one frame against the HyperFrames template contract.

    Raises ValueError describing the first problem. Checks are keyed off the
    assembler's own TEMPLATE_REGISTRY so parse-time validation matches exactly
    what build_project() will accept downstream.
    """
    if not isinstance(frame, dict):
        raise ValueError(f"Frame {i} must be an object")

    template = frame.get("template")
    if not template:
        raise ValueError(f"Frame {i} missing `template`")
    if template not in TEMPLATE_REGISTRY:
        raise ValueError(f"Frame {i} has unknown template {template!r}")
    spec = TEMPLATE_REGISTRY[template]

    tokens = frame.get("tokens", {})
    if not isinstance(tokens, dict):
        raise ValueError(f"Frame {i} ({template}) `tokens` must be an object")
    # ASSET_SRC is computed by the assembler, never authored -- ignore it here.
    missing = [t for t in spec["required_tokens"] if t not in tokens]
    if missing:
        raise ValueError(f"Frame {i} ({template}) missing required token(s): {missing}")

    if template in _REPEAT_TEMPLATES:
        items = frame.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError(f"Frame {i} ({template}) needs a non-empty `items` list")
        for j, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Frame {i} ({template}) item {j} must be an object")
            item_missing = [k for k in spec["repeat_required"] if k not in item]
            if item_missing:
                raise ValueError(
                    f"Frame {i} ({template}) item {j} missing key(s): {item_missing}"
                )

    if template in _ASSET_TEMPLATES and not frame.get("asset"):
        raise ValueError(f"Frame {i} ({template}) missing `asset` filename")


# Frame COUNT alone (validated below, 3-14) doesn't bound runtime, since
# slot_seconds varies per template and repeat-block frames scale with their
# own item count -- so runtime needs its own, separate check.
_MAX_VIDEO_DURATION_SECONDS = 30.0


def _estimate_duration_seconds(frames):
    """Sum each frame's TEMPLATE_REGISTRY slot_seconds -- the same formula
    hyperframes_project_builder.build_project() uses -- to estimate the
    video's total runtime before ever rendering it.

    For "cut" transitions (the default, and the only kind this writer's
    prompt asks for) this matches the real assembled duration exactly; a
    crossfade/push-up transition only shortens the real total further, so
    this sum is always a safe upper bound, never an underestimate.
    """
    total = 0.0
    for frame in frames:
        spec = TEMPLATE_REGISTRY[frame["template"]]
        slot = spec["slot_seconds"]
        if not callable(slot):
            total += slot
            continue
        items = frame.get("items") or []
        if frame["template"] == "close-social-proof":
            lead_in_words = len(frame.get("tokens", {}).get("LEAD_IN", "").split())
            total += slot(len(items), lead_in_words)
        else:
            total += slot(len(items))
    return round(total, 3)


def parse_video(text):
    """Parse the model reply into the video-plan dict; raise ValueError if impossible."""
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
        raise ValueError(f"Could not parse video JSON: {e}") from e

    for field in ("youtubeTitle", "youtubeDescription", "projectId"):
        if not data.get(field):
            raise ValueError(f"Video JSON missing `{field}`")

    frames = data.get("frames")
    if not isinstance(frames, list) or not (3 <= len(frames) <= 14):
        got = len(frames) if isinstance(frames, list) else type(frames).__name__
        raise ValueError(f"Video JSON `frames` must be a list of 3-14 items, got {got}")
    for i, frame in enumerate(frames):
        _validate_frame(i, frame)

    estimated_duration = _estimate_duration_seconds(frames)
    if estimated_duration > _MAX_VIDEO_DURATION_SECONDS:
        raise ValueError(
            f"Video JSON estimated runtime {estimated_duration}s exceeds the "
            f"{_MAX_VIDEO_DURATION_SECONDS}s short-video cap -- shorten frames or "
            "reduce repeat-block item counts"
        )

    return data


def generate_video(
    brief, display_name, api_key, model,
    fallback_model=None, provider="openrouter",
    voice_guidance="", assets_block="", social_proof=None, cta_text="",
    avoid_templates="",
):
    """Write a video plan end to end: build the system/user prompt, call the
    LLM, parse + validate the reply. Returns the parsed video-plan dict
    (see parse_video), ready for `builder.hyperframes_project_builder.build_project`.
    """
    system = _build_system(display_name, voice_guidance, social_proof, cta_text)
    prompt = build_prompt(brief, assets_block, avoid_templates)
    return call_text_capability(
        provider, api_key, model, system, prompt,
        fallback_model=fallback_model, timeout=120.0, parse=parse_video,
    )
