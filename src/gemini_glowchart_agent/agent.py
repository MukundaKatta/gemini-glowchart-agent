"""ADK Gemini 2.5 Flash agent wired to Perfect Corp YouCam API.

Two modes (toggled by env var GLOWCHART_STUB):
- "1" (default): tools return hand-written fixtures from `stubs.py`.
  Lets reviewers reproduce the demo with zero Perfect Corp creds.
- "0": tools call the real Perfect Corp YouCam API at
  https://yce-api-01.makeupar.com using PERFECT_CORP_API_KEY.

The five FunctionTools (upload_image, analyze_skin, analyze_skin_tone,
apply_makeup, apply_hair_color) share one code path across both modes,
so the agent code is identical regardless of backend.
"""

from __future__ import annotations

from typing import Any

from gemini_glowchart_agent.prompt import SYSTEM_PROMPT
from gemini_glowchart_agent.tools import build_tools


try:
    from google.adk.agents import LlmAgent
    _ADK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ADK_AVAILABLE = False


AGENT_NAME = "gemini_glowchart_agent"


def build_agent(model: str = "gemini-2.5-flash") -> Any:
    """Build the ADK LlmAgent with the five Perfect Corp tools attached."""
    if not _ADK_AVAILABLE:
        return None
    return LlmAgent(
        model=model,
        name=AGENT_NAME,
        instruction=SYSTEM_PROMPT,
        tools=build_tools(),
    )
