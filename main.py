"""main.py — FastAPI app for Creator Income Copilot.

Wave 3 (agent G). Serves the static dashboard and exposes three API routes:

- ``GET /``                    -> static/index.html
- ``POST /api/analyze``        -> multipart 'file' (CSV) OR JSON {'csv_text': ...}
- ``GET /api/sample``          -> sample_data/payhip_sample.csv as attachment
- ``POST /api/sample/analyze`` -> full pipeline over the built-in sample

Run with: uvicorn main:app --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from core.parser import parse_csv
from core.report import build_analyze_response
from core.models import AnalyzeResponse

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SAMPLE_CSV = BASE_DIR / "sample_data" / "payhip_sample.csv"
SAMPLE_CSV_STORE2 = BASE_DIR / "sample_data" / "store2_gumroad.csv"

# Frontend store-switcher: store id -> sample CSV. store=1 is the original
# Payhip sample (default), store=2 the Gumroad-style PixelPerch sample.
SAMPLE_STORES = {
    1: SAMPLE_CSV,
    2: SAMPLE_CSV_STORE2,
}

# Dedicated-parser routing (core/parsers) is driven by header auto-detect;
# the store-2 headers ('Order Number' + 'Created At') accidentally match the
# lemon signature, so pin the built-in gumroad engine via source_hint.
STORE2_SOURCE_HINT = "gumroad"

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB cap
ALLOWED_SUFFIXES = {".csv", ".txt"}

# Multipart envelopes add boundary/header bytes on top of the file content,
# so the early Content-Length gate gets a small slack. The EXACT cap is still
# enforced by the chunked reads below, which count payload bytes only — the
# slack exists purely so a legitimately ~5MB file isn't rejected because its
# multipart wrapper pushed the HTTP body a few hundred bytes over.
_BODY_SLACK_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 64 * 1024


async def _read_stream_capped(stream, cap: int) -> bytes:
    """Read an async byte stream, rejecting it once it exceeds ``cap`` bytes.

    Reads in chunks and bails as soon as the running total passes the cap, so
    an oversized body is never fully buffered in memory (defends against
    memory-exhaustion DoS via huge uploads / JSON bodies).
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=400,
                detail=f"Body too large (max {cap} bytes)",
            )
        chunks.append(chunk)
    return b"".join(chunks)

app = FastAPI(
    title="Creator Income Copilot",
    description="Income intelligence for digital-product creators.",
    version="1.0.0",
)

# Open CORS — demo app, no auth, no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Security headers (defense-in-depth for the XSS surface)
# ---------------------------------------------------------------------------
# The dashboard renders CSV-derived strings with JS-side HTML escaping; this
# CSP is the second layer. 'unsafe-inline' in style-src is required because
# app.js sets inline style attributes (e.g. the share-bar width). script-src
# stays strict (no inline/unsafe-eval) — that is the layer that stops XSS.
_SECURITY_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'"
)


@app.middleware("http")
async def _security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _SECURITY_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


async def _extract_csv(request: Request) -> str:
    """Pull CSV text from a multipart 'file' upload or a JSON {'csv_text': ...} body.

    Raises HTTPException 422 when the input shape is wrong, 400 for
    disallowed extensions or oversized uploads.
    """
    content_type = request.headers.get("content-type", "").lower()

    # Early gate on the declared Content-Length: reject a giant body BEFORE
    # multipart/JSON parsing buffers it. The exact cap is still enforced by
    # the chunked reads below; the slack only absorbs multipart envelope
    # overhead. A malformed header is ignored (the chunked reads still cap).
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_UPLOAD_BYTES + _BODY_SLACK_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Request body too large (max {MAX_UPLOAD_BYTES} bytes)",
                )
        except ValueError:
            pass

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        # Duck-typed: form() yields UploadFile objects for file parts (the
        # class differs across fastapi/starlette versions), plain str for
        # non-file fields — only a real file part has .read().
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(
                status_code=422,
                detail="Missing required field 'file' (multipart CSV upload)",
            )
        filename = upload.filename or ""
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Only .csv or .txt uploads are accepted, "
                    f"got {suffix if suffix else '(no extension)'!r}"
                ),
            )
        # Chunked read with a running cap: an oversized upload is rejected as
        # soon as the cap is crossed instead of being buffered in full first.
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await upload.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Upload too large (max {MAX_UPLOAD_BYTES} bytes)",
                )
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    # Otherwise expect a JSON body with 'csv_text'. The body is streamed and
    # capped at MAX_UPLOAD_BYTES before parsing, so a huge JSON body can't be
    # fully buffered/parsed in memory (same DoS defence as the upload path).
    try:
        body = await _read_stream_capped(request.stream(), MAX_UPLOAD_BYTES)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - client disconnect / transport error
        raise HTTPException(
            status_code=422,
            detail="Expected multipart 'file' upload or JSON body with 'csv_text'",
        ) from None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="Expected multipart 'file' upload or JSON body with 'csv_text'",
        ) from None
    if not isinstance(payload, dict) or "csv_text" not in payload:
        raise HTTPException(
            status_code=422,
            detail="JSON body must contain a 'csv_text' field",
        )
    csv_text = payload.get("csv_text")
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise HTTPException(
            status_code=422,
            detail="'csv_text' must be a non-empty string",
        )
    # The 5MB cap must apply to the JSON body too, not just multipart
    # uploads — otherwise the size limit is trivially bypassed.
    if len(csv_text.encode("utf-8", errors="replace")) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'csv_text' too large: {len(csv_text)} chars "
                f"(max {MAX_UPLOAD_BYTES} bytes)"
            ),
        )
    return csv_text


def _analyze_csv_text(csv_text: str, source_hint: str | None = None) -> AnalyzeResponse:
    """Shared pipeline: parse -> report -> insights. 400 on unparseable CSV.

    source_hint is forwarded to parse_csv (None keeps auto-detection).
    """
    records, warnings = parse_csv(csv_text, source_hint=source_hint)
    if not records:
        detail = "; ".join(warnings) if warnings else "no parseable sales rows"
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse CSV: {detail}",
        )
    return build_analyze_response(records, warnings)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the single-page dashboard."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request) -> AnalyzeResponse:
    """Analyze an uploaded sales CSV (multipart 'file' or JSON 'csv_text')."""
    csv_text = await _extract_csv(request)
    return _analyze_csv_text(csv_text)


def _resolve_sample(store: int) -> Path:
    """Resolve a sample-store id to its CSV path; 404 on unknown ids."""
    path = SAMPLE_STORES.get(store)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown sample store {store!r} (valid stores: 1, 2)",
        )
    return path


@app.get("/api/sample")
async def sample_csv(store: int = 1) -> FileResponse:
    """Download a built-in sample CSV as an attachment.

    store=1 -> Payhip sample (default, backward compatible);
    store=2 -> Gumroad-style PixelPerch sample.
    """
    path = _resolve_sample(store)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sample CSV not found")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=path.name,
    )


@app.post("/api/sample/analyze", response_model=AnalyzeResponse)
async def sample_analyze(store: int = 1) -> AnalyzeResponse:
    """Run a built-in sample through the full pipeline.

    store=1 -> Payhip sample (default); store=2 -> Gumroad-style sample,
    parsed with the built-in gumroad engine (see STORE2_SOURCE_HINT).
    """
    path = _resolve_sample(store)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sample CSV not found")
    csv_text = path.read_text(encoding="utf-8")
    hint = STORE2_SOURCE_HINT if store == 2 else None
    return _analyze_csv_text(csv_text, source_hint=hint)
