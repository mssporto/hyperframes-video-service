# hyperframes-video-service

Generates short-form (YouTube Shorts style) vertical video from a text brief,
using [HyperFrames](https://www.npmjs.com/package/hyperframes) as the render
engine. Fully standalone: no client/tenant concept, no hardcoded brand, no
external dependency on any other repo. Bring your own LLM API key, your own
Modal account, and (optionally) your own brand colours/logo.

Extracted and genericized from a larger multi-client content pipeline as a
clean, self-contained starting point — treat this repo as a base to build on,
not a finished product.

## Architecture

```
brief (topic/script) ──▶ builder.video_writer.generate_video()   [LLM call, your key]
                              │  returns a "video plan": title/description + frames[]
                              ▼
                        builder.hyperframes_project_builder.build_project()
                              │  deterministic, no LLM: fills templates/*.html,
                              │  writes a complete HyperFrames project dir
                              ▼
                        zip_project()  →  base64 zip
                              │
                              ▼
                 POST /create  (Modal, service/app.py)  →  { jobId }
                              │
                        GET /status  (poll)
                              │
                        GET /result  →  raw MP4 bytes
```

The LLM call and the deterministic project build both happen **outside**
Modal (in `builder/`, run locally, in a script, or in n8n via HTTP/Code
nodes) — your LLM API key never has to live in the Modal image. Only the
finished project (as a zip) and the render job itself go to Modal. If you'd
rather do the build step remotely too (e.g. because n8n can't run Python),
the deployed service also exposes a `/build` endpoint that does the same
`build_project()` call server-side from a plain JSON body — see below.

## Repo layout

```
builder/
  hyperframes_project_builder.py   # deterministic template assembler (no LLM)
  video_writer.py                  # brief -> video plan, via LLM
  video_theme.py                   # brand colours/font/logo -> theme tokens
  theme_common.py                  # WCAG-AA contrast maths
  llm_providers/                   # openrouter.py, fal.py -- swap by string
templates/
  body/ asset/ closing/            # 14 theme-driven HyperFrames templates
  CONTRACT.md                      # the full template/placeholder spec
service/
  app.py                           # Modal app: build / create / status / result / delete
examples/
  generate_short.py                # CLI reference: brief -> rendered MP4, end to end
```

## Setup

1. **Modal account.** `pip install modal && modal token new` (use your own
   Modal account -- this deploys a brand-new app, `hyperframes-video` by
   default, with its own job store and output volume; nothing here can
   collide with any other Modal app you have).
2. **Deploy the render service.**
   ```bash
   cd hyperframes-video-service
   modal deploy -e dev service/app.py    # sandbox environment
   modal deploy service/app.py           # or straight to your "main" env
   ```
   Modal prints the deployed URLs for `build`/`create`/`status`/`result`/`delete`.
3. **An LLM API key.** `builder/llm_providers/` ships OpenRouter and fal.ai
   providers (same `call(api_key, model, system, prompt, timeout) -> str`
   shape) -- set `OPENROUTER_API_KEY` or `FAL_API_KEY` wherever you run the
   writing step. Add a new provider by dropping one more module in
   `builder/llm_providers/` with the same shape.
4. **(Optional) a brand theme.** Skip this to render with
   `builder/video_theme.py::DEFAULT_THEME` (dark background, white text, a
   plain blue accent, no logo). To use your own colours/font/logo, either
   build a theme dict by hand (see the fields in `video_theme.py`'s
   docstring) or call `video_theme.derive_theme(brand_guidelines_text,
   api_key, model)` to have an LLM propose one from free-text brand
   guidelines -- either way, `enforce_readable_theme()` guarantees every
   text/background pairing clears WCAG AA before you ever render.

## Running it locally

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=...
export HYPERFRAMES_SERVICE_URL=https://<your-modal-url>-create.modal.run
python examples/generate_short.py --topic "why most onboarding emails get ignored" --cta "yoursite.com"
```

This writes `short.mp4` in the current directory. Read `examples/generate_short.py`
top to bottom -- it's short and it's exactly what any other caller (n8n
included) needs to replicate.

## Wiring into n8n

n8n can't run this repo's Python directly, so replicate the same 4 steps as
HTTP calls:

1. **Write the plan.** An HTTP Request node (or an AI Agent node) that calls
   your LLM provider with the *same* system prompt shape as
   `builder/video_writer.py::_build_system()` -- either copy that prompt into
   an n8n LLM node, or run `generate_video()` in a small always-on helper
   service you call from n8n. Either way, the output must satisfy
   `builder/video_writer.py::parse_video()`'s schema (a JSON object with
   `youtubeTitle`, `youtubeDescription`, `projectId`, `frames`).
2. **Build the project remotely.** HTTP Request node → `POST /build` on your
   deployed service, body `{"plan": {...}, "theme": {...}}` (theme optional).
   Returns `{"projectZipBase64": "..."}`.
3. **Render.** HTTP Request node → `POST /create` with that same
   `projectZipBase64` (+ an `outputName`). Returns `{"jobId": "..."}`.
4. **Poll and fetch.** A Wait + HTTP Request loop against `GET /status`
   until `status == "complete"`, then `GET /result` for the MP4 bytes (n8n
   can pipe that binary straight into whatever publishing node you use next
   -- YouTube, Metricool, wherever).

## Template contract

Every template in `templates/` is theme-driven (see `templates/CONTRACT.md`)
-- colour, font, and logo are placeholders, never hardcoded, so the same 14
templates work for any brand. If you want a genuinely different visual
style (not just different colours), that's a second template set: copy
`templates/` to a sibling directory, edit the markup/animation freely, and
point a modified `hyperframes_project_builder.TEMPLATES_DIR` at it.

## Audio

`builder/audio/` holds one bundled background-music bed: "Technology - Tech
Technology 90 Second" by BombinSound (Pixabay Content License — free for
commercial use, no attribution required, **not** registered with YouTube
Content ID, so it won't trigger a claim on upload). It's mounted into the
Modal image the same way `templates/` is (via `add_local_dir` in
`service/app.py`), so a request can reference it by its in-container path:

```json
"audio": { "bed_path": "/root/builder/audio/bombinsound-technology-tech-technology-90-second-499581.mp3", "bed_volume": 0.5 }
```

Add more tracks the same way -- drop an MP3 in `builder/audio/`, redeploy
(`modal app stop` then `modal deploy` so a warm container doesn't serve the
old mount), and reference its new `/root/builder/audio/<file>.mp3` path.
`bed_path`/`outro_path` only accept a path that's actually mounted in the
container; there's no way to pass arbitrary audio bytes inline (unlike
`asset_base64` for images) as of this writing.

## What's intentionally NOT included

- No client/tenant config system, no multi-brand switching -- this is a
  single-purpose service. Fork it per project if you need more than one look.
- No publishing step (YouTube/Metricool/etc.) -- this repo's job ends at "a
  rendered MP4 on disk" or "a rendered MP4 in Modal's volume." Publishing is
  a separate concern for your n8n workflow to own.
- No bundled brand assets besides the one BGM track above (icons, SFX,
  logos). `builder/hyperframes_project_builder.py`'s `icon_library`/`icon_sfx`
  plan keys still work if you supply your own files at request time --
  there's just nothing else baked in by default.
