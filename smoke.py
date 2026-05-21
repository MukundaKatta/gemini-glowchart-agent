"""End-to-end smoke test for gemini-glowchart-agent in stub mode.

Runs the deterministic tool chain (upload_image -> analyze_skin ||
analyze_skin_tone -> pick look -> apply_makeup + apply_hair_color ->
rendered 5-section answer) on the canned demo selfie and asserts every
load-bearing string is present.

Usage:
    GLOWCHART_STUB=1 .venv/bin/python smoke.py
"""

from __future__ import annotations

import os
import sys

# Stub mode by default.
os.environ.setdefault("GLOWCHART_STUB", "1")

from gemini_glowchart_agent.runner import DEMO_IMAGE_B64, ask  # noqa: E402


def main() -> int:
    print("== gemini-glowchart-agent smoke ==")
    print(f"stub_mode={os.environ.get('GLOWCHART_STUB')}")
    print()
    print(f"> selfie={DEMO_IMAGE_B64!r}")
    print()
    resp = ask(DEMO_IMAGE_B64, use_llm=False)
    print("--- FINAL TEXT ---")
    print(resp.final_text)
    print("--- END FINAL TEXT ---")
    print()
    text = resp.final_text or ""
    upper = text.upper()
    checks = {
        "has ATTRIBUTES section":              "ATTRIBUTES" in upper,
        "has UNDERTONE section":               "UNDERTONE" in upper,
        "has RECOMMENDED_LOOK section":        "RECOMMENDED_LOOK" in upper,
        "has EVIDENCE section":                "EVIDENCE" in upper,
        "has CONFIDENCE section":              "CONFIDENCE" in upper,
        "quotes oiliness verbatim":            "oiliness" in text,
        "quotes pore verbatim":                "pore" in text,
        "quotes skin_type verbatim":           "skin_type" in text,
        "quotes oiliness score 70":            "oiliness: 70" in text,
        "quotes warm undertone":               "warm" in text,
        "quotes autumn season":                "autumn" in text,
        "quotes warm-medium-3 foundation":     "warm-medium-3" in text,
        "uses palette hex #C97D5D":            "#C97D5D" in text,
        "uses palette hex #A0623E for hair":   "#A0623E" in text,
    }
    print("--- CHECKS ---")
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
