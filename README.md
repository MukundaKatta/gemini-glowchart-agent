# gemini-glowchart-agent

A beauty-advisor agent built on **Google Cloud Agent Builder (ADK)**,
**Vertex AI Gemini 2.5 Flash**, and **Perfect Corp's YouCam API**.

You upload a selfie. The agent calls Perfect Corp's Skin Analysis and
Skin Tone endpoints in parallel, reads the structured JSON, picks a
makeup look + hair color that fits, and triggers the virtual try-on
endpoints. Every attribute name, score, undertone, season, and
foundation shade in the final answer is copied byte-for-byte from the
Perfect Corp API response. No paraphrasing.

Built for the DevNetwork [AI + ML] Hackathon 2026, Perfect Corp
Challenge track.

## What it does

The agent has five tools shaped like the Perfect Corp YouCam API:

1. `upload_image(image_b64)` returns `{file_id, expires_at}`.
2. `analyze_skin(file_id, mode="SD")` returns 15 attributes (name +
   score + severity), an `overall_score`, an `ai_skin_age`, and a
   `mask_urls` map.
3. `analyze_skin_tone(file_id)` returns `{undertone, season, palette,
   foundation_shade}`.
4. `apply_makeup(file_id, look)` triggers the makeup virtual try-on with
   `{lipstick, eyeshadow, blush}` hex codes; returns a `result_url`.
5. `apply_hair_color(file_id, color_hex)` triggers the hair-color virtual
   try-on; returns a `result_url`.

The final answer is structured into five labeled sections:
**ATTRIBUTES**, **UNDERTONE**, **RECOMMENDED_LOOK**, **EVIDENCE**,
**CONFIDENCE**. Every attribute name, score, undertone, and hex code in
those sections is byte-for-byte from the API JSON. EVIDENCE quotes are
unedited. CONFIDENCE is tied to `overall_score`: if any required field
is missing or `overall_score` is below 50, CONFIDENCE drops to `low`.

## Demo scenario

Upload a selfie (the canned one is a placeholder). The agent:
1. Uploads the image and gets `file_id=file_demo_20260521_abc123`.
2. Runs `analyze_skin` and `analyze_skin_tone` in parallel.
3. Picks the top 3 concerns: `skin_type` (72), `oiliness` (70), `pore` (65).
4. Reads `undertone=warm, season=autumn, foundation_shade=warm-medium-3`.
5. Picks a warm earth-tone matte look from the autumn palette
   (`#C97D5D`, `#8B4A3B`, `#D4A574`) plus auburn hair (`#A0623E`).
6. Triggers `apply_makeup` and `apply_hair_color`.
7. Renders the five sections with verbatim citations.

## Quickstart (stub mode, zero cloud setup)

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run the deterministic smoke (no LLM call, no Perfect Corp creds needed)
.venv/bin/python smoke.py

# Run the test suite
.venv/bin/pytest
```

Stub mode is the default. The five tools return hand-written fixtures
shaped exactly like Perfect Corp's API responses, so agent code is
identical between stub and real mode.

## Real mode (Perfect Corp YouCam API + Vertex AI Gemini)

Set these env vars:

```sh
# Switch tools off stub
export GLOWCHART_STUB=0

# Perfect Corp YouCam
export PERFECT_CORP_API_KEY="<your-bearer-token>"
# (optional) override host if your tenant is on a non-default region
# export GLOWCHART_API_HOST="https://yce-api-01.makeupar.com"

# Vertex AI Gemini
export GOOGLE_CLOUD_PROJECT="my-gcp-project"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI=true
```

Then drive the full LLM path:

```python
from gemini_glowchart_agent.runner import ask
with open("selfie.jpg", "rb") as fh:
    import base64
    b64 = base64.b64encode(fh.read()).decode()
print(ask(b64, use_llm=True).final_text)
```

## Environment variables

| Variable                   | Purpose                                  | Default |
| -------------------------- | ---------------------------------------- | ------- |
| `GLOWCHART_STUB`           | `1` = fixtures, `0` = real Perfect Corp  | `1`     |
| `PERFECT_CORP_API_KEY`     | Bearer token (real mode only)            | unset   |
| `GLOWCHART_API_HOST`       | Override Perfect Corp API host           | yce-api-01 |
| `GOOGLE_CLOUD_PROJECT`     | Vertex AI project (LLM path only)        | unset   |
| `GOOGLE_CLOUD_LOCATION`    | Vertex AI region                         | unset   |
| `GOOGLE_GENAI_USE_VERTEXAI`| `true` to use Vertex AI Gemini           | unset   |

## System prompt contract

Five sections, in order. Pulled from
`src/gemini_glowchart_agent/prompt.py`.

- **ATTRIBUTES**: bulleted list of the top 3 skin concerns,
  `- <name>: <score>`, both copied verbatim from `analyze_skin`.
- **UNDERTONE**: one line, `undertone=<v>, season=<v>,
  foundation_shade=<v>`, all three copied verbatim from
  `analyze_skin_tone`.
- **RECOMMENDED_LOOK**: a one-line JSON object with `lipstick`,
  `eyeshadow`, `blush`, `hair_color` hex codes (from the season
  palette), followed by a one-sentence reason citing the attribute names
  + season.
- **EVIDENCE**: 2-4 byte-for-byte quotes from the API JSON, each tagged
  with `analyze_skin` or `analyze_skin_tone`.
- **CONFIDENCE**: `high` / `medium` / `low` tied to `overall_score`.

## Repo layout

```
src/gemini_glowchart_agent/
  __init__.py
  agent.py     # build_agent() -> ADK LlmAgent with five tools
  prompt.py    # 5-section system prompt
  runner.py    # ask() with use_llm toggle, parallel skin+tone batcher
  stubs.py     # hand-written fixtures shaped like Perfect Corp YouCam
  tools.py     # 5 FunctionTools: upload_image, analyze_skin, ...

tests/
  conftest.py
  test_tools.py
  test_agent.py

smoke.py        # end-to-end stub-mode smoke test
main.py         # FastAPI HTTP entry (POST /ask, GET /, GET /health)
pyproject.toml
LICENSE         # MIT
```

## Cloud Run deploy (TODO, stage 2)

The hackathon judging requires a public Cloud Run URL. That deploy step
is intentionally left for stage 2. Sketch:

```sh
# (later) build container and push
gcloud run deploy gemini-glowchart-agent \
  --source . \
  --region us-central1 \
  --set-env-vars GLOWCHART_STUB=0,GOOGLE_GENAI_USE_VERTEXAI=true \
  --set-secrets PERFECT_CORP_API_KEY=perfect-corp-key:latest
```

## License

MIT, see `LICENSE`.
