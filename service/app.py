"""
HyperFrames render service — async render pipeline for short-form video.

  POST   /build   → bridge a video plan (asset bytes inline, no local paths)
                    into a project zip, ready for /create
  POST   /create  → submit job, returns { jobId, status: "pending" } immediately
  GET    /status  → { jobId, status, ... }  — poll until "complete" or "failed"
  GET    /result  → raw MP4 binary           — only when status == "complete"
  DELETE /delete  → removes the job record and its rendered file

Endpoint functions are named `build` / `create` / `status` / `result` /
`delete` on purpose: Modal derives the web URL from the function name, and
each non-default environment's profile prefixes the URL with its own name.
So `create` deployed to `dev` resolves to
https://<profile>-dev--<app-name>-create.modal.run.

No client/tenant concept lives here: theme, audio, icons, and icon SFX are
either supplied explicitly in the request body or simply omitted (the
project renders without them). See ../builder/video_theme.py for a plain
neutral default theme, and ../README.md for the end-to-end flow.

Every endpoint below requires `Authorization: Bearer <token>` (see
AUTH_SECRET_NAME) -- Modal web endpoints are public URLs by default, so
without this any caller with the link could run renders on your compute or
read/delete job records.
"""

import os

import modal
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Not `from fastapi import status` -- one of our own endpoint functions below
# is itself named `status`, which would shadow the fastapi module's `status`
# at module scope and break this exact check with an AttributeError.
_HTTP_401_UNAUTHORIZED = 401

# Change this if you want a different Modal app name. Whatever you pick, it's
# yours -- there's no other service in this repo to collide with.
app = modal.App("hyperframes-video")

# Every HTTP endpoint below requires `Authorization: Bearer <token>` matching
# this Modal Secret's AUTH_TOKEN value (same convention as this account's other
# services, e.g. render-auth-token). Modal endpoints are public URLs by
# default -- anyone with the link can call them, run renders on your compute,
# or read/delete job records -- so every endpoint pulls this secret in and
# checks it before doing anything else.
#   modal secret create hyperframes-video-auth-token AUTH_TOKEN=<a random string> -e dev
AUTH_SECRET_NAME = "hyperframes-video-auth-token"
auth_scheme = HTTPBearer()


def _require_auth(token: HTTPAuthorizationCredentials) -> None:
    if token.credentials != os.environ["AUTH_TOKEN"]:
        raise HTTPException(
            status_code=_HTTP_401_UNAUTHORIZED,
            detail="Incorrect bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Persistent job state: jobId → { status, outputName, renderMs, sizeMb, error, submittedAt }.
# A modal.Dict is the cross-invocation store: the `create` endpoint, the spawned
# render function, and the `status`/`result`/`delete` endpoints each run in their
# own container, so job state has to live somewhere shared rather than in memory.
job_store = modal.Dict.from_name("hyperframes-video-jobs", create_if_missing=True)

# Persistent volume — rendered MP4s live here (keyed by jobId) until deleted.
video_volume = modal.Volume.from_name("hyperframes-video-outputs", create_if_missing=True)

# Pin matches this repo's own template contract -- bump deliberately, not via @latest.
HYPERFRAMES_VERSION = "0.7.48"

# Chromium install choice: `apt-get install -y chromium` for the shared libs/fonts
# it drags in as apt deps, but the actual render engine does NOT use
# PUPPETEER_EXECUTABLE_PATH — HyperFrames pins its own `chrome-headless-shell`
# build (via @puppeteer/browsers) for reproducible pixel output, resolved
# through the PRODUCER_HEADLESS_SHELL_PATH env var instead. Without it, a render
# tries to download chrome-headless-shell on demand and fails on extraction if
# `unzip` isn't present. Fix: install `unzip`, pre-install chrome-headless-shell at
# build time (baked into the image, no runtime download), and resolve its path into
# a file at build time since the exact path includes a version dir that can't be
# hardcoded ahead of the "stable" tag resolving.
image = (
    modal.Image.debian_slim()
    .apt_install("curl", "unzip", "ffmpeg", "chromium")
    .run_commands(
        # Node.js 22 via nodesource. hyperframes@0.7.48 declares an engines
        # requirement of node >=22 (as do its puppeteer-core/@puppeteer/browsers
        # deps).
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        "apt-get install -y nodejs",
    )
    .run_commands(
        "npx --yes @puppeteer/browsers install chrome-headless-shell@stable --path /root/.cache/puppeteer",
        # Bake the resolved binary path into a file at build time -- read at
        # render time since Modal calls `hyperframes render` from Python
        # (render_job), not via an entrypoint script.
        "find /root/.cache/puppeteer -name 'chrome-headless-shell' -type f | head -1 > /root/.cache/headless-shell-path.txt",
    )
    .env(
        {
            "PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium",
            "PUPPETEER_SKIP_CHROMIUM_DOWNLOAD": "true",
        }
    )
    .pip_install("fastapi>=0.110.0")
    # Warm the npx cache at build time so the first render doesn't pay the
    # download cost on top of Modal's cold start.
    .run_commands(f"npx --yes hyperframes@{HYPERFRAMES_VERSION} --version || true")
)

# Repo root, computed from this file's own location rather than assumed cwd --
# `modal deploy` is invoked from this repo's root or from `service/`, so a
# relative path here would resolve wrong from the wrong cwd.
# .../hyperframes-video-service/service/app.py -> repo root is two dirname()s up.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Image for the `build` endpoint only -- it needs the builder package and the
# whole templates/ directory; none of these are part of `image` above, which
# only carries the render toolchain (Node/Chromium/hyperframes CLI), no repo
# Python source or templates.
# `add_local_*` calls must be the LAST thing chained onto an image (Modal
# raises InvalidError if a build step is added afterward with copy=False, the
# default). copy=False also means these files are attached at container
# startup rather than baked into an image layer, so editing the builder
# package or a template doesn't force an image rebuild.
build_image = (
    image
    .add_local_dir(
        os.path.join(_REPO_ROOT, "builder"),
        remote_path="/root/builder",
    )
    .add_local_dir(
        os.path.join(_REPO_ROOT, "templates"),
        remote_path="/root/templates",
    )
)


# ── Background render function ────────────────────────────────────────────────

@app.function(
    image=image,
    timeout=600,
    memory=4096,
    volumes={"/renders": video_volume},
)
def render_job(job_id: str, project_zip_b64: str, output_name: str):
    """
    Spawned by `create`; not an HTTP endpoint.

    Runs the actual HyperFrames render, which is long (tens of seconds to
    minutes) — far past the ~5-minute hard timeout Modal enforces on anything
    reachable by URL. Keeping it a spawned background function (rather than
    inline in the `create` endpoint) is what lets `create` return immediately.

    Steps: decode the project zip → unzip into a per-job working dir → run
    `npx hyperframes render` there → move the MP4 into the volume keyed by jobId.
    """
    import base64, os, shutil, subprocess, time, zipfile

    work_dir = f"/tmp/render-{job_id}"
    job_store[job_id] = {"status": "running", "outputName": output_name}
    print(f"[hyperframes] Start job={job_id} output={output_name}")

    try:
        os.makedirs(work_dir, exist_ok=True)
        zip_path = f"{work_dir}.zip"
        with open(zip_path, "wb") as f:
            f.write(base64.b64decode(project_zip_b64))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(work_dir)
        os.unlink(zip_path)

        # A zip may contain the project files at its root, or nested one level
        # inside a single top-level directory (the common `zip -r foo.zip foo/`
        # shape). Detect a HyperFrames project by its `hyperframes.json` marker
        # and treat that directory as the render root.
        project_dir = _find_project_root(work_dir)
        if project_dir is None:
            job_store[job_id] = {
                "status": "failed",
                "outputName": output_name,
                "error": "No hyperframes.json found in the submitted zip — not a HyperFrames project.",
            }
            return

        with open("/root/.cache/headless-shell-path.txt") as f:
            headless_shell_path = f.read().strip()
        render_env = {**os.environ, "PRODUCER_HEADLESS_SHELL_PATH": headless_shell_path}

        t0 = time.time()
        result = subprocess.run(
            ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render", "--output", output_name],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=540,
            env=render_env,
        )
        render_ms = int((time.time() - t0) * 1000)

        if result.returncode != 0:
            diag = (result.stderr or "")[-1500:] or (result.stdout or "")[-1500:]
            print(f"[hyperframes] Failed job={job_id}\n{diag}")
            job_store[job_id] = {
                "status": "failed",
                "outputName": output_name,
                "error": diag[-600:],
            }
            return

        output_path = os.path.join(project_dir, output_name)
        if not os.path.isfile(output_path):
            job_store[job_id] = {
                "status": "failed",
                "outputName": output_name,
                "error": f"Render reported success but {output_name!r} was not found in the project dir.",
            }
            return

        with open(output_path, "rb") as f_in:
            video_bytes = f_in.read()
        size_mb = round(len(video_bytes) / 1_048_576, 2)
        print(f"[hyperframes] Done job={job_id} in {render_ms}ms — {size_mb} MB")

        with open(f"/renders/{job_id}.mp4", "wb") as f_out:
            f_out.write(video_bytes)
        video_volume.commit()

        job_store[job_id] = {
            "status": "complete",
            "outputName": output_name,
            "renderMs": render_ms,
            "sizeMb": size_mb,
        }

    except subprocess.TimeoutExpired:
        print(f"[hyperframes] Timeout job={job_id}")
        job_store[job_id] = {
            "status": "failed",
            "outputName": output_name,
            "error": "Render exceeded the 540s time budget.",
        }
    except Exception as e:
        print(f"[hyperframes] Exception job={job_id}: {e}")
        job_store[job_id] = {"status": "failed", "outputName": output_name, "error": str(e)}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _find_project_root(base_dir: str):
    """
    Return the directory containing `hyperframes.json`, or None.

    Handles both a flat zip (files at the root) and a zip that wraps everything
    in one top-level folder. Checks the base dir first, then one level down.
    """
    import os

    if os.path.isfile(os.path.join(base_dir, "hyperframes.json")):
        return base_dir
    for entry in os.listdir(base_dir):
        candidate = os.path.join(base_dir, entry)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "hyperframes.json")):
            return candidate
    return None


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@app.function(
    image=build_image,
    timeout=30,
    scaledown_window=300,
    secrets=[modal.Secret.from_name(AUTH_SECRET_NAME)],
)
@modal.fastapi_endpoint(method="POST")
def build(item: dict, token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Bridge a "video plan" (asset bytes inline, never a local path) into a
    project zip that `create` above accepts unchanged.

    Body:
      {
        "plan": {
          "project_id": "some-slug",
          "frames": [
            {
              "id": "s01",
              "template": "body-stroke-hook",
              "tokens": {"...": "..."},
              "items": [{"...": "..."}],
              "asset_base64": "<base64 raw file bytes>",   # only on asset-* templates
              "asset_filename": "<real name incl. extension>",  # only on asset-* templates
              "transition": "cut"
            }
          ],
          "audio": {...},          # optional, see builder/hyperframes_project_builder.py
          "icon_library": [...],   # optional
          "icon_sfx": {...}        # optional
        },
        "theme": {"bg": "#...", "text": "#...", "lead_text": "#...", "accent": "#...",
                   "accent_text": "#...", "font_family": "...", "logo_url": "..."}
      }

    Every `plan` field matches `builder/hyperframes_project_builder.py`'s
    `build_project()` video-plan schema exactly except: asset-template frames
    carry `asset_base64`/`asset_filename` here instead of `asset_path`,
    because a caller (e.g. an LLM's structured output) only ever knows a
    remote file id + filename, never a local path. This endpoint decodes
    each frame's `asset_base64` to a real temp file, swaps in the resulting
    `asset_path`, then calls `build_project()` + `zip_project()`.

    `theme` is OPTIONAL — omit it entirely to render with
    `builder/video_theme.py`'s neutral `DEFAULT_THEME`. `plan["audio"]`,
    `plan["icon_library"]`, and `plan["icon_sfx"]` are all OPTIONAL and never
    auto-populated with anything — omit them for a silent, icon-free video.

    Returns: { "projectZipBase64": "<base64 of the built project zip>" } --
    same field name `create`'s body expects, so the response here can be
    piped straight into a `create` call unchanged.

    400s (mirroring `create`'s HTTPException style) on a missing/malformed
    `plan`, a missing/empty `frames` list, a frame claiming `asset_base64`
    without a usable `asset_filename`, invalid base64, or any `ValueError`
    `build_project()` raises for bad frame data (unknown template, missing
    required tokens, duplicate frame ids, etc.).
    """
    import base64
    import shutil
    import sys
    import uuid

    _require_auth(token)

    # /root is where build_image's add_local_dir mounts `builder/` and
    # `templates/` (see build_image above) -- needed for the `import builder...`
    # below and for builder.hyperframes_project_builder's own
    # TEMPLATES_DIR resolution (dirname(dirname(__file__)) + "templates").
    sys.path.insert(0, "/root")
    import builder.hyperframes_project_builder as hfb

    plan = item.get("plan")
    if not isinstance(plan, dict):
        raise HTTPException(status_code=400, detail="Missing required field: plan (object)")

    frames = plan.get("frames")
    if not isinstance(frames, list) or not frames:
        raise HTTPException(status_code=400, detail="plan.frames must be a non-empty list")

    work_id = str(uuid.uuid4())
    work_dir = f"/tmp/build-{work_id}"
    project_dir = os.path.join(work_dir, "project")
    assets_dir = os.path.join(work_dir, "assets-in")
    zip_path = f"{work_dir}.zip"

    try:
        os.makedirs(assets_dir, exist_ok=True)

        # Materialize each asset-* frame's inline bytes as a real local file --
        # build_project() needs a real "asset_path" on disk to copy into the
        # project's assets/ dir. This is the only bridging step; every other
        # field is passed through untouched.
        resolved_frames = []
        for i, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise HTTPException(status_code=400, detail=f"Frame {i}: must be an object")
            frame = dict(frame)
            asset_b64 = frame.pop("asset_base64", None)
            asset_filename = frame.pop("asset_filename", None)

            if asset_b64 is not None:
                if not asset_filename or not isinstance(asset_filename, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Frame {i}: asset_base64 present but asset_filename missing/invalid",
                    )
                safe_name = os.path.basename(asset_filename)
                if not safe_name or safe_name in (".", ".."):
                    raise HTTPException(status_code=400, detail=f"Frame {i}: invalid asset_filename")
                try:
                    raw_bytes = base64.b64decode(asset_b64, validate=True)
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Frame {i}: invalid asset_base64: {e}")

                dest_path = os.path.join(assets_dir, f"{i:03d}-{safe_name}")
                with open(dest_path, "wb") as f:
                    f.write(raw_bytes)
                frame["asset_path"] = dest_path

            resolved_frames.append(frame)

        resolved_plan = dict(plan)
        resolved_plan["frames"] = resolved_frames

        theme = item.get("theme")
        hfb.build_project(resolved_plan, project_dir, theme=theme)
        hfb.zip_project(project_dir, zip_path)

        with open(zip_path, "rb") as f:
            zip_b64 = base64.b64encode(f.read()).decode("ascii")

        print(
            f"[hyperframes] Built project id={resolved_plan.get('project_id')!r} "
            f"frames={len(resolved_frames)} "
            f"audio={bool(resolved_plan.get('audio'))} "
            f"icons={bool(resolved_plan.get('icon_library'))}"
        )
        return {"projectZipBase64": zip_b64}

    except ValueError as e:
        # build_project()'s own validation errors -- bad template name, missing
        # required tokens, duplicate frame ids, etc.
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            os.unlink(zip_path)
        except FileNotFoundError:
            pass


@app.function(
    image=image,
    timeout=30,
    scaledown_window=300,
    secrets=[modal.Secret.from_name(AUTH_SECRET_NAME)],
)
@modal.fastapi_endpoint(method="POST")
def create(item: dict, token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Submit a render job. Returns immediately with a jobId; the render runs in a
    spawned background function (see render_job) because it far outlasts the HTTP
    request timeout.

    Body:
      {
        "projectZipBase64": "<base64 of a zip of an entire HyperFrames project dir>",
        "outputName": "some-name.mp4"   # optional, defaults to "output.mp4"
      }

    A HyperFrames project is a self-contained directory (index.html,
    compositions/, assets/, meta.json, hyperframes.json, ...). Zip that whole
    directory, base64-encode the zip bytes, and send the string as
    `projectZipBase64`. The zip may have the files at its root or nested inside a
    single top-level folder — both are accepted.

    Returns: { "jobId": str, "status": "pending" }
    """
    import time, uuid

    from fastapi import HTTPException

    _require_auth(token)

    project_zip_b64 = item.get("projectZipBase64")
    if not project_zip_b64 or not isinstance(project_zip_b64, str):
        raise HTTPException(status_code=400, detail="Missing required field: projectZipBase64 (base64-encoded project zip)")

    output_name = item.get("outputName") or "output.mp4"
    if not isinstance(output_name, str) or not output_name.endswith(".mp4"):
        raise HTTPException(status_code=400, detail="outputName must be a string ending in .mp4")
    # Guard against path traversal — the render writes this name inside the
    # container working dir, so it must stay a bare filename.
    if "/" in output_name or "\\" in output_name or output_name.startswith(".."):
        raise HTTPException(status_code=400, detail="outputName must be a bare filename, not a path")

    job_id = str(uuid.uuid4())
    job_store[job_id] = {"status": "pending", "outputName": output_name, "submittedAt": time.time()}
    render_job.spawn(job_id, project_zip_b64, output_name)
    print(f"[hyperframes] Spawned job={job_id} output={output_name}")

    return {"jobId": job_id, "status": "pending"}


@app.function(
    image=image,
    timeout=30,
    scaledown_window=300,
    secrets=[modal.Secret.from_name(AUTH_SECRET_NAME)],
)
@modal.fastapi_endpoint(method="GET")
def status(job_id: str, token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Poll job status.

    Query:   ?job_id=<uuid>
    Returns: { jobId, status, outputName, renderMs?, sizeMb?, error? }
             status is one of: pending | running | complete | failed
    """
    from fastapi import HTTPException

    _require_auth(token)

    try:
        info = dict(job_store[job_id])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"jobId": job_id, **info}


@app.function(
    image=image,
    timeout=60,
    volumes={"/renders": video_volume},
    scaledown_window=300,
    secrets=[modal.Secret.from_name(AUTH_SECRET_NAME)],
)
@modal.fastapi_endpoint(method="GET")
def result(job_id: str, token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Download the rendered MP4.

    Query:   ?job_id=<uuid>
    Returns: video/mp4 binary when complete — 202 + status JSON while still
             pending/running, 404 if unknown, 500 if the file went missing.
    """
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse, Response

    _require_auth(token)

    try:
        info = dict(job_store[job_id])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if info.get("status") != "complete":
        # Not an error — the caller polls this until the render finishes.
        return JSONResponse(status_code=202, content={"jobId": job_id, **info})

    video_volume.reload()
    video_path = f"/renders/{job_id}.mp4"
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Video file missing from storage")

    raw_name = str(info.get("outputName", f"{job_id}.mp4"))
    safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".") else "-" for c in raw_name)[:100] or f"{job_id}.mp4"

    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.function(
    image=image,
    timeout=30,
    volumes={"/renders": video_volume},
    scaledown_window=300,
    secrets=[modal.Secret.from_name(AUTH_SECRET_NAME)],
)
@modal.fastapi_endpoint(method="DELETE")
def delete(job_id: str, token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Delete a rendered video and its job record to free storage. Safe to call on
    a failed or still-pending job (there's just no file to remove in that case).

    Query:   ?job_id=<uuid>
    Returns: { jobId, deleted: true }
    """
    import os

    from fastapi import HTTPException

    _require_auth(token)

    try:
        info = dict(job_store[job_id])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if info.get("status") == "complete":
        video_volume.reload()
        try:
            os.unlink(f"/renders/{job_id}.mp4")
            video_volume.commit()
        except FileNotFoundError:
            pass

    del job_store[job_id]
    print(f"[hyperframes] Deleted job={job_id}")

    return {"jobId": job_id, "deleted": True}
