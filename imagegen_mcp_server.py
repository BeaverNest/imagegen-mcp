#!/usr/bin/env python
"""MCP server for free image generation via Pollinations.

Keyless free text-to-image API (https://image.pollinations.ai, Flux).
No API key required. Community service, no SLA - fine for casual use.

Pitfall: the endpoint blocks default HTTP client user-agents (403);
requests MUST send a real browser User-Agent header.
"""
from __future__ import annotations

import os
import pwd
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

POLLINATIONS_BASE = "https://image.pollinations.ai"
ALLOWED_ASPECT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _default_output_dir() -> str:
    configured = os.environ.get("IMAGE_MCP_OUTPUT_DIR", "").strip()
    if configured:
        return configured
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except Exception:  # noqa: BLE001 - fallback
        home = os.path.expanduser("~")
    return os.path.join(home, "gemini-image-mcp", "output")


OUTPUT_DIR = _default_output_dir()

mcp = FastMCP(
    "imagegen",
    instructions=(
        "Image generation via Pollinations (free, keyless, Flux model). "
        "generate_image returns a local image path. No API key needed."
    ),
)


def _aspect_to_size(aspect_ratio: str) -> tuple[int, int]:
    return {
        "1:1": (1024, 1024),
        "3:4": (768, 1024),
        "4:3": (1024, 768),
        "9:16": (576, 1024),
        "16:9": (1024, 576),
    }[aspect_ratio]


def _save_image(raw: bytes, mime_type: str, target_dir: str) -> str:
    ext = (mime_type.split("/")[-1] or "png").lower()
    if ext not in {"png", "jpeg", "jpg", "webp"}:
        ext = "png"
    fname = (
        "img_" + time.strftime("%Y%m%d_%H%M%S")
        + f"_{int(time.time() * 1000) % 100000:05d}." + ext
    )
    path = os.path.join(target_dir, fname)
    with open(path, "wb") as fh:
        fh.write(raw)
    return path


@mcp.tool()
def health() -> dict[str, Any]:
    """Check image MCP readiness (output dir writable)."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        writable = os.access(OUTPUT_DIR, os.W_OK)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"output dir check failed: {exc}"}
    return {
        "ok": writable,
        "provider": "pollinations",
        "key_required": False,
        "output_dir": OUTPUT_DIR,
        "writable": writable,
    }


@mcp.tool()
def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    output_dir: str = "",
) -> dict[str, Any]:
    """Generate an image from a text prompt (free, no API key).

    Args:
        prompt: Text description of the image to generate (required).
        aspect_ratio: One of 1:1, 3:4, 4:3, 9:16, 16:9 (default 1:1).
        output_dir: Optional directory to save the image into. Defaults to
            ~/gemini-image-mcp/output.

    Returns:
        {ok, path, provider, ...} on success, or {ok: false, error}.
    """
    if not prompt or not prompt.strip():
        return {"ok": False, "error": "prompt is required and must not be empty"}
    if len(prompt) > 2000:
        return {"ok": False, "error": "prompt too long (max 2000 chars)"}
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        return {"ok": False, "error": f"aspect_ratio must be one of {sorted(ALLOWED_ASPECT_RATIOS)}"}

    target_dir = output_dir.strip() or OUTPUT_DIR
    try:
        os.makedirs(target_dir, exist_ok=True)
        if not os.access(target_dir, os.W_OK):
            return {"ok": False, "error": f"output dir not writable: {target_dir}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"cannot create output dir: {exc}"}

    width, height = _aspect_to_size(aspect_ratio)
    quoted = urllib.parse.quote(prompt.strip())
    url = f"{POLLINATIONS_BASE}/prompt/{quoted}?width={width}&height={height}&nologo=true"
    req = urllib.request.Request(
        url,
        headers={"Accept": "image/*", "User-Agent": BROWSER_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
            if not mime.startswith("image/"):
                return {"ok": False, "error": f"unexpected content-type {mime}", "url": url}
            path = _save_image(raw, mime, target_dir)
            return {
                "ok": True,
                "path": path,
                "mime_type": mime,
                "size_bytes": len(raw),
                "aspect_ratio": aspect_ratio,
                "provider": "pollinations",
                "message": f"image saved to {path}",
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"pollinations HTTP {exc.code}", "url": url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"pollinations {type(exc).__name__}: {exc}", "url": url}


if __name__ == "__main__":
    mcp.run()
