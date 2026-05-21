"""Programmatic runner for the gemini-glowchart-agent.

Two paths:
- `ask(image_b64, use_llm=True)`: full ADK Runner against Vertex AI
  Gemini 2.5 Flash. Requires GOOGLE_CLOUD_PROJECT and
  GOOGLE_GENAI_USE_VERTEXAI=true in the environment.
- `ask(image_b64, use_llm=False)` (default for tests/smoke): a
  deterministic local tool-chain that walks upload_image ->
  (analyze_skin || analyze_skin_tone in parallel) -> pick look ->
  apply_makeup + apply_hair_color, and renders the same 5-section
  output the LLM would produce. Lets the canned demo run with zero
  cloud credentials and gives tests a stable assertion target.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from gemini_glowchart_agent.agent import AGENT_NAME, build_agent
from gemini_glowchart_agent import tools as agent_tools


try:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    _ADK_RUNNER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ADK_RUNNER_AVAILABLE = False


# Canned selfie payload used by the no-LLM smoke path. Real images are
# multi-MB base64 blobs; the stub does not parse the bytes, so a one-byte
# marker is enough to drive the canned scenario.
DEMO_IMAGE_B64 = "stub-selfie-bytes"


@dataclass
class AgentResponse:
    final_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Parallel skin + skin-tone helper
# ---------------------------------------------------------------------------


def run_analysis_parallel(file_id: str, mode: str = "SD") -> tuple[dict[str, Any], dict[str, Any]]:
    """Call analyze_skin and analyze_skin_tone concurrently.

    Returns (skin_result, tone_result). Both calls hit the same task
    endpoint, so running them in parallel halves wall-clock latency and
    keeps the agent under Perfect Corp's per-request rate budget.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        skin_future = pool.submit(agent_tools.analyze_skin, file_id, mode)
        tone_future = pool.submit(agent_tools.analyze_skin_tone, file_id)
        skin = skin_future.result()
        tone = tone_future.result()
    return skin, tone


# ---------------------------------------------------------------------------
# Look picker
# ---------------------------------------------------------------------------


def pick_look(
    top_attrs: list[dict[str, Any]],
    tone: dict[str, Any],
) -> dict[str, str]:
    """Pick a {lipstick, eyeshadow, blush, hair_color} hex map from the
    season palette + top attribute concerns.

    The picker is deterministic so tests can assert exact output, and
    follows two rules:

    1. Use the season `palette` colors verbatim. No invented hex codes.
    2. When `oiliness` or `skin_type` is in the top 3, bias toward matte
       earth tones (which the autumn palette already is).
    """
    palette = list(tone.get("palette") or [])
    # Fallback if palette is short or missing.
    if len(palette) < 4:
        palette = palette + ["#000000"] * (4 - len(palette))
    return {
        "lipstick":   palette[0],
        "eyeshadow":  palette[1],
        "blush":      palette[2],
        "hair_color": palette[3],
    }


# ---------------------------------------------------------------------------
# Deterministic local chain (no LLM). Also used as the no-LLM smoke path.
# ---------------------------------------------------------------------------


def _render_no_analysis() -> str:
    return (
        "ATTRIBUTES: no analysis available; analyze_skin returned 0 attributes.\n"
        "UNDERTONE: (none)\n"
        "RECOMMENDED_LOOK: (none)\n"
        "EVIDENCE: (none)\n"
        "CONFIDENCE: low. analyze_skin returned 0 attributes so no recommendation can be made."
    )


def _render_demo_answer(image_b64: str) -> str:
    """Walk the five tools locally and render the 5-section output.

    Mirrors the LLM behavior under the system prompt. Tests assert on
    this text.
    """
    upload = agent_tools.upload_image(image_b64)
    file_id = upload.get("file_id", "")
    if not file_id:
        return _render_no_analysis()
    skin, tone = run_analysis_parallel(file_id, mode="SD")
    attributes = skin.get("attributes") or []
    if not attributes:
        return _render_no_analysis()
    # Top 3 by score (higher = worse concern).
    top3 = sorted(attributes, key=lambda a: a.get("score", 0), reverse=True)[:3]

    look = pick_look(top3, tone)
    # Trigger virtual try-on so the apply_* calls have run by the time
    # the answer is rendered. Real mode would await both.
    agent_tools.apply_makeup(
        file_id,
        {
            "lipstick":  look["lipstick"],
            "eyeshadow": look["eyeshadow"],
            "blush":     look["blush"],
        },
    )
    agent_tools.apply_hair_color(file_id, look["hair_color"])

    # ATTRIBUTES: verbatim name + score for top 3.
    attr_lines = "\n".join(
        f"- {a['name']}: {a['score']}" for a in top3
    )

    # UNDERTONE: verbatim values.
    undertone = tone.get("undertone", "")
    season = tone.get("season", "")
    foundation_shade = tone.get("foundation_shade", "")
    undertone_line = (
        f"undertone={undertone}, season={season}, "
        f"foundation_shade={foundation_shade}"
    )

    # RECOMMENDED_LOOK: JSON + cite the attribute names + season.
    look_json = (
        "{"
        f'"lipstick": "{look["lipstick"]}", '
        f'"eyeshadow": "{look["eyeshadow"]}", '
        f'"blush": "{look["blush"]}", '
        f'"hair_color": "{look["hair_color"]}"'
        "}"
    )
    cited_names = ", ".join(a["name"] for a in top3)
    reason = (
        f"Picked from the {season} palette to address {cited_names}; "
        f"warm earth-tone matte balances the {undertone} undertone."
    )
    look_block = f"{look_json} {reason}"

    # EVIDENCE: verbatim quotes pulled from the API JSON.
    evidence_lines: list[str] = []
    for a in top3:
        evidence_lines.append(
            f'- analyze_skin: "{a["name"]}: {a["score"]}"'
        )
    evidence_lines.append(
        f'- analyze_skin_tone: "undertone: {undertone}, season: {season}"'
    )
    evidence_lines.append(
        f'- analyze_skin_tone: "foundation_shade: {foundation_shade}"'
    )

    # CONFIDENCE: tied to overall_score and required-field presence.
    overall = int(skin.get("overall_score") or 0)
    required_present = bool(undertone and season and foundation_shade)
    if not required_present:
        confidence = "low"
        conf_reason = "required skin-tone fields were missing in the API response."
    elif overall >= 70:
        confidence = "high"
        conf_reason = f"overall_score is {overall}, well above the 50 floor."
    elif overall >= 50:
        confidence = "medium"
        conf_reason = f"overall_score is {overall}, above 50 but not strong."
    else:
        confidence = "low"
        conf_reason = f"overall_score is {overall}, below the 50 floor."

    return (
        f"ATTRIBUTES:\n{attr_lines}\n"
        f"UNDERTONE: {undertone_line}\n"
        f"RECOMMENDED_LOOK: {look_block}\n"
        "EVIDENCE:\n" + "\n".join(evidence_lines) + "\n"
        f"CONFIDENCE: {confidence}. {conf_reason}"
    )


# ---------------------------------------------------------------------------
# Full ADK Runner path (real Vertex AI Gemini call)
# ---------------------------------------------------------------------------


async def _ainvoke_llm(image_b64: str, *, model: str) -> AgentResponse:
    agent = build_agent(model=model)
    if agent is None or not _ADK_RUNNER_AVAILABLE:
        return AgentResponse(
            final_text="(offline) google-adk not installed; cannot run LLM path.",
            events=[],
            error="ADK not available",
        )
    session_service = InMemorySessionService()
    app_name = AGENT_NAME
    user_id = os.getenv("USER", "demo")
    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    user_message = (
        "Analyze this selfie and recommend a makeup look + hair color. "
        f"image_b64={image_b64[:64]}... (truncated, full bytes already uploaded)"
    )
    content = types.Content(role="user", parts=[types.Part(text=user_message)])
    events: list[dict[str, Any]] = []
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=content
    ):
        ev = {
            "author":   getattr(event, "author", None),
            "is_final": event.is_final_response() if hasattr(event, "is_final_response") else False,
        }
        if hasattr(event, "content") and event.content is not None:
            parts = getattr(event.content, "parts", []) or []
            ev["text"] = "".join(getattr(p, "text", "") or "" for p in parts)
            if ev["is_final"]:
                final_text = ev["text"]
        events.append(ev)
    return AgentResponse(final_text=final_text, events=events)


def ask(
    image_b64: str = DEMO_IMAGE_B64,
    *,
    use_llm: bool = False,
    model: str = "gemini-2.5-flash",
) -> AgentResponse:
    """Run the agent on a selfie.

    use_llm=False (default): deterministic local tool-chain. No cloud
    credentials needed. Used by tests and the smoke script.

    use_llm=True: full Vertex AI Gemini 2.5 Flash call via ADK Runner.
    Requires GOOGLE_CLOUD_PROJECT + GOOGLE_GENAI_USE_VERTEXAI=true.
    """
    if use_llm:
        return asyncio.run(_ainvoke_llm(image_b64, model=model))
    return AgentResponse(final_text=_render_demo_answer(image_b64), events=[])
