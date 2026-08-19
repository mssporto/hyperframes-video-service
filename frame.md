---
version: alpha
name: dahiana.work — Frame (video / frame layer)
description: >
  Video-first companion to dahiana.work's design.md. The unit is the frame
  (1080×1920, vertical short-form only). Atoms carried over verbatim from the
  live site: cream ground, near-black ink, one royal-blue accent, Archivo
  throughout, and the site's real 64px hairline grid as atmosphere. Unlike a
  freeform HyperFrames project, composition here is NOT free — this repo's
  builder (builder/hyperframes_project_builder.py) fills a fixed menu of 14
  parameterized templates (templates/CONTRACT.md) by token substitution; a
  video plan picks templates, it never authors new HTML. So "Frame
  Treatments" below documents what each of those 14 templates actually
  renders under this brand, not a menu of layouts to invent.
unit: the frame — 1080×1920 (9:16). No 16:9/1:1 variant exists in this repo.
principle: cream and ink carry every frame · one accent, never a second · the
  grid is atmosphere, never a background you draw on top of

colors:
  bg: "#f1efea"
  text: "#131410"
  lead-text: "#4b4b47"
  accent: "#1d4ed8"
  accent-text: "#ffffff"
  grid-line: "#e6e3dc"
  logo-url: "https://lh3.googleusercontent.com/d/1Q1JyZFJ21O9sfUmPsbSMlj_pzR7SX2mb"

typography:
  fontFamily: "Archivo, sans-serif"
  # Measured off the actual templates (grep'd, not invented) — every video
  # frame's real font-size/weight/line-height/letter-spacing, grouped by role.
  stroke-hook-setup:  { cqw: 9.4,  weight: 800, lineHeight: 1.05, tracking: "-0.02em", role: "body-stroke-hook HEADLINE_TOP" }
  stroke-hook-payoff: { cqw: 13.0, weight: 800, lineHeight: 1.0,  tracking: "-0.02em", role: "body-stroke-hook HEADLINE_PAYOFF (stroke-outline, accent fill)" }
  standout-line:      { cqw: 9.6,  weight: 800, lineHeight: 1.06, tracking: "-0.02em", role: "body-standout-line LINE_1/2/3" }
  bridge:             { cqw: 8.2,  weight: 800, lineHeight: 1.08, tracking: "-0.02em", role: "body-bridge HEADLINE" }
  word-emphasis:      { cqw: 6.7,  weight: 700, lineHeight: 1.15, tracking: "-0.02em", role: "body-word-emphasis HEADLINE" }
  split-contrast:     { cqw: 6.1,  weight: "600/700", lineHeight: 1.15, tracking: "-0.02em", role: "body-split-contrast CLAUSE_A (600, lead-text) / CLAUSE_B (700, text)" }
  sequential-list:    { cqw: 5.4,  weight: 700, lineHeight: 1.16, tracking: "-0.02em", role: "body-sequential-list LINE_TEXT" }
  step-badge:         { cqw: 3.2,  weight: 800, role: "body-step-list auto-numbered square badge (accent-text on accent fill)" }
  step-label:         { cqw: 2.75, weight: 700, lineHeight: 1.2,  tracking: "0.01em", upper: true, role: "body-step-list STEP_LABEL" }
  asset-headline:     { cqw: "5.4–7.0", weight: "700/800", lineHeight: "1.1–1.16", tracking: "-0.02em", role: "asset-* HEADLINE / HEADLINE_ABOVE / HEADLINE_BELOW" }
  social-proof-tag:   { cqw: 1.4,  weight: 500, tracking: "0.06em", upper: true, role: "close-social-proof TAG_LABEL" }
  social-proof-lead:  { cqw: 3.2,  weight: 400, lineHeight: 1.4,  tracking: "-0.01em", role: "close-social-proof LEAD_IN (lead-text)" }
  social-proof-name:  { cqw: 6.4,  weight: 700, lineHeight: 1.16, tracking: "-0.02em", role: "close-social-proof NAME" }
  close-cta-headline: { cqw: 5.8,  weight: 700, lineHeight: 1.15, tracking: "-0.02em", role: "close-cta HEADLINE" }
  close-cta-button:   { cqw: 3.0,  weight: 600, tracking: "0.01em", role: "close-cta CTA_TEXT (accent-text, on accent fill)" }

spacing:
  grid-cell: "64px"
  progress-bar-height: "4px"
  brand-mark: "6cqw square, 5cqw inset from top-left"
  card-radius: "16px"

components:
  bg-layer:
    backgroundColor: "{colors.bg}"
    backgroundImage: "hairline grid, {colors.grid-line}, 1px lines, {spacing.grid-cell} squares, both axes"
    description: "Every frame's full-bleed ground. Never themed to a second color — one flat cream field with the site's real grid texture, nothing else."
  brand-mark:
    size: "{spacing.brand-mark}"
    position: "top-left on every body/asset/social-proof frame"
    content: "{colors.logo-url}, or empty (collapses, never a fallback mark)"
  progress-bar:
    height: "{spacing.progress-bar-height}"
    track: "color-mix({colors.accent} 20%, transparent)"
    fill: "{colors.accent}"
    description: "Bottom-edge, full-width. The only other persistent chrome besides the brand mark."
  accent-line:
    stroke: "{colors.accent}"
    width: "4px"
    description: "Self-draws (stroke-dashoffset) under a headline in several body templates — a signature beat, not a border."
  tinted-card:
    radius: "{spacing.card-radius}"
    shadow: "none"
    description: "The ONE rounded surface in the system (asset-card panel, body-step-list rows). Everything else is 0px / sharp."
  cta-rectangle:
    fill: "{colors.accent}"
    radius: "0"
    textColor: "{colors.accent-text}"
    description: "close-cta's solid accent button. Text on it is ALWAYS accent-text (white) — near-black on royal blue drops to ~2.8:1 and fails AA, same rule as the live site's accent-usage note."
  emphasis-word:
    color: "{colors.accent}"
    description: "The [[double-bracket]] marker inside any text token. One run per line, max. This is the system's only in-line color accent — there is no separate highlight template."
---

# dahiana.work — Frame (video / frame layer)

## Overview

This is the frame-scale companion to [`dahiana_work/design.md`](../dahiana_work/design.md) — I read it, plus the site's live `tokens.css`/`BaseLayout.astro`, to derive the values here, rather than inventing a "video-appropriate" palette. Per the consumption contract this format follows (`hyperframes-creative/references/video-composition.md`): **colors, fonts, and Do's/Don'ts are strict — carried over from the site exactly; only scale, spacing, and per-template application are adapted for video.** Where video numbers diverge from the site's web numbers, that's called out explicitly below, not smoothed over.

The frame is **cream and ink, one accent, one font.** Cream (`#f1efea`) and near-black (`#131410`) do the work everywhere; royal blue (`#1d4ed8`) is the single accent — for emphasis words, the progress bar, and the one solid CTA rectangle — never a second color, never a fill with the wrong text color on top. Archivo carries every size, headline to CTA button, matching the site's "one font for the entire site" rule. The only atmosphere is the site's real 64px hairline grid; it's texture, not a second background to design against.

**This repo's builder does not compose freeform layouts.** Every "frame" is one of 14 fixed templates in `templates/{body,asset,closing}/`, filled by scalar-token substitution (`builder/hyperframes_project_builder.py`). A video plan's only creative decisions are: which template, in what order, and what text goes in its tokens. This doc's "Frame Treatments" section is therefore a description of what exists, not a menu to design new ones from — if a genuinely new layout is wanted, that's a new template file, a code change, not a frame.md edit.

**Key characteristics at frame scale:**

- **Cream ground + the real site grid** (`#e6e3dc`, 64px, both axes) — no other background treatment exists in any template.
- **Archivo throughout**, weights 600–800 for display, one weight lighter (400/500/600) for lead-ins/labels/CTA text.
- **One accent, `#1d4ed8`** — emphasis words, progress bar, accent-line self-draws, the close-cta button fill. Never introduced as a second hue.
- **Sharp corners (0px) everywhere** except the one rounded surface (`16px`, tinted cards) — no shadows anywhere.
- **Logo, not wordmark.** The brand mark is a small top-left image on every frame and the same slot (larger) in `close-cta`; if no `logo_url` is set, the slot renders empty — never a fallback mark.

## The Frame

- **Only ratio: 1080×1920 (9:16).** No 16:9 or 1:1 template exists in this repo; if one is ever needed it's new template files, not a reflow of these.
- **Persistent chrome, same on every frame:** the top-left brand mark and the bottom progress bar. `close-cta` is the one exception — it swaps the small mark for the full logo, centered, and its progress bar is always at 100%.
- **The grid is drawn once, at the frame ground.** No template draws its own competing texture; a themed template that wanted a *different* atmosphere would need `bg_pattern` cleared or replaced in the theme dict, not a change per-frame.

## Colors

`{colors.bg}` is the only background any template uses — there is no secondary surface color, no dark variant in play here (the site's own `#0a0a08` footer band was evaluated and explicitly **not** chosen for video; see Known Gaps). `{colors.text}` is every headline and primary body token; `{colors.lead-text}` is exactly two things — `body-split-contrast`'s `CLAUSE_A` and `close-social-proof`'s `LEAD_IN` — never a headline. `{colors.accent}` is the sole accent: emphasis words, the progress bar fill, accent-line self-draws, `close-cta`'s button fill. `{colors.accent-text}` exists for exactly one reason — text/icon color *on* the accent fill, since near-black on `#1d4ed8` fails AA (same finding as the site's own accent-usage rule). `{colors.grid-line}` (`#e6e3dc`) is the hairline grid and nothing else — it is never used as a text or accent color.

**Divergence from the site, stated plainly:** the site's `color-text-accent-on-dark` (`#6d94ff`, for accent text against the dark footer) has no equivalent here, because no template renders on a dark ground. If a dark-ground template variant is ever built, that token — not a guessed new one — is the correct value to reach for.

## Typography

One family, Archivo, at eight weights across the ramp (400/500/600/700/800), sized in `cqw` per-template (see the frontmatter ramp — every value there was measured directly off the shipped templates, not designed fresh). Two things the site's own rule doesn't quite carry over 1:1, called out rather than papered over:

- **Letter-spacing is `-0.02em`** on most display roles here, vs. the site's documented `-0.03em` headline tracking. Close, not identical — a real, small divergence from a different render context (GSAP-animated `<template>` frames vs. a static page), not an error to "fix" by matching the number exactly.
- **`body-step-list`'s `STEP_LABEL` is uppercase, tracked +0.01em** — the one place in the system that departs from sentence case, because it's reading as a compact numbered-method label, not a headline. Every other text token is sentence case, matching the site's rule.

The emphasis marker (`[[word]]`, rendered in `{colors.accent}`) is this system's *only* in-line color device — there's no separate "highlight" template, matching the site's own "one font, one accent, hierarchy from scale/weight" philosophy applied to motion typography instead of a static page.

## Depth & Surface

Flat. `box-shadow: none` on every template, confirmed by reading the CSS, not assumed. The **only** rounded surface anywhere is `16px`, on exactly two things: the `asset-card` image panel and each `body-step-list` row — everything else, including every other template's asset frame, is `border-radius: 0`. This is a genuine (small) divergence from the site's own button convention ("sharp-cornered rectangle, no border-radius, or max 2–4px") — `16px` is bigger than that ceiling. Worth deciding deliberately (tighten the two video card radii to match the site, or accept the divergence as video's own convention) rather than carrying it forward by default.

## Shapes

- **16px radius** — `asset-card` panel, `body-step-list` row cards. The one exception.
- **0 (sharp)** — every other surface: body/closing frame content, all other asset frames, the `close-cta` button, the progress bar, the brand mark's bounding box.

## Components

See the frontmatter `components` block for the normative values. In prose:

- **bg-layer** — the cream ground + hairline grid, drawn once per frame, never doubled or swapped per-template.
- **brand-mark** / (in `close-cta` only) the full logo, centered — the only two places the logo appears; every other frame gets the small top-left mark.
- **progress-bar** — bottom-edge, accent fill on a 20%-accent track, present on every frame including `close-cta` (where it's always full).
- **accent-line** — the self-drawing stroke under several body templates' headlines; a motion beat, not a static rule.
- **tinted-card** — the one rounded surface (see Depth & Surface's divergence note).
- **cta-rectangle** — `close-cta`'s solid accent button; text on it is *always* `accent-text`, never `text`.
- **emphasis-word** — the `[[...]]` marker; one run per line, never in `body-step-list`'s `STEP_LABEL` (no accent engine there).

## Frame Treatments

Not a menu to design from — a description of the 14 fixed templates (`templates/CONTRACT.md` §4 has the full mechanical spec; this is the brand read of the same 14, plus which are actually reachable through the n8n workflow's agent today).

**In active use by the shipped n8n workflow's Video Copy Agent** (body + one mandatory closing frame; no asset frames wired up, no social-proof frames prompted for):

1. **body-stroke-hook** — opener. Outline-stroke setup line, solid-accent-fill payoff line beneath. The single largest type in the system (`13cqw` payoff).
2. **body-word-emphasis** — one idea, one `[[emphasis]]` word, on an accent-line stage.
3. **body-split-contrast** — two-clause tension: lead-text setup → text turn.
4. **body-bridge** — fastest beat, one tight line, no decoration.
5. **body-standout-line** — the biggest hold, up to 3 lines, screenshot-worthy statement.
6. **body-sequential-list** — an accumulating list, 2–3 `LINE_TEXT` items.
7. **body-step-list** — the one rounded-card template; numbered method steps, 2–3 `STEP_LABEL` items.
8. **close-cta** *(mandatory, always last)* — full logo, one hook line, the solid accent button.

**Exist in `templates/`, theme-ready, but not currently reachable through the n8n agent's prompt** (no image-sourcing step is wired up, and no social-proof list is configured):

9–13. **asset-reveal / asset-card / asset-comparison / asset-fullbleed / asset-letterbox** — each needs a real image (`asset_base64`/`asset_filename` via `/build`); this brand's asset frames would put the image behind the same accent-bordered/tinted-card treatment as everything else — no separate visual language for photos.
14. **close-social-proof** — reusable for a "client work" and a "recognition" beat before `close-cta`; would need real names supplied (see Approved Entities) and a second `TAG_LABEL`/`LEAD_IN` pair per use.

## Composition Rules

### Do

- Keep every frame on `{colors.bg}` with the grid drawn once — never a second background color, never a competing texture.
- Put `[[emphasis]]` on the single word or short phrase carrying the frame's point — one run, one line, never more.
- Use `{colors.accent-text}` (white) for any text sitting on an accent fill — never `{colors.text}`.
- Vary body template choice across a video (no single template twice in most short runs) — the templates carry the visual variety; the palette stays constant.

### Don't

- Don't introduce a second accent color, a dark-ground variant, or a gradient background — none exist in this system today.
- Don't put `{colors.text}` (near-black) directly on `{colors.accent}` — that pairing fails AA (~2.8:1); use `{colors.accent-text}`.
- Don't round a corner outside the two named `16px` cards — sharp is the rule, rounded is the named exception.
- Don't use the `[[emphasis]]` marker inside `body-step-list`'s `STEP_LABEL` — it renders literal brackets there, no accent engine reads it.
- Don't invent client names, awards, or any other entity for `close-social-proof` — see Approved Entities.

## Aspect-Ratio Behavior

Not applicable — this repo renders 1080×1920 only. If a 16:9 or 1:1 variant is ever wanted, it is new template files with their own layout math, not a CSS media query on these.

## Approved Entities

**None are defined for this brand.** dahiana.work's `design.md` names no client roster or awards list (unlike the multi-client system this repo was extracted from, which had a real "Approved Entities" list to draw `close-social-proof` from). Until real names exist: skip `close-social-proof` entirely, exactly as the current n8n agent prompt already does — never fabricate a client or award name to fill the template.

## Numerals & Claims

This brand has no stat-figure or numeral-display template in active use, so this section is mostly moot today — but the rule holds if one is ever wired up: any number, date, or client claim in a frame must trace to the actual brief/topic given to the Video Copy Agent, never invented to make a frame "complete." The agent's own system prompt already states a version of this ("GROUND TRUTH RULE") — this doc is the second place it's written down, not a contradiction of it.

## Pre-Render Self-Audit

- **Palette** — cream ground, near-black text, one royal-blue accent, white on accent fills. No second color anywhere.
- **Grid** — one hairline grid at `{spacing.grid-cell}`, drawn once, never doubled.
- **Type** — Archivo only, sentence case except `STEP_LABEL` (uppercase by design), tracking `-0.02em` on display roles.
- **Shape** — sharp corners except the two named `16px` cards; zero shadows anywhere.
- **Logo** — present (small mark or, in `close-cta`, full logo) or empty — never a fallback mark.
- **Entities** — no invented client/award names; `close-social-proof` skipped until real ones exist.
- **Emphasis** — at most one `[[...]]` run per line, never in `STEP_LABEL`.

## Known Gaps

- **This doc is not yet wired into any script.** The theme values it documents currently live duplicated in `builder/video_theme.py::DEFAULT_THEME` (generic placeholder, not this brand) and as raw hex/strings in the shipped n8n workflow's `Video Brief` node. Nothing here changes that automatically — reconciling them (e.g. a small loader that reads `frame.md`'s frontmatter into a theme dict) is a deliberate follow-up, not done as part of writing this file.
- **Dark-ground variant untested.** The site's real dark footer palette (`#0a0a08` bg, white text, `#6d94ff` accent-on-dark) exists and is documented in `design.md`, but no template here has been rendered against it — "Colors" above names the right tokens to reach for if that's ever wanted, but nobody has verified contrast/legibility against these specific templates yet.
- **Card-radius divergence (16px vs. the site's ≤4px button ceiling) is unresolved** — flagged in "Depth & Surface," not fixed here.
- **Only 8 of 14 templates are reachable** through the current n8n workflow's agent prompt (see Frame Treatments) — the 5 asset templates and `close-social-proof` are theme-ready but need, respectively, an image-sourcing step and real Approved Entities before they can be used.
- **No motion guidance here on purpose** — `templates/CONTRACT.md` §3's house-style motion grammar (eases, stagger timing, the one sanctioned overshoot) already covers it and isn't brand-specific; duplicating it here would just create a second copy to keep in sync.
