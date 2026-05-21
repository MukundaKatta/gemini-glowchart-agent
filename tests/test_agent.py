"""Smoke tests for agent build + end-to-end deterministic chain."""

from unittest.mock import patch

from gemini_glowchart_agent.agent import _ADK_AVAILABLE, build_agent
from gemini_glowchart_agent.runner import (
    DEMO_IMAGE_B64,
    ask,
    pick_look,
    run_analysis_parallel,
)
from gemini_glowchart_agent import tools as agent_tools


def test_adk_importable():
    assert _ADK_AVAILABLE


def test_agent_constructs_with_five_tools():
    agent = build_agent()
    assert agent is not None
    assert agent.name == "gemini_glowchart_agent"
    tools = list(getattr(agent, "tools", []) or [])
    # Five FunctionTool wrappers: upload_image, analyze_skin,
    # analyze_skin_tone, apply_makeup, apply_hair_color.
    assert len(tools) == 5


def test_end_to_end_demo_quotes_verbatim_strings():
    """The killer test: run the canned scenario and assert the verbatim
    attribute name, undertone, season, and foundation_shade appear in
    the final answer."""
    resp = ask(DEMO_IMAGE_B64)
    text = resp.final_text or ""
    upper = text.upper()
    # 5 sections present.
    for section in (
        "ATTRIBUTES",
        "UNDERTONE",
        "RECOMMENDED_LOOK",
        "EVIDENCE",
        "CONFIDENCE",
    ):
        assert section in upper, f"missing section: {section}"
    # Verbatim strings the prompt requires.
    assert "oiliness" in text
    assert "warm" in text
    assert "autumn" in text
    assert "warm-medium-3" in text


def test_top3_attributes_have_verbatim_scores():
    """The top 3 attributes by score in the canned scenario are
    skin_type (72), oiliness (70), pore (65). The rendered ATTRIBUTES
    section must list those three with byte-for-byte score values."""
    resp = ask(DEMO_IMAGE_B64)
    text = resp.final_text or ""
    assert "skin_type: 72" in text
    assert "oiliness: 70" in text
    assert "pore: 65" in text


def test_recommended_look_uses_palette_hex_codes():
    """RECOMMENDED_LOOK must use the verbatim hex codes from the
    skin-tone palette. No invented hex codes."""
    resp = ask(DEMO_IMAGE_B64)
    text = resp.final_text or ""
    assert "#C97D5D" in text
    assert "#8B4A3B" in text
    assert "#D4A574" in text
    assert "#A0623E" in text


def test_no_hallucination_when_zero_attributes():
    """Negative test: if analyze_skin returns 0 attributes, the agent
    must NOT pick a look or invent attribute names. Emit the no-analysis
    path with CONFIDENCE: low."""
    from gemini_glowchart_agent import stubs

    with patch.object(
        agent_tools.stubs,
        "stub_analyze_skin",
        side_effect=stubs.stub_analyze_skin_empty,
    ):
        resp = ask(DEMO_IMAGE_B64)
    text = resp.final_text or ""
    upper = text.upper()
    assert "ATTRIBUTES" in upper
    assert "CONFIDENCE" in upper
    assert "no analysis available" in text
    # Must not invent attribute names or hex codes from the canned
    # scenario.
    assert "oiliness" not in text
    assert "#C97D5D" not in text
    # Must signal low confidence.
    assert "low" in text.lower()


def test_run_analysis_parallel_runs_concurrently():
    """The agent code MUST batch analyze_skin + analyze_skin_tone in
    parallel. We assert this with a Barrier(2) inside both spies: if
    the calls are sequential, the barrier will time out and the test
    fails. If they are parallel, both spies cross the barrier and the
    call returns normally.
    """
    import threading

    barrier = threading.Barrier(2, timeout=2.0)
    real_skin = agent_tools.analyze_skin
    real_tone = agent_tools.analyze_skin_tone

    def spy_skin(file_id, mode="SD"):
        barrier.wait()
        return real_skin(file_id, mode)

    def spy_tone(file_id):
        barrier.wait()
        return real_tone(file_id)

    with patch.object(agent_tools, "analyze_skin", side_effect=spy_skin), \
            patch.object(agent_tools, "analyze_skin_tone", side_effect=spy_tone):
        skin, tone = run_analysis_parallel("file_demo_20260521_abc123")

    # If we got here, both spies cleared the barrier within the timeout,
    # which only happens when the two calls are in flight at the same time.
    assert skin["attributes"]
    assert tone["season"] == "autumn"


def test_pick_look_uses_palette_only():
    """pick_look must never invent hex codes; every output hex must be
    in the input palette."""
    tone = {
        "undertone":        "warm",
        "season":           "autumn",
        "palette":          ["#C97D5D", "#8B4A3B", "#D4A574", "#A0623E"],
        "foundation_shade": "warm-medium-3",
    }
    top3 = [
        {"name": "skin_type", "score": 72},
        {"name": "oiliness",  "score": 70},
        {"name": "pore",      "score": 65},
    ]
    look = pick_look(top3, tone)
    palette_set = set(tone["palette"])
    for key in ("lipstick", "eyeshadow", "blush", "hair_color"):
        assert look[key] in palette_set, f"{key} not from palette: {look[key]}"
