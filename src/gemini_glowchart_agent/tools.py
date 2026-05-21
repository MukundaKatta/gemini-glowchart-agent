"""The five agent tools, mirroring the Perfect Corp YouCam API:

  upload_image, analyze_skin, analyze_skin_tone, apply_makeup,
  apply_hair_color

Stub mode (GLOWCHART_STUB=1, the default) returns hand-written fixtures
from `stubs.py` whose shapes match the real Perfect Corp API responses.
Real mode (GLOWCHART_STUB=0) calls the production API at
`https://yce-api-01.makeupar.com` with `Authorization: Bearer
${PERFECT_CORP_API_KEY}`. The four analysis / try-on endpoints are async
(POST returns task_id, then poll GET until task_status == "success").

The five functions are plain callables so unit tests bypass ADK.
`build_tools()` wraps them with ADK `FunctionTool` for the agent.
"""

from __future__ import annotations

import os
import time
from typing import Any

from gemini_glowchart_agent import stubs


# Perfect Corp YouCam API host. Override with GLOWCHART_API_HOST if the
# tenant lives in a different region.
DEFAULT_API_HOST = "https://yce-api-01.makeupar.com"

# Async poll defaults. Skin analysis takes 3-8s in practice; cap the
# poll loop at 60s so a stalled task does not hang the agent forever.
_POLL_INTERVAL_SECS = 1.0
_POLL_TIMEOUT_SECS = 60.0


def _is_stub() -> bool:
    return os.environ.get("GLOWCHART_STUB", "1") == "1"


def _api_host() -> str:
    return os.environ.get("GLOWCHART_API_HOST", DEFAULT_API_HOST)


def _api_headers() -> dict[str, str]:
    key = os.environ["PERFECT_CORP_API_KEY"]
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }


def _poll_task(task: str, task_id: str) -> dict[str, Any]:
    """Poll GET /s2s/v2.0/task/{task}/{task_id} until task_status is
    `success` or `failed`. Raises RuntimeError on timeout/failure."""
    import requests  # noqa: E402

    url = f"{_api_host()}/s2s/v2.0/task/{task}/{task_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT_SECS
    while time.monotonic() < deadline:
        r = requests.get(url, headers=_api_headers(), timeout=10)
        r.raise_for_status()
        body = r.json()
        status = body.get("task_status", "")
        if status == "success":
            return body
        if status == "failed":
            raise RuntimeError(f"task {task}/{task_id} failed: {body}")
        time.sleep(_POLL_INTERVAL_SECS)
    raise RuntimeError(f"task {task}/{task_id} timed out after {_POLL_TIMEOUT_SECS}s")


def _start_and_poll(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    import requests  # noqa: E402

    url = f"{_api_host()}/s2s/v2.0/task/{task}"
    r = requests.post(url, json=payload, headers=_api_headers(), timeout=10)
    r.raise_for_status()
    task_id = r.json().get("result", {}).get("task_id") or r.json().get("task_id", "")
    if not task_id:
        raise RuntimeError(f"task {task} did not return a task_id: {r.json()}")
    return _poll_task(task, task_id)


# ---------------------------------------------------------------------------
# Tool 1: upload_image
# ---------------------------------------------------------------------------


def upload_image(image_b64: str) -> dict[str, Any]:
    """Upload a base64-encoded selfie to Perfect Corp's file store.

    Returns: {"file_id": str, "expires_at": str}.
    """
    if _is_stub():
        env = stubs.stub_upload_image(image_b64)
    else:
        import requests  # noqa: E402

        url = f"{_api_host()}/s2s/v1.0/file/upload-image"
        r = requests.post(
            url,
            json={"image": image_b64},
            headers=_api_headers(),
            timeout=20,
        )
        r.raise_for_status()
        env = r.json()
    result = env.get("result", {})
    return {
        "file_id":    str(result.get("file_id", "")),
        "expires_at": str(result.get("expires_at", "")),
    }


# ---------------------------------------------------------------------------
# Tool 2: analyze_skin
# ---------------------------------------------------------------------------


def analyze_skin(file_id: str, mode: str = "SD") -> dict[str, Any]:
    """Run Perfect Corp Skin Analysis (SD = 15 attributes; HD = 30).

    Returns:
      {
        "attributes":    [{"name", "score", "severity"}, ...],
        "overall_score": int,
        "ai_skin_age":   int,
        "mask_urls":     {"pore": "...", ...},
      }
    """
    mode = (mode or "SD").upper()
    if mode not in ("SD", "HD"):
        mode = "SD"
    if _is_stub():
        env = stubs.stub_analyze_skin(file_id, mode=mode)
    else:
        env = _start_and_poll("skin-analysis", {"file_id": file_id, "mode": mode})
    result = env.get("result", {})
    return {
        "attributes":    [dict(a) for a in (result.get("attributes") or [])],
        "overall_score": int(result.get("overall_score") or 0),
        "ai_skin_age":   int(result.get("ai_skin_age") or 0),
        "mask_urls":     dict(result.get("mask_urls") or {}),
    }


# ---------------------------------------------------------------------------
# Tool 3: analyze_skin_tone
# ---------------------------------------------------------------------------


def analyze_skin_tone(file_id: str) -> dict[str, Any]:
    """Run Perfect Corp Skin Tone analysis.

    Returns:
      {
        "undertone":        "warm"|"cool"|"neutral",
        "season":           str,
        "palette":          [hex, ...],
        "foundation_shade": str,
      }
    """
    if _is_stub():
        env = stubs.stub_analyze_skin_tone(file_id)
    else:
        env = _start_and_poll("skin-tone", {"file_id": file_id})
    result = env.get("result", {})
    return {
        "undertone":        str(result.get("undertone", "")),
        "season":           str(result.get("season", "")),
        "palette":          list(result.get("palette") or []),
        "foundation_shade": str(result.get("foundation_shade", "")),
    }


# ---------------------------------------------------------------------------
# Tool 4: apply_makeup
# ---------------------------------------------------------------------------


def apply_makeup(file_id: str, look: dict[str, Any]) -> dict[str, Any]:
    """Trigger the makeup virtual try-on with a {lipstick, eyeshadow,
    blush} hex map. Returns: {"result_url": str, "units_charged": int}.
    """
    look = dict(look or {})
    if _is_stub():
        env = stubs.stub_apply_makeup(file_id, look)
    else:
        env = _start_and_poll(
            "makeup",
            {"file_id": file_id, "look": look},
        )
    result = env.get("result", {})
    return {
        "result_url":    str(result.get("result_url", "")),
        "units_charged": int(result.get("units_charged") or 0),
    }


# ---------------------------------------------------------------------------
# Tool 5: apply_hair_color
# ---------------------------------------------------------------------------


def apply_hair_color(file_id: str, color_hex: str) -> dict[str, Any]:
    """Trigger the hair-color virtual try-on. Returns:
    {"result_url": str, "units_charged": int}."""
    color_hex = str(color_hex or "")
    if _is_stub():
        env = stubs.stub_apply_hair_color(file_id, color_hex)
    else:
        env = _start_and_poll(
            "hair-color",
            {"file_id": file_id, "color_hex": color_hex},
        )
    result = env.get("result", {})
    return {
        "result_url":    str(result.get("result_url", "")),
        "units_charged": int(result.get("units_charged") or 0),
    }


# ---------------------------------------------------------------------------
# ADK FunctionTool wrappers
# ---------------------------------------------------------------------------


def build_tools() -> list[Any]:
    """Wrap the five functions as ADK FunctionTools."""
    from google.adk.tools import FunctionTool  # noqa: E402

    return [
        FunctionTool(func=upload_image),
        FunctionTool(func=analyze_skin),
        FunctionTool(func=analyze_skin_tone),
        FunctionTool(func=apply_makeup),
        FunctionTool(func=apply_hair_color),
    ]
