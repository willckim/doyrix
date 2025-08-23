# app.py
# --- path shim: make ./ and ./utils importable ---
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
UTILS = ROOT / "utils"
for p in (ROOT, UTILS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
# --------------------------------------------------
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path as _Path
from uuid import uuid4
import os
import logging

from utils.parse_pdf import parse_pdf_with_citations
from report import build_analyst_report, export_report  # report-only

# --- logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("doyrix")

app = FastAPI(title="Doyrix API", version="0.2.0")

# CORS origins (env override)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = _Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "50"))

class UploadResponse(BaseModel):
    document_id: str
    status: str

class StatusResponse(BaseModel):
    document_id: str
    status: str
    error_msg: str | None = None

# --- Report models (report-only) ---
class ReportRequest(BaseModel):
    document_id: str

class ReportResponse(BaseModel):
    html: str
    metadata: dict

class ReportExportRequest(BaseModel):
    document_id: str
    fmt: str  # "pdf" or "docx"

# In-memory stores
DOCS: dict[str, dict] = {}
RESULTS: dict[str, dict] = {}

def _lazy_load(doc_id: str) -> dict | None:
    """If RESULTS lost state, re-open from disk and re-parse to fulfill later calls."""
    d = DOCS.get(doc_id)
    if not d:
        return None
    try:
        path = d.get("path")
        if path and os.path.exists(path):
            log.info(f"[{doc_id}] lazy re-parse from disk: {path}")
            parsed = parse_pdf_with_citations(str(path))
            RESULTS[doc_id] = parsed
            DOCS[doc_id]["status"] = "ready"
            return parsed
    except Exception as e:
        log.exception(f"[{doc_id}] lazy re-parse failed")
        DOCS[doc_id]["status"] = "error"; DOCS[doc_id]["error_msg"] = str(e)
    return None

@app.get("/")
def health():
    return {"ok": True, "name": "doyrix-api", "version": app.version}

@app.get("/version")
def version():
    return {"name": "doyrix-api", "version": app.version}

@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...), doc_type: str = Form("Other")):
    if not file or not file.filename:
        raise HTTPException(400, "No file uploaded")
    ext = _Path(file.filename).suffix.lower()
    if ext not in [".pdf", ".txt", ".docx"]:
        raise HTTPException(415, "Supported: PDF/TXT/DOCX only")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(413, f"File too large ({size_mb:.1f} MB). Max {MAX_UPLOAD_MB:.0f} MB.")

    doc_id = str(uuid4())
    save_path = DATA_DIR / f"{doc_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(content)

    DOCS[doc_id] = {
        "file_name": file.filename,
        "path": str(save_path),
        "doc_type": doc_type,
        "status": "parsing",
        "error_msg": None,
    }

    log.info(f"[{doc_id}] saved {file.filename} ({size_mb:.2f} MB) -> {save_path}")

    try:
        parsed = parse_pdf_with_citations(str(save_path))
        RESULTS[doc_id] = parsed
        DOCS[doc_id]["status"] = "ready"
        log.info(f"[{doc_id}] parsing complete: pages={parsed.get('doc_meta',{}).get('pages')}, anchors={parsed.get('doc_meta',{}).get('anchors_found')}")
    except Exception as e:
        DOCS[doc_id]["status"] = "error"
        DOCS[doc_id]["error_msg"] = str(e)
        log.exception(f"[{doc_id}] parsing failed")
        raise HTTPException(500, f"Parsing failed: {e}")

    return {"document_id": doc_id, "status": DOCS[doc_id]["status"]}

@app.get("/status/{document_id}", response_model=StatusResponse)
async def status(document_id: str):
    d = DOCS.get(document_id)
    if not d:
        raise HTTPException(404, "Unknown document id")
    return {"document_id": document_id, "status": d["status"], "error_msg": d["error_msg"]}

# --- Analyst Report (multi-section/multi-page) ---
@app.post("/generate-report", response_model=ReportResponse)
async def generate_report(req: ReportRequest):
    parsed = RESULTS.get(req.document_id) or _lazy_load(req.document_id)
    if not parsed:
        raise HTTPException(404, "No parsed result for document")
    html, metadata = build_analyst_report(parsed)
    return {"html": html, "metadata": metadata}

@app.post("/export-report")
def export_report_endpoint(req: ReportExportRequest):
    parsed = RESULTS.get(req.document_id) or _lazy_load(req.document_id)
    if not parsed:
        raise HTTPException(404, "No parsed result for document")
    fmt = req.fmt.lower()
    if fmt not in {"pdf", "docx"}:
        raise HTTPException(400, "fmt must be 'pdf' or 'docx'")
    out_path = DATA_DIR / f"{req.document_id}_report.{fmt}"
    try:
        built_path = export_report(parsed, out_path, fmt)
    except Exception as e:
        log.exception("export_report failed")
        raise HTTPException(500, f"Report build failed: {e}")
    media_type = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path=str(built_path), filename=built_path.name, media_type=media_type)
