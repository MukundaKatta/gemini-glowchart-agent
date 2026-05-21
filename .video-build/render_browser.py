"""Render scene 3 (browser screencast) for the gemini-glowchart-agent demo.

Drives the live Cloud Run URL with Playwright, capturing PNG screenshots
at six key states (load, hover the canned demo button, click, thinking,
answer rendered, scroll). Stitches into a smooth ~50s scene plus a
closing overlay card.

Outputs:
    .video-build/browser_frame_*.png
    .video-build/scene3_browser.mp4
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
W, H = 1920, 1080
URL = "https://gemini-glowchart-agent-1029931682737.us-central1.run.app/"

SF = "/System/Library/Fonts/SFNS.ttf"
MONO = "/System/Library/Fonts/SFNSMono.ttf"
if not Path(MONO).exists():
    MONO = "/System/Library/Fonts/Menlo.ttc"


def grab_browser_frames() -> list[Path]:
    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H},
                                  device_scale_factor=1)
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        # Frame 1: initial load.
        p1 = OUT / "browser_frame_01.png"
        page.screenshot(path=str(p1), full_page=False)
        paths.append(p1)

        # Frame 2: hover the canned demo button.
        page.hover("#demo")
        time.sleep(0.3)
        p2 = OUT / "browser_frame_02.png"
        page.screenshot(path=str(p2), full_page=False)
        paths.append(p2)

        # Frame 3: just before click (still showing button focus).
        page.focus("#demo")
        time.sleep(0.2)
        p3 = OUT / "browser_frame_03.png"
        page.screenshot(path=str(p3), full_page=False)
        paths.append(p3)

        # Trigger the canned demo.
        page.click("#demo")
        try:
            page.wait_for_function(
                "() => document.getElementById('out').textContent.includes('ATTRIBUTES:')",
                timeout=45_000,
            )
        except Exception:
            time.sleep(8)
        p4 = OUT / "browser_frame_04.png"
        page.screenshot(path=str(p4), full_page=False)
        paths.append(p4)

        page.evaluate("window.scrollTo(0,0)")
        time.sleep(0.6)
        p5 = OUT / "browser_frame_05.png"
        page.screenshot(path=str(p5), full_page=False)
        paths.append(p5)

        page.evaluate("window.scrollBy(0, 220)")
        time.sleep(0.6)
        p6 = OUT / "browser_frame_06.png"
        page.screenshot(path=str(p6), full_page=False)
        paths.append(p6)

        ctx.close()
        browser.close()
    return paths


def render_closing_overlay(path: Path) -> None:
    img = Image.new("RGB", (W, H), "#1a0f1a")
    d = ImageDraw.Draw(img)
    title_f = ImageFont.truetype(SF, 90)
    sub_f = ImageFont.truetype(SF, 40)
    url_f = ImageFont.truetype(MONO, 36)
    d.text((96, 320), "gemini-glowchart-agent", font=title_f, fill="#fdf2f8")
    d.rectangle([(96, 460), (380, 472)], fill="#f472b6")
    d.text((96, 520), "Skin reads. Verbatim citations.", font=sub_f, fill="#e9a8c5")
    d.text((96, 580), "Picks the look for you.", font=sub_f, fill="#e9a8c5")
    d.text((96, 720), "Code:", font=sub_f, fill="#e9a8c5")
    d.text((96, 780), "github.com/MukundaKatta/gemini-glowchart-agent",
           font=url_f, fill="#fbbf24")
    img.save(path, "PNG", optimize=True)


def build_scene_video(frames: list[Path], overlay: Path, mp4: Path) -> None:
    durs = [3.5, 3.5, 4.5, 7.0, 8.0, 8.0, 9.0]
    assert len(durs) == len(frames) + 1

    concat_file = OUT / "browser_concat.txt"
    files = frames + [overlay]
    lines: list[str] = []
    for p, dur in zip(files, durs):
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {dur}")
    lines.append(f"file '{files[-1].resolve()}'")
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
    frames = grab_browser_frames()
    print(f"  captured {len(frames)} browser frames")
    overlay = OUT / "browser_overlay.png"
    render_closing_overlay(overlay)
    print(f"  wrote {overlay.name}")
    mp4 = OUT / "scene3_browser.mp4"
    build_scene_video(frames, overlay, mp4)
    print(f"  wrote {mp4.name}")


if __name__ == "__main__":
    main()
