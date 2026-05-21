"""Unit tests for the five agent tools, asserting Perfect Corp YouCam
API-shaped fields. Stub mode is forced by conftest.py so these run with
zero Perfect Corp creds.
"""

from gemini_glowchart_agent.tools import (
    analyze_skin,
    analyze_skin_tone,
    apply_hair_color,
    apply_makeup,
    upload_image,
)


# ---------------------------------------------------------------------------
# Tool 1: upload_image
# ---------------------------------------------------------------------------


def test_upload_image_returns_file_id_and_expires_at():
    out = upload_image("stub-selfie-bytes")
    assert set(out.keys()) == {"file_id", "expires_at"}
    assert isinstance(out["file_id"], str) and out["file_id"]
    assert isinstance(out["expires_at"], str) and out["expires_at"]
    # ISO-8601-ish: 2026-05-22T09:15:00Z
    assert "T" in out["expires_at"] and out["expires_at"].endswith("Z")


# ---------------------------------------------------------------------------
# Tool 2: analyze_skin
# ---------------------------------------------------------------------------


def test_analyze_skin_returns_15_attributes_with_perfect_corp_shape():
    out = analyze_skin("file_demo_20260521_abc123", mode="SD")
    assert set(out.keys()) >= {"attributes", "overall_score", "ai_skin_age", "mask_urls"}
    assert isinstance(out["attributes"], list)
    assert len(out["attributes"]) == 15
    # Each attribute has the Perfect Corp shape: name + score + severity.
    for a in out["attributes"]:
        assert set(a.keys()) >= {"name", "score", "severity"}
        assert isinstance(a["name"], str) and a["name"]
        assert isinstance(a["score"], int)
        assert 1 <= a["score"] <= 100
        assert a["severity"] in ("low", "medium", "high")
    # Verbatim names the prompt depends on.
    names = {a["name"] for a in out["attributes"]}
    assert {"oiliness", "pore", "skin_type"}.issubset(names)
    # Verbatim scores the prompt depends on.
    by_name = {a["name"]: a["score"] for a in out["attributes"]}
    assert by_name["oiliness"] == 70
    assert by_name["pore"] == 65
    assert by_name["skin_type"] == 72


# ---------------------------------------------------------------------------
# Tool 3: analyze_skin_tone
# ---------------------------------------------------------------------------


def test_analyze_skin_tone_returns_warm_autumn_palette():
    out = analyze_skin_tone("file_demo_20260521_abc123")
    assert set(out.keys()) == {"undertone", "season", "palette", "foundation_shade"}
    assert out["undertone"] == "warm"
    assert out["season"] == "autumn"
    assert out["foundation_shade"] == "warm-medium-3"
    assert out["palette"] == ["#C97D5D", "#8B4A3B", "#D4A574", "#A0623E"]


# ---------------------------------------------------------------------------
# Tool 4: apply_makeup
# ---------------------------------------------------------------------------


def test_apply_makeup_returns_result_url_and_units_charged():
    out = apply_makeup(
        "file_demo_20260521_abc123",
        {
            "lipstick":  "#C97D5D",
            "eyeshadow": "#8B4A3B",
            "blush":     "#D4A574",
        },
    )
    assert set(out.keys()) == {"result_url", "units_charged"}
    assert isinstance(out["result_url"], str)
    assert out["result_url"].startswith("https://")
    assert isinstance(out["units_charged"], int)
    assert out["units_charged"] >= 1


# ---------------------------------------------------------------------------
# Tool 5: apply_hair_color
# ---------------------------------------------------------------------------


def test_apply_hair_color_returns_result_url_and_units_charged():
    out = apply_hair_color("file_demo_20260521_abc123", "#A0623E")
    assert set(out.keys()) == {"result_url", "units_charged"}
    assert isinstance(out["result_url"], str)
    assert out["result_url"].startswith("https://")
    assert isinstance(out["units_charged"], int)
    assert out["units_charged"] >= 1


# ---------------------------------------------------------------------------
# Cross-tool consistency
# ---------------------------------------------------------------------------


def test_upload_then_analyze_chain_is_consistent():
    """The file_id from upload_image is what analyze_skin + analyze_skin_tone
    expect. Both calls return success-shaped envelopes for that same id.
    """
    up = upload_image("stub-selfie-bytes")
    fid = up["file_id"]
    skin = analyze_skin(fid)
    tone = analyze_skin_tone(fid)
    # Skin gave us a non-empty attribute list and a plausible overall_score.
    assert skin["attributes"]
    assert 0 < skin["overall_score"] <= 100
    # Tone returned the autumn palette.
    assert tone["season"] == "autumn"
    assert tone["palette"][0] == "#C97D5D"
