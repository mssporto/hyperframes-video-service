#!/usr/bin/env python3
"""End-to-end reference: brief -> LLM video plan -> render -> MP4 on disk.

This is what an n8n workflow should mirror (as HTTP Request / Code nodes) or
simply shell out to. It deliberately does the LLM call and the local
project build OUTSIDE Modal -- your LLM API key never has to live in the
Modal image, and you can swap providers/models without touching the
deployed service at all. Only the finished project (as a base64 zip) and
the render job itself go to Modal.

Usage:
    export OPENROUTER_API_KEY=...
    export HYPERFRAMES_SERVICE_URL=https://you--hyperframes-video-create.modal.run
    # (status/result/delete are the same base URL with -status/-result/-delete)
    python examples/generate_short.py --topic "why most onboarding emails get ignored"

Requires: pip install httpx
"""

import argparse
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from builder.hyperframes_project_builder import build_project, zip_project
from builder.video_theme import DEFAULT_THEME
from builder.video_writer import generate_video


def _service_url(function_name):
    """Derive a sibling endpoint URL from HYPERFRAMES_SERVICE_URL, which you
    should set to the `create` endpoint's URL (they all share everything but
    the trailing function name), e.g.
    https://you--hyperframes-video-create.modal.run ->
    https://you--hyperframes-video-status.modal.run
    """
    base = os.environ["HYPERFRAMES_SERVICE_URL"]
    return base.replace("-create.modal.run", f"-{function_name}.modal.run")


def main():
    ap = argparse.ArgumentParser(description="Generate a YouTube Short end to end.")
    ap.add_argument("--topic", required=True, help="What the short should be about.")
    ap.add_argument("--display-name", default="the show", help="Whose voice the writer speaks in.")
    ap.add_argument("--cta", default="", help="Closing CTA text (e.g. your handle/domain).")
    ap.add_argument("--output", default="short.mp4", help="Local filename for the finished MP4.")
    ap.add_argument("--model", default="openai/gpt-4o-mini", help="OpenRouter/fal model id.")
    ap.add_argument("--provider", default="openrouter", choices=["openrouter", "fal"])
    args = ap.parse_args()

    api_key = os.environ.get(f"{args.provider.upper()}_API_KEY")
    if not api_key:
        sys.exit(f"Set {args.provider.upper()}_API_KEY")

    print("Writing video plan...")
    plan = generate_video(
        brief={"topic": args.topic},
        display_name=args.display_name,
        api_key=api_key,
        model=args.model,
        provider=args.provider,
        cta_text=args.cta,
    )
    print(f"  -> {plan['projectId']}, {len(plan['frames'])} frames")

    print("Building HyperFrames project...")
    project_dir = f"/tmp/{plan['projectId']}"
    zip_path = f"{project_dir}.zip"
    build_project({"project_id": plan["projectId"], "frames": plan["frames"]}, project_dir, theme=DEFAULT_THEME)
    zip_project(project_dir, zip_path)
    with open(zip_path, "rb") as f:
        zip_b64 = base64.b64encode(f.read()).decode("ascii")

    print("Submitting render job...")
    resp = httpx.post(
        _service_url("create"),
        json={"projectZipBase64": zip_b64, "outputName": os.path.basename(args.output)},
        timeout=30.0,
    )
    resp.raise_for_status()
    job_id = resp.json()["jobId"]
    print(f"  -> job {job_id}")

    print("Waiting for render...")
    while True:
        resp = httpx.get(_service_url("status"), params={"job_id": job_id}, timeout=30.0)
        resp.raise_for_status()
        info = resp.json()
        if info["status"] == "complete":
            break
        if info["status"] == "failed":
            sys.exit(f"Render failed: {info.get('error')}")
        time.sleep(5)

    print("Downloading MP4...")
    resp = httpx.get(_service_url("result"), params={"job_id": job_id}, timeout=60.0)
    resp.raise_for_status()
    with open(args.output, "wb") as f:
        f.write(resp.content)
    print(f"Done -> {args.output} ({info['sizeMb']} MB, {info['renderMs']}ms)")

    httpx.delete(_service_url("delete"), params={"job_id": job_id}, timeout=30.0)


if __name__ == "__main__":
    main()
