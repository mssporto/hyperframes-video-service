# hyperframes-video-service

Generates short-form vertical video (YouTube Shorts style) from a text brief,
using [HyperFrames](https://www.npmjs.com/package/hyperframes) as the render
engine. Standalone: no client/tenant concept, no hardcoded brand. Bring your
own LLM API key, your own Modal account, and (optionally) your own brand
colours/logo.

## Architecture

```
brief (topic/script) ──▶ builder.video_writer.generate_video()   [LLM call]
                              │  returns a "video plan": title/description + frames[]
                              ▼
                        builder.hyperframes_project_builder.build_project()
                              │  fills templates/*.html, writes a project dir
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

The LLM call and project build happen outside Modal. Only the finished
project zip and the render job go to Modal. A `/build` endpoint is also
available to run the project-build step server-side from a JSON body, for
callers (e.g. n8n) that can't run this repo's Python.

## Repo layout

```
frame.md                           # example brand spec
builder/
  hyperframes_project_builder.py   # template assembler
  video_writer.py                  # brief -> video plan, via LLM
  video_theme.py                   # brand colours/font/logo -> theme tokens
  theme_common.py                  # WCAG-AA contrast maths
  llm_providers/                   # openrouter.py, fal.py
  audio/                           # bundled royalty-free BGM
templates/
  body/ asset/ closing/            # 14 theme-driven HyperFrames templates
  CONTRACT.md                      # template/placeholder spec
service/
  app.py                           # Modal app: build / create / status / result / delete
examples/
  generate_short.py                # CLI reference: brief -> rendered MP4
```

## Brand spec (`frame.md`)

[`frame.md`](frame.md) follows the format the wider HyperFrames skill
ecosystem resolves automatically (`frame.md` → `design.md` → `DESIGN.md`).
YAML frontmatter (colors, typography, spacing, components) plus a markdown
body (Overview, Colors, Typography, Frame Treatments, Do/Don't, Known Gaps).

The shipped version is an example theme with placeholder values. It's
documentation only — nothing in this repo reads it automatically yet.
`builder/video_theme.py::DEFAULT_THEME` carries its own values independently.

## Setup

1. **Modal account.** `pip install modal && modal token new`.
2. **Create the auth secret.** Every endpoint requires
   `Authorization: Bearer <token>`. Store a random token as a Modal Secret:
   ```bash
   modal secret create hyperframes-video-auth-token AUTH_TOKEN=<your random token> -e dev
   ```
3. **Deploy the render service.**
   ```bash
   cd hyperframes-video-service
   modal deploy -e dev service/app.py    # sandbox environment
   modal deploy service/app.py           # or straight to "main"
   ```
   Modal prints the deployed URLs for `build`/`create`/`status`/`result`/`delete`.
   Create the same secret in any other environment you deploy to.
4. **An LLM API key.** `builder/llm_providers/` ships OpenRouter and fal.ai
   providers (same `call(api_key, model, system, prompt, timeout) -> str`
   shape). Set `OPENROUTER_API_KEY` or `FAL_API_KEY`.
5. **(Optional) a brand theme.** Skip to render with
   `builder/video_theme.py::DEFAULT_THEME`. Or build a theme dict by hand
   (see `video_theme.py`'s docstring), or call
   `video_theme.derive_theme(brand_guidelines_text, api_key, model)`.

## Running it locally

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=...
export HYPERFRAMES_SERVICE_URL=https://<your-modal-url>-create.modal.run
export HYPERFRAMES_AUTH_TOKEN=...   # the AUTH_TOKEN secret value
python examples/generate_short.py --topic "why most onboarding emails get ignored" --cta "yoursite.com"
```

Writes `short.mp4` in the current directory. `examples/generate_short.py` is
the reference for any other caller (n8n included) to replicate.

## Wiring into n8n

Replicate these as HTTP calls. Every HTTP Request node needs
`Authorization: Bearer <token>` (the `AUTH_TOKEN` secret value).

1. **Write the plan.** An LLM/HTTP node using the same prompt shape as
   `builder/video_writer.py::_build_system()`. Output must satisfy
   `builder/video_writer.py::parse_video()`'s schema (`youtubeTitle`,
   `youtubeDescription`, `projectId`, `frames`).
2. **Build.** `POST /build`, body `{"plan": {...}, "theme": {...}}` (theme
   optional). Returns `{"projectZipBase64": "..."}`.
3. **Render.** `POST /create` with that zip (+ an `outputName`). Returns
   `{"jobId": "..."}`.
4. **Poll and fetch.** Wait + `GET /status` until `"complete"`, then
   `GET /result` for the MP4 bytes.

## Template contract

Every template in `templates/` is theme-driven (see `templates/CONTRACT.md`)
— colour, font, and logo are placeholders, so the same 14 templates work for
any brand. A different visual style is a second template set: copy
`templates/`, edit freely, point a modified `TEMPLATES_DIR` at it.

## Audio

Optional background-music bed. Most Shorts/Reels traffic watches muted, so
every template is on-screen text first — audio is a production-value layer,
not the delivery mechanism.

`builder/audio/` holds one bundled track: "Technology - Tech Technology 90
Second" by BombinSound (Pixabay Content License, free for commercial use, no
attribution required, not YouTube Content ID registered).

```json
"audio": { "bed_path": "/root/builder/audio/bombinsound-technology-tech-technology-90-second-499581.mp3", "bed_volume": 0.5 }
```

The bed is looped or trimmed via `ffmpeg` to the video's exact duration, then
written in as a plain `<audio>` element at a flat volume. Omit `audio`
entirely for a silent render.

Add more tracks by dropping an MP3 in `builder/audio/` and redeploying
(`modal app stop` then `modal deploy`, so a warm container doesn't serve the
old mount).

For more (voiceover ducking, EQ, fades), the official HyperFrames skill set
covers it: `npx skills add heygen-com/hyperframes --full-depth` (see
`hyperframes-audio`, `media-use`, `hyperframes-core`, `hyperframes-animation`).

## What's intentionally NOT included

- No client/tenant config system, no multi-brand switching.
- No publishing step (YouTube/Metricool/etc.) — output is a rendered MP4;
  publishing is a separate concern.
- No bundled brand assets besides the one BGM track (icons, SFX, logos) —
  `icon_library`/`icon_sfx` plan keys accept your own files at request time.
