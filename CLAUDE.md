# CLAUDE.md

Operating notes for an AI agent (or a human) working in a HyperFrames +
Modal short-form video render pipeline shaped like this one: an LLM writes a
"video plan" (a list of frames, each a template name + text tokens), a
deterministic builder fills a fixed set of theme-driven HTML templates from
that plan, and a Modal service renders the result with a headless-Chrome
HyperFrames CLI run. Two clearly separate halves below: facts/gotchas, then
agent operating rules. Written to survive being copied into a sibling or
forked repo of the same shape — nothing here should assume this exact
project's name, brand, or file layout beyond "builder / templates / service."

## Architecture, in one pass

```
brief ──▶ LLM call (builder/video_writer.py)         → video plan (JSON)
      ──▶ deterministic template fill (builder/hyperframes_project_builder.py)
      ──▶ zip a HyperFrames project dir
      ──▶ Modal: POST /create → { jobId }  (long-running render, spawned)
      ──▶ Modal: GET /status  (poll)
      ──▶ Modal: GET /result  → MP4 bytes
      ──▶ Modal: DELETE /delete (free storage)
```

The LLM call and the template fill are pure Python and can run anywhere
(local script, n8n Code node, a small helper service) — they never need to
run inside the Modal image, and the LLM key never needs to live there. Only
the finished project zip and the render job cross into Modal. A `/build`
endpoint exists so a non-Python caller (n8n) can do the template-fill step
server-side too — same function, just reachable over HTTP.

Templates are **not** freeform: a fixed registry of named templates, each
with required/optional scalar tokens (`{{TOKEN}}`) and, for repeat blocks, a
list of per-item tokens. A video plan only ever picks templates and fills
their tokens — it never authors new HTML. Theme (colors, font, logo,
background pattern) is a second, separate substitution pass applied
globally across every frame, so the same template set works for any brand.

## Facts & gotchas

**Modal web endpoints are public URLs with zero auth by default.** Anyone
who has the link can call `create`/`status`/`result`/`delete` — run renders
on your compute, or read/delete arbitrary job records — unless you add auth
yourself. There's no implicit protection from the URL being hard to guess;
treat every deployed endpoint as public until you've explicitly gated it
(bearer token checked against a Modal Secret is the pattern used here — see
`service/app.py`'s `_require_auth` / `AUTH_SECRET_NAME`).

**Don't name an endpoint function the same as something you import from its
own framework.** This repo had a `status` endpoint function that shadowed
`from fastapi import status` at module scope — every reference to
`status.HTTP_401_UNAUTHORIZED` inside `_require_auth` silently resolved to
the *endpoint function* instead (an `AttributeError`, turning every 401 into
an opaque 500). If an endpoint's natural name collides with a framework
export, alias the import or hardcode the constant instead.

**A Modal image's `add_local_dir`/`add_local_file` calls must be the LAST
build steps chained onto that `Image`.** Any `pip_install`/`run_commands`/
`.env()` added afterward raises `InvalidError` on deploy. Bundle local
source/templates last, after every other image-build step.

**With `copy=False` (the default), local files mount at container
*startup*, not into an image layer — a still-warm container can keep
serving the old files/code after a redeploy.** `modal deploy` succeeding is
not proof the new code is what's actually answering requests. Run
`modal app stop -e <env> <app-name> --yes` immediately before `modal
deploy` whenever the change matters (security fixes especially) to force
every container to restart cold.

**The render step has a real, enforced time budget** (this repo: 540s
subprocess timeout inside a 600s function timeout) — a headless-Chrome run
of a GSAP timeline. A template with many animated elements, a long stagger,
or heavy per-frame SVG (think: dense charts, lots of simultaneously-animated
data points) pushes real render time up, not just perceived complexity.
Render-test any visually heavy new template on its own before assuming it's
cheap — don't extrapolate render cost from how the template *looks* in a
browser preview, which isn't running the same renderer.

**Leftover `{{TOKEN}}`-shaped text after substitution means a token was
missed, and there's a real function for catching it** —
`find_unresolved_placeholders()` in the builder. Every new template needs
its required tokens declared in the registry *and* actually present in the
HTML, or a plan that omits one fails at build time with a clear error
instead of shipping a broken frame. Reach for this function while iterating
on a new template rather than eyeballing the rendered output for `{{...}}`
leaks.

**WCAG-AA contrast enforcement here is text/background only.** The theme
system guarantees every text/background color pairing clears AA before
render — it has no concept of anything else (chart lines, data-series
colors, gridlines, an accent used as a fill instead of text). Adding
data-viz elements doesn't inherit this guarantee for free.

**Personal/account-identifying info leaks into example files and docs far
more easily than into the actual application code.** A real deployed Modal
URL, a real cloud-storage file ID, a real brand/domain name — none of these
look dangerous in a docstring or a sample payload the way a credential does,
but they identify a real account/person the moment the repo is shared.
Anything under `examples/`, in a README, or in a committed sample config is
effectively public the instant the repo is — write placeholders there, not
"realistic-looking" real values with the risky part removed.

**Google Drive / Sheets integration, if a fork ever adds one, carries two
sharp edges worth knowing before hitting them:** `files().list()` against a
folder in a Shared Drive silently returns zero files without
`supportsAllDrives=True, includeItemsFromAllDrives=True` (no error — just an
empty result that looks like "the folder is empty"); and a service account
has zero personal-Drive storage quota, so it can only create files inside a
genuine Shared Drive, never a personal "My Drive" folder no matter how that
folder is shared — uploading into a personal-Drive-owned folder fails with
`403 storageQuotaExceeded` even when the folder is shared as writer.

**Vision/image-model calls must use the file's real MIME type, not an
assumed default.** A `data:<mime>;base64,...` URI built with a hardcoded
`image/png` gets rejected outright by some providers when the actual file is
`.webp`/`.jpg`/anything else — this only surfaces once an input source isn't
guaranteed to be one fixed format.

## Agent operating rules

These are the behaviors that matter most for someone (human or agent)
extending this repo — adding templates, especially heavier/graphic ones,
without quietly breaking the parts that make every template composable.

- **A new template is not done until it's in the registry, in the contract
  doc, and rendered once for real.** All three: the template's HTML file,
  its entry in `TEMPLATE_REGISTRY` (required/optional tokens declared
  accurately), and a line in `templates/CONTRACT.md`. Skipping the registry
  entry means a video plan can reference the template and fail with a
  confusing error instead of a clear "unknown template" one; skipping the
  contract doc means the next person (or agent) has to read the HTML to
  learn what tokens it needs.
- **Never hardcode a color, font, or logo inside a template.** Every visual
  property that varies by brand goes through a `{{THEME_*}}` token, filled
  by the same global substitution pass as every other template. A template
  that looks right for one theme but has a literal hex value baked in will
  look wrong, silently, for every other theme.
- **Run the WCAG-AA check on any new color role you introduce, don't assume
  the existing enforcement covers it.** If a template needs a new kind of
  colored surface (a chart fill, a second accent, a gridline), that pairing
  needs its own explicit contrast check — the shipped
  `enforce_readable_theme()` only reasons about the token names it already
  knows.
- **Render-test before calling a template "done," not just before shipping
  the whole feature.** A template that only exists as reviewed HTML/CSS has
  not been proven cheap to render, free of `{{...}}` leaks, or actually
  legible at 1080×1920 — all three are checked by one real render.
- **Don't touch deploy, auth, or secrets without saying so first.** A
  `modal deploy`, a `modal app stop`, or a change to what a Secret is
  expected to contain affects a live, callable service — narrate it before
  doing it, the same as any other action with a blast radius bigger than
  this repo's working tree.
- **Treat anything in `examples/`, README snippets, or sample payloads as
  already public.** Before adding a URL, ID, filename, or brand name to any
  of those, ask whether it's a real value that identifies a real account —
  if yes, it's a placeholder, not an example.
- **Verify a claim before making it, especially about a deployed service.**
  "Fixed" means the live endpoint was actually re-hit and behaved
  differently, not that the local diff looks correct — a warm container, a
  wrong secret key, or a stale mount can all make a real fix produce no
  observable change until you check.
- **When genuinely unsure how much a new template category (e.g.
  data-viz/graph-heavy templates) should diverge from the existing visual
  language, ask rather than guess a house style.** The existing 14 templates
  share one deliberate look (sharp corners except one named exception, one
  accent color, one font) — a new category either extends that discipline
  or explicitly breaks from it, and that's a call worth surfacing, not
  making silently.
