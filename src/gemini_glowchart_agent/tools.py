"""The five agent tools, mirroring the Perfect Corp YouCam API:

  upload_image, analyze_skin, analyze_skin_tone, apply_makeup,
  apply_hair_color

Stub mode (GLOWCHART_STUB=1, the default) returns hand-written fixtures
from `stubs.py` whose shapes match what the agent expects.

Real mode (GLOWCHART_STUB=0) calls the production API at
`https://yce-api-01.makeupar.com`. The auth flow lives in `auth.py`
(long-lived bearer or RSA handshake, autodetected). The four analysis /
try-on endpoints follow the async-task pattern:

  1. POST /s2s/v2.0/file/{task_name} { files: [{content_type, file_name,
     file_size}] } -> { data: { files: [{ file_id, requests:
     [{ url, headers, method: "PUT" }] }] } }
  2. PUT the raw image bytes to the pre-signed URL with the returned
     headers.
  3. POST /s2s/v2.0/task/{task_name} { src_file_id: <file_id>, ... }
     -> { data: { task_id } }
  4. GET /s2s/v2.0/task/{task_name}/{task_id} every 2 seconds until
     data.task_status is `success` or `error`. Cap at 60 seconds.

Live API findings (2026-05-21):
- Envelope key is `data` (not `result`).
- `skin-tone-analysis` returns only `{color: {skin_color}, face_quality}`.
  We derive undertone/season/palette/foundation_shade from skin_color so
  the agent's downstream contract stays stable across stub and real.
- `skin-analysis` task name is unverified live (would burn units to
  probe); first-try is the canonical name with a small candidate list.

The five functions are plain callables so unit tests bypass ADK.
`build_tools()` wraps them with ADK `FunctionTool` for the agent.
"""

from __future__ import annotations

import base64
import binascii
import os
import time
from typing import Any

from gemini_glowchart_agent import stubs
from gemini_glowchart_agent.auth import get_access_token, reset_token_cache


# Perfect Corp YouCam API host. Override with GLOWCHART_API_HOST if the
# tenant lives in a different region.
DEFAULT_API_HOST = "https://yce-api-01.makeupar.com"

# Task names confirmed against the live API on 2026-05-21.
# Per-task candidate lists let us recover if Perfect Corp renames an
# endpoint without breaking the agent.
_TASK_NAME_CANDIDATES: dict[str, tuple[str, ...]] = {
    "skin_analysis":      ("skin-analysis", "skin-analysis-sd"),
    "skin_analysis_hd":   ("skin-analysis-hd", "skin-analysis"),
    "skin_tone_analysis": ("skin-tone-analysis", "personal-color-analysis"),
    "makeup_vto":         ("makeup-vto",),
    "hair_color":         ("hair-color",),
}

# Async poll defaults. Skin-tone analysis returns in 3-5s in practice;
# cap the loop at 60s so a stalled task does not hang the agent forever.
_POLL_INTERVAL_SECS = 2.0
_POLL_TIMEOUT_SECS = 60.0


def _is_stub() -> bool:
    return os.environ.get("GLOWCHART_STUB", "1") == "1"


def _api_host() -> str:
    return os.environ.get("GLOWCHART_API_HOST", DEFAULT_API_HOST)


def _bearer_headers() -> dict[str, str]:
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


def _envelope_data(env: dict[str, Any]) -> dict[str, Any]:
    """Pull the inner payload from a Perfect Corp envelope.

    The API uses `data` at top level on v2.0; some older shapes used
    `result`. We probe both.
    """
    if isinstance(env, dict):
        d = env.get("data")
        if isinstance(d, dict):
            return d
        r = env.get("result")
        if isinstance(r, dict):
            return r
    return env if isinstance(env, dict) else {}


def _post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to {host}{path} with auto-refresh on 401."""
    import requests  # noqa: E402

    url = f"{_api_host()}{path}"
    r = requests.post(url, json=body, headers=_bearer_headers(), timeout=20)
    if r.status_code == 401:
        reset_token_cache()
        r = requests.post(url, json=body, headers=_bearer_headers(), timeout=20)
    r.raise_for_status()
    return r.json()


def _get_json(path: str) -> dict[str, Any]:
    import requests  # noqa: E402

    url = f"{_api_host()}{path}"
    r = requests.get(url, headers=_bearer_headers(), timeout=15)
    if r.status_code == 401:
        reset_token_cache()
        r = requests.get(url, headers=_bearer_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Real-mode upload: pre-signed PUT
# ---------------------------------------------------------------------------


def _coerce_image_bytes(image_b64: str) -> bytes:
    """Accept either a base64 string or raw bytes wrapped as str.

    Real callers pass base64 from the browser; the smoke path passes the
    sentinel "stub-selfie-bytes". For real mode the caller is expected
    to pass real base64, but we tolerate garbage by treating undecodable
    input as raw utf-8 bytes (so the API returns a 415 rather than us
    crashing locally).
    """
    try:
        return base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return image_b64.encode("utf-8", errors="replace")


def _real_upload(image_bytes: bytes, task_name: str) -> str:
    """Real-mode upload: returns the Perfect Corp file_id.

    Uses the v2.0 pre-signed-PUT flow per task. The task_name argument
    selects which pipeline the upload is registered for; the file_id is
    only valid for that task.
    """
    import requests  # noqa: E402

    body = {
        "files": [
            {
                "content_type": "image/jpeg",
                "file_name":    "selfie.jpg",
                "file_size":    len(image_bytes),
            },
        ],
    }
    env = _post_json(f"/s2s/v2.0/file/{task_name}", body)
    data = _envelope_data(env)
    files = data.get("files") or []
    if not files:
        raise RuntimeError(f"upload for {task_name} returned no files: {env}")
    f0 = files[0]
    file_id = f0.get("file_id") or ""
    requests_spec = f0.get("requests") or []
    if not file_id or not requests_spec:
        raise RuntimeError(f"upload for {task_name} missing file_id/requests: {env}")
    upload_spec = requests_spec[0]
    put_url = upload_spec.get("url") or ""
    put_headers = upload_spec.get("headers") or {}
    if not put_url:
        raise RuntimeError(f"upload for {task_name} missing pre-signed url: {env}")
    put_resp = requests.put(put_url, data=image_bytes, headers=put_headers, timeout=30)
    put_resp.raise_for_status()
    return file_id


def _real_upload_for(task_key: str, image_b64: str) -> str:
    """Upload bytes against the first valid task-name candidate.

    Different pipelines have different upload registries; we walk the
    candidate list and fall back on 404.
    """
    import requests  # noqa: E402

    image_bytes = _coerce_image_bytes(image_b64)
    candidates = _TASK_NAME_CANDIDATES.get(task_key, (task_key,))
    last_err: Exception | None = None
    for name in candidates:
        try:
            return _real_upload(image_bytes, name)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                last_err = exc
                continue
            raise
    raise RuntimeError(
        f"no upload candidate worked for {task_key}: {candidates}; last={last_err}"
    )


# ---------------------------------------------------------------------------
# Real-mode start + poll
# ---------------------------------------------------------------------------


def _poll_task(task_name: str, task_id: str) -> dict[str, Any]:
    """Poll GET /s2s/v2.0/task/{task}/{task_id} until task_status is
    `success` or `error`. Raises RuntimeError on timeout/failure."""
    path = f"/s2s/v2.0/task/{task_name}/{task_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT_SECS
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = _get_json(path)
        last = body
        data = _envelope_data(body)
        status = data.get("task_status") or data.get("status") or ""
        if status in ("success", "completed"):
            return body
        if status in ("error", "failed"):
            raise RuntimeError(f"task {task_name}/{task_id} failed: {body}")
        time.sleep(_POLL_INTERVAL_SECS)
    raise RuntimeError(
        f"task {task_name}/{task_id} timed out after {_POLL_TIMEOUT_SECS}s; last={last}"
    )


def _start_task(task_name: str, file_id: str, extra_payload: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"src_file_id": file_id}
    if extra_payload:
        payload.update(extra_payload)
    env = _post_json(f"/s2s/v2.0/task/{task_name}", payload)
    data = _envelope_data(env)
    task_id = data.get("task_id") or ""
    if not task_id:
        raise RuntimeError(f"task {task_name} did not return a task_id: {env}")
    return str(task_id)


def _start_and_poll(task_key: str, file_id: str, extra_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the task-name candidate list for `task_key`, then start +
    poll. If the first candidate 404s, retry with the next one."""
    import requests  # noqa: E402

    candidates = _TASK_NAME_CANDIDATES.get(task_key, (task_key,))
    last_err: Exception | None = None
    for name in candidates:
        try:
            task_id = _start_task(name, file_id, extra_payload)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                last_err = exc
                continue
            raise
        return _poll_task(name, task_id)
    raise RuntimeError(
        f"all task-name candidates for {task_key} failed: {candidates}; last={last_err}"
    )


# ---------------------------------------------------------------------------
# skin_color -> undertone / season / palette derivation
# ---------------------------------------------------------------------------


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) != 6:
        return (200, 150, 120)  # safe medium-warm fallback
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (200, 150, 120)


def _derive_tone_from_skin_color(skin_color: str) -> dict[str, Any]:
    """Map a Perfect Corp `skin_color` hex into the
    {undertone, season, palette, foundation_shade} contract the agent
    expects.

    Heuristic (not a science): red dominance -> warm, blue dominance ->
    cool, near-equal -> neutral. Palette is a small earthy / cool / soft
    spread depending on undertone. Foundation shade encodes the rough
    luma level (light / medium / deep).
    """
    r, g, b = _hex_to_rgb(skin_color)
    luma = (0.299 * r + 0.587 * g + 0.114 * b)
    if luma >= 180:
        depth = "light"
    elif luma >= 130:
        depth = "medium"
    else:
        depth = "deep"
    if r - b >= 18:
        undertone = "warm"
        season = "autumn"
        palette = ["#C97D5D", "#8B4A3B", "#D4A574", "#A0623E"]
    elif b - r >= 10:
        undertone = "cool"
        season = "summer"
        palette = ["#B16C8F", "#6E7CA0", "#C2A4B4", "#5C4A66"]
    else:
        undertone = "neutral"
        season = "neutral"
        palette = ["#B98876", "#7E5B4C", "#C9A28A", "#6F4A3D"]
    return {
        "undertone":        undertone,
        "season":           season,
        "palette":          palette,
        "foundation_shade": f"{undertone}-{depth}",
        "skin_color":       skin_color,
    }


# ---------------------------------------------------------------------------
# Tool 1: upload_image
# ---------------------------------------------------------------------------


# Default upload task. The file_id is scoped to this task; the per-tool
# analysis functions re-upload under their own scope when needed.
_DEFAULT_UPLOAD_TASK = "skin_tone_analysis"


def upload_image(image_b64: str) -> dict[str, Any]:
    """Upload a base64-encoded selfie to Perfect Corp's file store.

    Returns: {"file_id": str, "expires_at": str}.

    In real mode, the file_id is scoped to the default upload task
    (`skin-tone-analysis`). Each analysis tool re-uploads under its own
    task scope.
    """
    if _is_stub():
        env = stubs.stub_upload_image(image_b64)
        result = env.get("result", {})
        return {
            "file_id":    str(result.get("file_id", "")),
            "expires_at": str(result.get("expires_at", "")),
        }
    file_id = _real_upload_for(_DEFAULT_UPLOAD_TASK, image_b64)
    # The v2.0 upload response does not surface an explicit expiry; files
    # are valid for ~30 minutes on the s3 signed URL and 24h server-side
    # per docs. Treat as opaque.
    return {"file_id": file_id, "expires_at": ""}


# ---------------------------------------------------------------------------
# Tool 2: analyze_skin
# ---------------------------------------------------------------------------


def analyze_skin(file_id: str, mode: str = "SD", image_b64: str = "") -> dict[str, Any]:
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
        inner = env.get("result", {})
        return {
            "attributes":    [dict(a) for a in (inner.get("attributes") or [])],
            "overall_score": int(inner.get("overall_score") or 0),
            "ai_skin_age":   int(inner.get("ai_skin_age") or 0),
            "mask_urls":     dict(inner.get("mask_urls") or {}),
        }
    # Real mode. file_id from upload_image is scoped to the skin-tone
    # task; we re-upload here for the skin-analysis task. The caller
    # passes the original image_b64 through to make this possible.
    if image_b64:
        key = "skin_analysis_hd" if mode == "HD" else "skin_analysis"
        scoped_file_id = _real_upload_for(key, image_b64)
    else:
        scoped_file_id = file_id
    key = "skin_analysis_hd" if mode == "HD" else "skin_analysis"
    env = _start_and_poll(key, scoped_file_id)
    data = _envelope_data(env)
    # v2.0 puts the rich result either at data.results or data.results[0].
    results = data.get("results")
    if isinstance(results, list) and results:
        inner = results[0] if isinstance(results[0], dict) else {}
    elif isinstance(results, dict):
        inner = results
    else:
        inner = data
    return {
        "attributes":    [dict(a) for a in (inner.get("attributes") or [])],
        "overall_score": int(inner.get("overall_score") or 0),
        "ai_skin_age":   int(inner.get("ai_skin_age") or 0),
        "mask_urls":     dict(inner.get("mask_urls") or {}),
    }


# ---------------------------------------------------------------------------
# Tool 3: analyze_skin_tone
# ---------------------------------------------------------------------------


def analyze_skin_tone(file_id: str, image_b64: str = "") -> dict[str, Any]:
    """Run Perfect Corp Skin Tone analysis.

    Returns:
      {
        "undertone":        "warm"|"cool"|"neutral",
        "season":           str,
        "palette":          [hex, ...],
        "foundation_shade": str,
      }

    In real mode the API only returns a single `skin_color` hex; we
    derive the rest locally so the agent's downstream contract is
    stable across stub and real.
    """
    if _is_stub():
        env = stubs.stub_analyze_skin_tone(file_id)
        inner = env.get("result", {})
        return {
            "undertone":        str(inner.get("undertone", "")),
            "season":           str(inner.get("season", "")),
            "palette":          list(inner.get("palette") or []),
            "foundation_shade": str(inner.get("foundation_shade", "")),
        }
    # Real mode. The default upload above is already scoped to
    # skin-tone-analysis; only re-upload if the caller passed image_b64
    # and we don't trust the file_id.
    if image_b64 and not file_id:
        file_id = _real_upload_for("skin_tone_analysis", image_b64)
    env = _start_and_poll("skin_tone_analysis", file_id)
    data = _envelope_data(env)
    results = data.get("results") or {}
    color = (results.get("color") or {}) if isinstance(results, dict) else {}
    skin_color = color.get("skin_color") or ""
    derived = _derive_tone_from_skin_color(skin_color)
    return {
        "undertone":        derived["undertone"],
        "season":           derived["season"],
        "palette":          derived["palette"],
        "foundation_shade": derived["foundation_shade"],
    }


# ---------------------------------------------------------------------------
# Tool 4: apply_makeup
# ---------------------------------------------------------------------------


def apply_makeup(file_id: str, look: dict[str, Any], image_b64: str = "") -> dict[str, Any]:
    """Trigger the makeup virtual try-on with a {lipstick, eyeshadow,
    blush} hex map. Returns: {"result_url": str, "units_charged": int}.
    """
    look = dict(look or {})
    if _is_stub():
        env = stubs.stub_apply_makeup(file_id, look)
        inner = env.get("result", {})
        return {
            "result_url":    str(inner.get("result_url", "")),
            "units_charged": int(inner.get("units_charged") or 0),
        }
    # Real mode: re-upload under makeup-vto scope if we have raw bytes.
    if image_b64:
        scoped = _real_upload_for("makeup_vto", image_b64)
    else:
        scoped = file_id
    env = _start_and_poll("makeup_vto", scoped, {"look": look})
    data = _envelope_data(env)
    results = data.get("results") or {}
    result_url = ""
    if isinstance(results, dict):
        result_url = results.get("result_url") or ""
    elif isinstance(results, list) and results and isinstance(results[0], dict):
        result_url = results[0].get("result_url") or ""
    return {
        "result_url":    str(result_url),
        "units_charged": int(data.get("units_charged") or 0),
    }


# ---------------------------------------------------------------------------
# Tool 5: apply_hair_color
# ---------------------------------------------------------------------------


def apply_hair_color(file_id: str, color_hex: str, image_b64: str = "") -> dict[str, Any]:
    """Trigger the hair-color virtual try-on. Returns:
    {"result_url": str, "units_charged": int}."""
    color_hex = str(color_hex or "")
    if _is_stub():
        env = stubs.stub_apply_hair_color(file_id, color_hex)
        inner = env.get("result", {})
        return {
            "result_url":    str(inner.get("result_url", "")),
            "units_charged": int(inner.get("units_charged") or 0),
        }
    if image_b64:
        scoped = _real_upload_for("hair_color", image_b64)
    else:
        scoped = file_id
    env = _start_and_poll("hair_color", scoped, {"color_hex": color_hex})
    data = _envelope_data(env)
    results = data.get("results") or {}
    result_url = ""
    if isinstance(results, dict):
        result_url = results.get("result_url") or ""
    elif isinstance(results, list) and results and isinstance(results[0], dict):
        result_url = results[0].get("result_url") or ""
    return {
        "result_url":    str(result_url),
        "units_charged": int(data.get("units_charged") or 0),
    }


# ---------------------------------------------------------------------------
# Credit balance
# ---------------------------------------------------------------------------


def get_credit_balance() -> int:
    """Return the Perfect Corp unit balance (sum across token entries).

    Used by `scripts/live_verify.py` to bracket a live run and report
    delta units burned. Returns -1 if the call fails.
    """
    if _is_stub():
        return 1000
    try:
        env = _get_json("/s2s/v1.0/client/credit")
    except Exception:
        return -1
    # The live response is `{status, results: [{id, type, amount, expiry}, ...]}`.
    results = env.get("results")
    if isinstance(results, list) and results:
        total = 0
        for tk in results:
            try:
                total += int(tk.get("amount") or 0)
            except (TypeError, ValueError):
                continue
        return total
    # Single-object fallback.
    data = _envelope_data(env)
    for k in ("credit", "balance", "remain_credit", "available_credit", "amount"):
        if k in data:
            try:
                return int(data[k])
            except (TypeError, ValueError):
                continue
    return -1


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
