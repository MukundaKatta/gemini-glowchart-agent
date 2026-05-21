"""Hand-written fixtures shaped like the Perfect Corp YouCam API.

Returned objects mirror what `https://yce-api-01.makeupar.com` returns
for the five endpoints we use:

- POST /s2s/v1.0/file/upload-image -> {file_id, expires_at}
- POST /s2s/v1.1/task/skin-analysis -> {task_id} then GET task poll
  -> {task_status, result: {attributes, overall_score, ai_skin_age, mask_urls}}
- POST /s2s/v1.0/task/skin-tone -> task poll
  -> {undertone, season, palette, foundation_shade}
- POST /s2s/v1.0/task/makeup -> task poll -> {result_url, units_charged}
- POST /s2s/v1.0/task/hair-color -> task poll -> {result_url, units_charged}

The verbatim attribute names + scores live here. Anything the agent
quotes back to the user must appear in this file byte-for-byte.

The canned demo scenario: a 28-year-old with high oiliness (70), high
pore score (65), oily skin type (72), warm-autumn palette. Agent should
recommend a warm earth-tone matte makeup look + auburn hair color.
"""

from __future__ import annotations

from typing import Any


# Canned file_id the upload endpoint returns. Real API returns an opaque
# string + an ISO-8601 expires_at 24h out.
_STUB_FILE_ID = "file_demo_20260521_abc123"
_STUB_EXPIRES_AT = "2026-05-22T09:15:00Z"


# The 15 skin-analysis SD attributes. Names match the Perfect Corp
# YouCam Skin Analysis SD endpoint exactly. Scores are 1-100; higher
# means more severe concern (except moisture, radiance, firmness, where
# the scoring is inverted in the real API; we keep the same convention
# here so the agent sees identical shapes to real mode).
_SKIN_ATTRIBUTES: list[dict[str, Any]] = [
    {"name": "wrinkle",         "score": 22, "severity": "low"},
    {"name": "pore",            "score": 65, "severity": "high"},
    {"name": "acne",            "score": 18, "severity": "low"},
    {"name": "redness",         "score": 28, "severity": "low"},
    {"name": "dark_circles",    "score": 34, "severity": "medium"},
    {"name": "oiliness",        "score": 70, "severity": "high"},
    {"name": "moisture",        "score": 42, "severity": "medium"},
    {"name": "texture",         "score": 38, "severity": "medium"},
    {"name": "firmness",        "score": 25, "severity": "low"},
    {"name": "age_spots",       "score": 12, "severity": "low"},
    {"name": "radiance",        "score": 55, "severity": "medium"},
    {"name": "eye_bags",        "score": 30, "severity": "medium"},
    {"name": "tear_trough",     "score": 24, "severity": "low"},
    {"name": "droopy_eyelids",  "score": 15, "severity": "low"},
    {"name": "skin_type",       "score": 72, "severity": "high"},
]


# Skin tone analysis. Warm undertone, autumn season, autumn palette
# (verbatim hex codes the agent will quote back).
_SKIN_TONE = {
    "undertone":        "warm",
    "season":           "autumn",
    "palette":          ["#C97D5D", "#8B4A3B", "#D4A574", "#A0623E"],
    "foundation_shade": "warm-medium-3",
}


# ---------------------------------------------------------------------------
# Stub responses (Perfect Corp YouCam API-shaped envelopes)
# ---------------------------------------------------------------------------


def stub_upload_image(image_b64: str) -> dict[str, Any]:
    """Mirror of POST /s2s/v1.0/file/upload-image response.

    Real API returns `{"status": "success", "result": {"file_id": "...",
    "expires_at": "..."}}`. The tool wrapper flattens that to
    `{file_id, expires_at}`.
    """
    return {
        "status": "success",
        "result": {
            "file_id":    _STUB_FILE_ID,
            "expires_at": _STUB_EXPIRES_AT,
        },
    }


def stub_analyze_skin(file_id: str, mode: str = "SD") -> dict[str, Any]:
    """Mirror of the skin-analysis task poll response.

    Real API returns:
      {
        "task_status": "success",
        "result": {
          "attributes":   [{"name", "score", "severity"}, ...],
          "overall_score": int,
          "ai_skin_age":   int,
          "mask_urls":     {"pore": "...", "wrinkle": "...", ...}
        }
      }
    """
    return {
        "task_status": "success",
        "result": {
            "attributes":     [dict(a) for a in _SKIN_ATTRIBUTES],
            "overall_score":  68,
            "ai_skin_age":    28,
            "mask_urls": {
                "pore":     "https://cdn.perfectcorp.com/masks/demo/pore.png",
                "wrinkle":  "https://cdn.perfectcorp.com/masks/demo/wrinkle.png",
                "oiliness": "https://cdn.perfectcorp.com/masks/demo/oiliness.png",
            },
            "mode": mode,
        },
    }


def stub_analyze_skin_tone(file_id: str) -> dict[str, Any]:
    """Mirror of skin-tone task poll response."""
    return {
        "task_status": "success",
        "result": dict(_SKIN_TONE),
    }


def stub_apply_makeup(file_id: str, look: dict[str, Any]) -> dict[str, Any]:
    """Mirror of makeup virtual try-on task poll response.

    Real API returns `result_url` (signed CDN URL valid 1h) plus a
    `units_charged` int the customer is billed for.
    """
    return {
        "task_status": "success",
        "result": {
            "result_url":    "https://cdn.perfectcorp.com/vto/demo/makeup_result.jpg",
            "units_charged": 1,
            "applied_look":  dict(look),
        },
    }


def stub_apply_hair_color(file_id: str, color_hex: str) -> dict[str, Any]:
    """Mirror of hair-color virtual try-on task poll response."""
    return {
        "task_status": "success",
        "result": {
            "result_url":    "https://cdn.perfectcorp.com/vto/demo/hair_result.jpg",
            "units_charged": 1,
            "applied_color": color_hex,
        },
    }


# ---------------------------------------------------------------------------
# Failure-path stubs (negative tests assert on these)
# ---------------------------------------------------------------------------


def stub_analyze_skin_empty(file_id: str, mode: str = "SD") -> dict[str, Any]:
    """Simulate the API returning zero attributes (rare but real). The
    agent must NOT hallucinate a look in this case.
    """
    return {
        "task_status": "success",
        "result": {
            "attributes":    [],
            "overall_score": 0,
            "ai_skin_age":   0,
            "mask_urls":     {},
            "mode":          mode,
        },
    }
