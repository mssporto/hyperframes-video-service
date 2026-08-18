# HyperFrames Frame-Template Library — Assembly Contract

A fixed, enumerable vocabulary of **parameterized, theme-driven HyperFrames frame
templates**. Each template is a self-contained HyperFrames **sub-composition** (an
HTML file wrapped in `<template>`, with its own `#root` and a paused GSAP timeline).
A downstream, non-LLM tool ("the assembler" — `builder/hyperframes_project_builder.py`)
fills a template with real content by plain string substitution, writes the result to
`compositions/frames/<n>.html` of a video project, and wires it into that project's
`index.html` as a sub-composition clip.

This document is the **spec**: it lists every template, every placeholder token, and
the exact substitution rules — precisely enough that a Python script with no other
context can fill a template correctly.

---

## 1. Flat template library, not HyperFrames registry "blocks"

HyperFrames' native reuse mechanism is the **registry** (`hyperframes add <name>`
fetches a "block" from a remote registry, then a human hand-wires it). These templates
are deliberately **not** packaged as registry blocks:

- **Consumption model is different.** Registry blocks are installed *verbatim* and
  wired by a human. Our consumer is a Python assembler doing **string substitution** of
  placeholder tokens (`{{HEADLINE}}`, repeat blocks). Placeholder tokens aren't valid in
  a registry-published block meant to install-and-use as-is.
- **But the file *shape* is native.** A full-frame reusable unit in HyperFrames *is* a
  sub-composition (`<template>`-wrapped root, own `data-composition-id`, own paused
  timeline). Each template here adopts that sub-composition contract faithfully; only
  the packaging is a flat directory + this documented substitution contract rather than
  the registry.

**Net:** native sub-composition structure, flat-library packaging.

Set is **14 templates: 7 body + 5 asset + 2 closing** — covering openers, transitions,
lists, asset reveals, and a closing sequence, without proliferating transition-flavor
variants.

---

## 2. The substitution contract (how the assembler fills a template)

Everything a template needs is plain text substitution — **no templating engine, no
build step, no runtime templating library.** Three mechanisms:

### 2a. `{{FRAME_ID}}` — required in EVERY template

A unique-per-instance id string the assembler assigns to each frame (e.g. `"s01"`, `"s02"`,
… — must be a valid CSS/HTML id and unique within the assembled video). The token appears
in each template in these load-bearing places, and the assembler must replace **all**
occurrences with the same value:

- the root `data-composition-id="{{FRAME_ID}}"`
- the timeline key `window.__timelines["{{FRAME_ID}}"]`
- the timeline's own root lookup `document.querySelector('[data-composition-id="{{FRAME_ID}}"]')`
- SVG `clipPath` ids, where used

`{{FRAME_ID}}` **must** match the `data-composition-id` the assembler puts on the host
clip in `index.html` (HyperFrames' cross-file mount contract — a mismatch renders a
static frame). Uniqueness is why a single template file can be used for multiple frames
in one video without id/selector collisions: the timeline queries elements *within its
own root*, never by global selector.

### 2b. Scalar tokens — `{{NAME}}`

Single-value substitutions. Replace the literal `{{NAME}}` with the value. The full list
per template is in §4. Common ones:

| Token | Value kind | Notes |
| --- | --- | --- |
| `{{PROGRESS_PCT}}` | CSS width, e.g. `"37.5%"` | The frame's position in the WHOLE video (index ÷ total × 100). The assembler computes it; `close-cta` is normally `"100%"`. |
| `{{HEADLINE}}` etc. | short display text | See per-template word/line caps in §4. May contain ONE `[[emphasis]]` marker (§2d). |
| `{{ASSET_SRC}}` | relative image path | Path the render resolves against the project root (e.g. `assets/photo.png`). Asset templates only. |
| `{{ASSET_ALT}}` | short alt string | Plain text, no quotes that would break the `alt="…"` attribute. |
| `{{ICON_SVG}}` | raw inline `<svg>…</svg>` | OPTIONAL. See §2e. |

### 2c. Repeat blocks — variable-length lists

Three templates host a variable number of items (`body-sequential-list`,
`body-step-list`, `close-social-proof`). Each marks a repeatable region with HTML comments:

```html
<!-- hf:repeat:<name> start -->
   … one specimen item, containing per-item {{TOKENS}} …
<!-- hf:repeat:<name> end -->
```

The assembler must:
1. Extract the exact markup between the `start` and `end` marker comments (the specimen).
2. For each item, clone the specimen and substitute that item's per-item tokens.
3. Concatenate the clones and replace the whole region **including both marker comments**
   with the concatenation.

The timelines are **count-agnostic**: each queries the DOM for the resulting elements
and builds tweens in a loop, so any item count works with no script edits. (Step numbers
in `body-step-list` are auto-assigned from row order — do **not** template them.)

**Ordering vs. global scalar substitution (§2b): expand repeat blocks FIRST, then run the
single global scalar-substitution pass over the WHOLE resulting file.** Per-item tokens
have no single global value to substitute until the specimen has been cloned once per
item, so this is the only order that can work.

### 2d. Emphasis marker — `[[word]]` or `[[multiple words]]`

Inside any display-text token, wrap one word — or a run of several adjacent words in a
**single** bracket pair — in double square brackets to render it in the theme's accent
colour:

```
"It's a different [[order]]"           → "order" renders in the accent colour
"Measure what [[actually]] moves"      → "actually" renders in the accent colour
```

**Multi-word phrases are supported — wrap them in ONE pair, not one pair per word.**
Every `[[` must have a matching `]]` somewhere in the same token. `close-social-proof`
names do **not** support the marker (names are never re-coloured). Don't put more than
one emphasis run per line — the accent is for emphasis, never dominant.

### 2e. Icon slots — `{{ICON_SVG}}` (optional)

`body-word-emphasis` and each `body-step-list` row carry an optional icon slot. Replace
`{{ICON_SVG}}` with a complete inline `<svg>` element, or with an **empty string** to
omit it. The template degrades gracefully with no icon: the timeline checks for an
`<svg>` child and skips the icon tween; `.icon-wrap:empty { display: none }` collapses an
empty slot.

Icon *selection* (which topical icon fits a beat) is out of scope for these templates —
see `builder/hyperframes_project_builder.py`'s `icon_library`/`pick_icon_for_text`.

---

## 3. Themed tokens (global, one value per video)

Every template in this library is theme-driven: colour, font, and logo are ALL
placeholders, never hardcoded. `builder/video_theme.py::theme_tokens(theme)` produces
the map from a plain theme dict; `build_project()` merges it into the per-frame token
set, substituted in the same pass as `{{FRAME_ID}}`/`{{PROGRESS_PCT}}`.

| Token | Value |
| --- | --- |
| `{{THEME_BG}}` | `#RRGGBB` flat background |
| `{{THEME_TEXT}}` | `#RRGGBB`, WCAG-AA-guaranteed vs bg |
| `{{THEME_LEAD_TEXT}}` | `#RRGGBB`, AA vs bg (used by `close-social-proof`) |
| `{{THEME_ACCENT}}` | `#RRGGBB` single accent |
| `{{THEME_ACCENT_TEXT}}` | `#RRGGBB`, AA vs accent |
| `{{THEME_FONT}}` | a real CSS `font-family` value with a generic fallback |
| `{{THEME_FONT_IMPORT}}` | a full `@import url("…");` for the brand font, or `""` |
| `{{LOGO_MARKUP}}` | `<img src="…" alt="" />` for a real logo, or `""` |

**Placement.** The base colour/font tokens land in each template's own `:root { … }`
custom-property block (`--theme-bg`, `--theme-text`, `--theme-lead-text`,
`--theme-accent`, `--theme-accent-text`, `--theme-font`); the rest of the CSS
references them via `var(--theme-*)`. `{{THEME_FONT_IMPORT}}` and `{{LOGO_MARKUP}}` are
the only two themed tokens that sit outside `:root` (an `@import` cannot live in
`:root`; the logo is markup, not a property).

**Translucent accent variants** (card fill, tag chip, progress track, card border) are
**not** separate tokens — they're derived from the single `--theme-accent` inside each
template's `:root` via `color-mix(in srgb, var(--theme-accent) <α>%, transparent)`, so
one accent is the single source of truth.

**Logo.** If there's no logo configured, `{{LOGO_MARKUP}}` is `""` and the slot renders
empty (its container carries `:empty { display: none }`) — never a fallback mark. In
`close-cta` the slot keeps `data-role="wordmark"`, so its entrance animation still runs
harmlessly on an empty wrap.

---

## 4. Template reference

Every template lives under `templates/{body,asset,closing}/`. "Slot" = the recommended
`data-duration` (seconds) for the host clip in `index.html`; each internal animation
completes well inside it and then holds.

### Body templates (`body/`) — no asset

| Template | Purpose | Tokens | Slot |
| --- | --- | --- | --- |
| **body-stroke-hook** | Opening hook. Stroke-outline setup line, solid-accent payoff line lands beneath, accent-line draws under it. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{HEADLINE_TOP}}` (2–4 words) · `{{HEADLINE_PAYOFF}}` (1–3 words, accent) | ~3.2s |
| **body-word-emphasis** | One idea, one accent word, on an icon + accent-line stage. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{ICON_SVG}}` (optional) · `{{HEADLINE}}` (3–6 words, may contain one `[[emphasis]]`) | ~3.0s |
| **body-split-contrast** | Two-part tension: setup clause (lead tone) → accent divider draws → turn clause (primary tone). | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{CLAUSE_A}}` · `{{CLAUSE_B}}` (may contain one `[[emphasis]]`) | ~3.4s |
| **body-bridge** | Momentum/bridge beat: a single tight line, fastest tempo in the set, no icon. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{HEADLINE}}` (2–5 words, may contain one `[[emphasis]]`) | ~2.2s |
| **body-standout-line** | The screenshot-worthy statement: biggest type, up to 3 lines, accent-line above, long hold. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{LINE_1}}` (required) · `{{LINE_2}}` (optional, empty to omit) · `{{LINE_3}}` (optional). Any line may contain one `[[emphasis]]`. | ~3.6s |
| **body-sequential-list** | Multi-line staggered list that ACCUMULATES (each line lands and stays), accent index tick per line. REPEAT BLOCK `line`. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · per line: `{{LINE_TEXT}}` (may contain one `[[emphasis]]`) | ~`1.0 + 0.5·N`s |
| **body-step-list** | Dense numbered method: tinted-card rows (square accent badge, optional icon, label) land in sequence with a focus dim-ladder. REPEAT BLOCK `row`. Step numbers auto-assigned. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · per row: `{{ICON_SVG}}` (optional) + `{{STEP_LABEL}}` | ~`1.0 + 1.2·N`s |

### Asset templates (`asset/`) — one image each

All take `{{FRAME_ID}}`, `{{PROGRESS_PCT}}`, `{{ASSET_SRC}}`, `{{ASSET_ALT}}` plus the
headline token(s) noted. Images render sharp (0px).

| Template | Purpose | Extra tokens | Slot |
| --- | --- | --- | --- |
| **asset-reveal** | Headline up top; asset rises from below into a sharp accent-framed panel. | `{{HEADLINE}}` (3–8 words, may contain one `[[emphasis]]`) | ~3.4s |
| **asset-card** | Headline above; asset in a tinted rounded card that scales in (image stays sharp). | `{{HEADLINE}}` | ~3.2s |
| **asset-comparison** | Hard 50/50 top/bottom split: headline band up top, asset fills the lower half and wipes in behind an accent seam. | `{{HEADLINE}}` | ~3.2s |
| **asset-fullbleed** | Asset fills the frame with a slow Ken-Burns push; a scrim over the photo carries the headline, lower third. Give it a 9:16-friendly image. | `{{HEADLINE}}` | ~3.4s |
| **asset-letterbox** | Asset in a centered horizontal band that opens from its centre-line; a short line above and below. | `{{HEADLINE_ABOVE}}` · `{{HEADLINE_BELOW}}` (each 2–6 words, may contain one `[[emphasis]]`) | ~3.4s |

### Closing templates (`closing/`) — the mandatory closing sequence

The mandatory sequence is any number of social-proof slides (0+) then the closing-hook/CTA
slide.

| Template | Purpose | Tokens | Slot |
| --- | --- | --- | --- |
| **close-social-proof** | Social-proof beat — reusable for any number of "brand names" style slides. Tag chip + lead-in + a set of names, each landing with an accent highlight-sweep. Names are TEXT ONLY (never fabricated logos). REPEAT BLOCK `name`. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` · `{{TAG_LABEL}}` (e.g. `Client work` / `Recognition`) · `{{LEAD_IN}}` (lead-in clause) · per name: `{{NAME}}` | ~`0.8 + 0.18·W + 0.35·N + 0.3`s (N = names, W = `{{LEAD_IN}}` word count) |
| **close-cta** | Final beat: centered logo, the closing hook line, one solid accent CTA rectangle with contact. The ONLY frame with the full wordmark slot; progress bar full. | `{{FRAME_ID}}` · `{{PROGRESS_PCT}}` (`"100%"`) · `{{HEADLINE}}` (the hook line, 3–8 words, may contain one `[[emphasis]]`) · `{{CTA_TEXT}}` (button label, e.g. a domain/handle) | ~3.8s |

Keep names to ~3 per social-proof slide for 9:16 legibility.

---

## 5. Assembling a full video (host wiring)

For each frame, the assembler:

1. Picks a template, assigns a unique `{{FRAME_ID}}`, substitutes tokens (and expands any
   repeat block), writes the result to `compositions/frames/<frameId>.html`.
2. Adds a host clip to the project `index.html`, INSIDE the `#root` composition:

   ```html
   <div id="el-<frameId>" class="scene"
        data-composition-id="<frameId>"
        data-composition-src="compositions/frames/<frameId>.html"
        data-start="<cumulative seconds>"
        data-duration="<the template's slot seconds>"
        data-track-index="<n, increasing so later frames paint on top>"
        data-width="1080" data-height="1920"></div>
   ```

   `data-composition-id` here MUST equal the frame's `{{FRAME_ID}}`. Give each scene its own
   increasing `data-track-index`. For plain cuts, set each `data-start` to the previous
   frame's `start + duration`. For crossfade/push transitions, overlap neighbors by ~0.35s
   and animate the incoming scene at the host level.
3. Sets the `#root` `data-duration` to the total and registers an (empty or
   transition-bearing) `window.__timelines["main"]` paused timeline. The host page must load
   GSAP; the templates rely on the host's GSAP and deliberately include no GSAP `<script src>`
   of their own.
4. Audio (bed / SFX / outro sting) is layered at the host level — not part of these
   templates.

All of this is done for you by `builder/hyperframes_project_builder.py::build_project()`.
You should never need to hand-write `index.html`.
