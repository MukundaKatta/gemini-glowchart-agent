"""Render scene 2 (terminal screencast) for the gemini-glowchart-agent demo.

Renders a sequence of "terminal state" PNG frames showing pytest, smoke,
and curl output progressively, then stitches them into a single MP4
scene with deterministic per-frame timing.

Outputs:
    .video-build/terminal_state_*.png  (intermediate)
    .video-build/scene2_terminal.mp4   (~80s, 1920x1080, H.264, no audio)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1920, 1080

# Terminal palette (matches Apple Terminal "Pro" theme-ish).
BG = "#0b1020"
PROMPT = "#f472b6"
FG = "#fdf2f8"
DIM = "#e9a8c5"
GREEN = "#22c55e"
RED = "#f87171"
YELLOW = "#fbbf24"

MONO = "/System/Library/Fonts/SFNSMono.ttf"
if not Path(MONO).exists():
    MONO = "/System/Library/Fonts/Menlo.ttc"
SF = "/System/Library/Fonts/SFNS.ttf"

FONT_SIZE = 22
LINE_H = 30
PAD_X = 60
PAD_Y = 80


def mono(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO, size)


def title_font(size: int = 26) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(SF, size)


def make_blank() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (W, 50)], fill="#1a0f1a")
    d.text((PAD_X, 12), "gemini-glowchart-agent - demo terminal",
           font=title_font(22), fill=DIM)
    return img, d


def render_frame(lines: list[tuple[str, str]], path: Path) -> None:
    img, d = make_blank()
    y = PAD_Y
    for text, color in lines:
        d.text((PAD_X, y), text, font=mono(), fill=color)
        y += LINE_H
    img.save(path, "PNG", optimize=True)


def build_states() -> list[list[tuple[str, str]]]:
    L: list[tuple[str, str]] = []
    states: list[list[tuple[str, str]]] = []

    def commit() -> None:
        states.append(list(L))

    # ---- pytest ----
    L.append(("$ pytest -v", PROMPT))
    commit()
    L.append(("============================= test session starts ==============================", DIM))
    L.append(("platform darwin -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0", DIM))
    L.append(("collected 14 items", DIM))
    L.append(("", FG))
    commit()
    pytest_lines = [
        "tests/test_agent.py::test_adk_importable PASSED                          [  7%]",
        "tests/test_agent.py::test_agent_constructs_with_five_tools PASSED        [ 14%]",
        "tests/test_agent.py::test_end_to_end_demo_quotes_verbatim_strings PASSED [ 21%]",
        "tests/test_agent.py::test_top3_attributes_have_verbatim_scores PASSED    [ 28%]",
        "tests/test_agent.py::test_recommended_look_uses_palette_hex_codes PASSED [ 35%]",
        "tests/test_agent.py::test_no_hallucination_when_zero_attributes PASSED   [ 42%]",
        "tests/test_agent.py::test_run_analysis_parallel_runs_concurrently PASSED [ 50%]",
        "tests/test_agent.py::test_pick_look_uses_palette_only PASSED             [ 57%]",
        "tests/test_tools.py::test_upload_image_returns_file_id_and_expires      [ 64%]",
        "tests/test_tools.py::test_analyze_skin_returns_15_attributes_pc_shape   [ 71%]",
        "tests/test_tools.py::test_analyze_skin_tone_returns_warm_autumn_palette [ 78%]",
        "tests/test_tools.py::test_apply_makeup_returns_result_url_and_units     [ 85%]",
        "tests/test_tools.py::test_apply_hair_color_returns_result_url_and_units [ 92%]",
        "tests/test_tools.py::test_upload_then_analyze_chain_is_consistent       [100%]",
    ]
    chunk = 3
    for i in range(0, len(pytest_lines), chunk):
        for line in pytest_lines[i:i + chunk]:
            L.append((line, GREEN))
        commit()
    L.append(("", FG))
    L.append(("============================== 14 passed in 0.82s ==============================", GREEN))
    commit()
    L.append(("", FG))

    # ---- smoke ----
    L.append(("$ python smoke.py", PROMPT))
    commit()
    L.append(("== gemini-glowchart-agent smoke ==", DIM))
    L.append(("stub_mode=1", DIM))
    L.append(("", FG))
    L.append(("> selfie='stub-selfie-bytes'", FG))
    commit()
    smoke_pass = [
        "  [PASS] has ATTRIBUTES section",
        "  [PASS] has UNDERTONE section",
        "  [PASS] has RECOMMENDED_LOOK section",
        "  [PASS] has EVIDENCE section",
        "  [PASS] has CONFIDENCE section",
        "  [PASS] quotes oiliness verbatim",
        "  [PASS] quotes pore verbatim",
        "  [PASS] quotes skin_type verbatim",
        "  [PASS] quotes oiliness score 70",
        "  [PASS] quotes warm undertone",
        "  [PASS] quotes autumn season",
        "  [PASS] quotes warm-medium-3 foundation",
        "  [PASS] uses palette hex #C97D5D",
        "  [PASS] uses palette hex #A0623E for hair",
    ]
    L.append(("--- CHECKS ---", DIM))
    commit()
    # Split into 2 chunks of 7 for streaming feel.
    for line in smoke_pass[:7]:
        L.append((line, GREEN))
    commit()
    for line in smoke_pass[7:]:
        L.append((line, GREEN))
    L.append(("", FG))
    L.append(("14/14 PASS", GREEN))
    commit()
    L.append(("", FG))

    # ---- curl ----
    L.clear()
    L.append(("$ curl ... /ask  | jq -r .answer", PROMPT))
    L.append(("", FG))
    answer = [
        ("ATTRIBUTES:", YELLOW),
        ("  - skin_type: 72", FG),
        ("  - oiliness: 70", FG),
        ("  - pore: 65", FG),
        ("", FG),
        ("UNDERTONE:", YELLOW),
        ("  undertone=warm, season=autumn,", FG),
        ("  foundation_shade=warm-medium-3", FG),
        ("", FG),
        ("RECOMMENDED_LOOK:", YELLOW),
        ('  {"lipstick": "#C97D5D", "eyeshadow": "#8B4A3B",', FG),
        ('   "blush": "#D4A574", "hair_color": "#A0623E"}', FG),
        ("  Picked from the autumn palette to address", FG),
        ("  skin_type, oiliness, pore.", FG),
        ("", FG),
        ("EVIDENCE:", YELLOW),
        ('  - analyze_skin: "skin_type: 72"', FG),
        ('  - analyze_skin: "oiliness: 70"', FG),
        ('  - analyze_skin_tone: "undertone: warm, season: autumn"', FG),
        ('  - analyze_skin_tone: "foundation_shade: warm-medium-3"', FG),
        ("", FG),
        ("CONFIDENCE:", YELLOW),
        ("  medium. overall_score is 68, above 50 but not strong.", FG),
    ]
    chunks = [
        answer[:5],
        answer[5:10],
        answer[10:16],
        answer[16:],
    ]
    accumulated: list[tuple[str, str]] = []
    for ch in chunks:
        accumulated.extend(ch)
        L_snapshot = [("$ curl ... /ask  | jq -r .answer", PROMPT), ("", FG)] + accumulated
        states.append(L_snapshot)
    return states


def render_frames(states: list[list[tuple[str, str]]]) -> list[Path]:
    paths: list[Path] = []
    for i, lines in enumerate(states):
        p = OUT / f"terminal_state_{i:03d}.png"
        render_frame(lines, p)
        paths.append(p)
    return paths


def build_scene_video(frames: list[Path], mp4: Path) -> None:
    n = len(frames)
    defaults = [3.0] * n
    if n >= 4:
        defaults[-4] = 6.0
        defaults[-3] = 6.0
        defaults[-2] = 6.0
        defaults[-1] = 8.0
    defaults[0] = 2.0
    total = sum(defaults)
    target = 80.0
    scale = target / total
    durations = [round(d * scale, 2) for d in defaults]

    concat_file = OUT / "terminal_concat.txt"
    lines: list[str] = []
    for p, dur in zip(frames, durations):
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {dur}")
    lines.append(f"file '{frames[-1].resolve()}'")
    concat_file.write_text("\n".join(lines) + "\n")

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-vf", "scale=1920:1080,format=yuv420p",
            "-r", "30",
            "-c:v", "libx264", "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            str(mp4),
        ],
        check=True,
    )


def main() -> None:
    states = build_states()
    frames = render_frames(states)
    print(f"  rendered {len(frames)} terminal frames")
    mp4 = OUT / "scene2_terminal.mp4"
    build_scene_video(frames, mp4)
    print(f"  wrote {mp4.name}")


if __name__ == "__main__":
    main()
