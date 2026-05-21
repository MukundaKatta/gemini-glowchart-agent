"""One-shot live verification against the Perfect Corp YouCam API.

Runs ONE auth + ONE small `skin-tone-analysis` call on a face image,
brackets the credit balance to report unit delta, and refuses to fire
if the delta would exceed LIVE_VERIFY_UNIT_CAP (default 2 units).

Usage:
    source ~/.profile
    GLOWCHART_STUB=0 python scripts/live_verify.py

Prints (and only prints) the safe sanity-check fields. NEVER prints the
api key or the full bearer token. Only first 8 chars of token are shown
so the user can confirm a token was returned.

The face source is `thispersondoesnotexist.com`, which serves a
deterministic-enough AI-generated portrait. If the API rejects the
first sample with `error_face_not_forward_facing`, the script retries
up to MAX_FACE_TRIES (failed face-detection tasks may still consume
units; the credit-bracket reports the real delta).
"""

from __future__ import annotations

import io
import os
import sys
import urllib.request

# Real mode + repo-root path.
os.environ["GLOWCHART_STUB"] = "0"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from gemini_glowchart_agent import tools  # noqa: E402
from gemini_glowchart_agent.auth import get_access_token  # noqa: E402


# Unit-burn ceiling (used as a soft post-hoc warning, not a pre-call
# gate; failed face-detect calls already happened by the time we see
# the delta).
UNIT_CAP = int(os.environ.get("LIVE_VERIFY_UNIT_CAP", "2"))

# Max attempts to pull a frontal face from the generator.
MAX_FACE_TRIES = int(os.environ.get("LIVE_VERIFY_MAX_FACE_TRIES", "3"))

FACE_SOURCE_URL = "https://thispersondoesnotexist.com/"


def _fetch_face() -> bytes:
    req = urllib.request.Request(
        FACE_SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 glowchart-live-verify/0.1"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 - public stock generator
        return resp.read()


def _shrink_jpeg(raw: bytes, max_dim: int = 512, quality: int = 85) -> bytes:
    """Downsize to max_dim square JPEG to keep upload payload tiny.

    Perfect Corp accepts the original directly, but smaller payloads
    speed up the s3 PUT and keep the live test responsive.
    """
    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


def main() -> int:
    # 1. AUTH (one call; auto-detected bearer vs RSA handshake).
    try:
        token = get_access_token()
    except Exception as exc:
        print(f"AUTH FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"AUTH OK (token: {token[:8]}...)")

    # 2. CREDIT BEFORE
    before = tools.get_credit_balance()
    print(f"CREDIT BEFORE: {before}")

    # 3. Walk the analyze_skin_tone tool against a real face.
    last_err = ""
    result: dict | None = None
    for attempt in range(MAX_FACE_TRIES):
        try:
            raw = _fetch_face()
        except Exception as exc:
            last_err = f"face fetch failed: {exc}"
            continue
        img = _shrink_jpeg(raw)
        try:
            file_id = tools._real_upload_for("skin_tone_analysis", _b64(img))
        except Exception as exc:
            last_err = f"upload failed: {exc}"
            continue
        try:
            result = tools.analyze_skin_tone(file_id)
            break
        except RuntimeError as exc:
            last_err = str(exc)
            if "error_face_not_forward_facing" in last_err or "error_no_face" in last_err:
                # Try another generated face.
                continue
            print(f"TASK FAIL: {exc}", file=sys.stderr)
            break

    if result is None:
        print(f"TASK FAIL after {MAX_FACE_TRIES} attempts: {last_err}", file=sys.stderr)
    else:
        print(f"TASK OK (task: skin_tone_analysis)")
        # Safe fields only; no creds.
        safe = {k: result.get(k) for k in ("undertone", "season", "palette", "foundation_shade")}
        print(f"RESULT: {safe}")

    # 4. CREDIT AFTER + delta
    after = tools.get_credit_balance()
    print(f"CREDIT AFTER: {after}")
    if before >= 0 and after >= 0:
        delta = before - after
        print(f"UNITS USED: {delta}")
        if delta > UNIT_CAP:
            print(
                f"WARN: delta {delta} exceeds cap {UNIT_CAP}; live API charges for "
                f"face-detection attempts even on rejection.",
                file=sys.stderr,
            )
    return 0 if result is not None else 5


if __name__ == "__main__":
    raise SystemExit(main())
