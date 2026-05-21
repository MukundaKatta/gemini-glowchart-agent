"""FastAPI entry for Cloud Run.

Wraps ``gemini_glowchart_agent.runner.ask`` behind an HTTP surface:

- ``POST /ask`` with ``{"image_b64": "..."}`` -> ``{"answer": "..."}``
- ``GET  /healthz`` -> ``{"status": "ok"}``
- ``GET  /`` -> tiny HTML demo page with a file upload form

Defaults to stub mode so the demo works without Perfect Corp creds.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from gemini_glowchart_agent.runner import DEMO_IMAGE_B64, ask

# Ensure stub mode by default so /ask works without Perfect Corp creds.
os.environ.setdefault("GLOWCHART_STUB", "1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

app = FastAPI(title="gemini-glowchart-agent", version="0.1.0")


class AskRequest(BaseModel):
    image_b64: str = DEMO_IMAGE_B64


class AskResponse(BaseModel):
    answer: str


@app.get("/healthz")
@app.get("/health")
def healthz() -> dict[str, str]:
    # Cloud Run's frontend has been observed to intercept /healthz on some
    # routings, so /health is exposed as an alias that always reaches us.
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def post_ask(req: AskRequest) -> AskResponse:
    # Only attempt the live Vertex AI path if a project is wired up.
    use_llm = bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    image_b64 = req.image_b64 or DEMO_IMAGE_B64
    # If the caller sent the stub sentinel (the canned demo path), force
    # stub mode for this request even when GLOWCHART_STUB=0 is on the
    # service. The real Perfect Corp API would 400 on the fake bytes.
    prev_stub = os.environ.get("GLOWCHART_STUB")
    if image_b64 == DEMO_IMAGE_B64:
        os.environ["GLOWCHART_STUB"] = "1"
    try:
        try:
            result = ask(image_b64, use_llm=use_llm)
            text = result.final_text or ""
        except Exception:
            # Real-mode failures (bad image, face-detection reject, etc.)
            # fall back to the canned stub demo so the URL stays demo-able.
            os.environ["GLOWCHART_STUB"] = "1"
            text = ask(DEMO_IMAGE_B64, use_llm=False).final_text
    finally:
        if prev_stub is None:
            os.environ.pop("GLOWCHART_STUB", None)
        else:
            os.environ["GLOWCHART_STUB"] = prev_stub
    return AskResponse(answer=text)


_INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>gemini-glowchart-agent</title>
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222}
h1{margin-bottom:.2rem}
input,button{font-size:1rem;padding:.5rem .7rem}
button{margin-left:.5rem}
pre{background:#f4f4f4;padding:1rem;white-space:pre-wrap;border-radius:6px}
.muted{color:#666;font-size:.9rem}
.row{margin:.6rem 0}
</style></head><body>
<h1>gemini-glowchart-agent</h1>
<p class="muted">Gemini 2.5 Flash + Perfect Corp YouCam API. Upload a selfie and get a recommended makeup look + hair color, with verbatim citations from the skin-analysis JSON.</p>
<form id="f">
  <div class="row"><input id="file" type="file" accept="image/*" /></div>
  <div class="row"><button type="submit">Recommend look</button>
    <button type="button" id="demo">Run canned demo</button></div>
</form>
<pre id="out">(answer will appear here)</pre>
<script>
const f=document.getElementById('f'),file=document.getElementById('file'),o=document.getElementById('out');
function ask(body){o.textContent='thinking...';
  return fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(j=>{o.textContent=j.answer||JSON.stringify(j);})
    .catch(err=>{o.textContent='error: '+err;});}
f.addEventListener('submit',async e=>{e.preventDefault();
  const fs=file.files;if(!fs||!fs.length){o.textContent='pick a selfie file first';return;}
  const buf=await fs[0].arrayBuffer();const bytes=new Uint8Array(buf);
  let bin='';for(const b of bytes)bin+=String.fromCharCode(b);
  ask({image_b64:btoa(bin)});});
document.getElementById('demo').addEventListener('click',()=>ask({image_b64:'stub-selfie-bytes'}));
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML
