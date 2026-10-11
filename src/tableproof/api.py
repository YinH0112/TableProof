"""Loopback-only API and offline frontend host."""

import copy
import hashlib
import math
import mimetypes
import os
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .export import export_xlsx
from .operations import apply_operation, record_change, snapshot_project
from .pdf import extract_table, parse_pdf, select_context
from .storage import Store, timestamp

# Windows registry MIME associations can otherwise classify .mjs as text/plain.
# Module workers and WebAssembly must work with nosniff enabled.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")


class TableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    columnLines: list[float] = Field(default_factory=list, max_length=200)
    supersedes: str | None = None


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    operation: dict


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def create_app(data_dir=None, frontend_dir=None):
    store = Store(data_dir)
    jobs = {}
    jobs_lock = threading.RLock()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tableproof-parse")

    @asynccontextmanager
    async def lifespan(app):
        yield
        with jobs_lock:
            for job in jobs.values():
                if job["status"] in {"pending", "running"}:
                    job["cancel"].set()
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="TableProof Research", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.jobs = jobs

    @app.middleware("http")
    async def loopback_guard(request: Request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "LOOPBACK_ONLY"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "ORIGIN_NOT_ALLOWED"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "ORIGIN_NOT_ALLOWED"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def read(project_id):
        try:
            return store.load(project_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "PROJECT_NOT_FOUND")

    def check_version(project, version):
        if version != project["version"]:
            raise HTTPException(409, {"code": "VERSION_CONFLICT", "version": project["version"]})

    def validate_box(box):
        if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            raise ValueError("INVALID_REGION")
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("INVALID_REGION")

    def submit_import(path, filename, project_id):
        job_id = uuid.uuid4().hex
        cancel = threading.Event()
        with jobs_lock:
            jobs[job_id] = {"status": "pending", "progress": 0, "cancel": cancel}

        def run():
            directory = store.directory(project_id)
            try:
                with jobs_lock:
                    jobs[job_id]["status"] = "running"
                file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

                def progress(done, total):
                    with jobs_lock:
                        jobs[job_id]["progress"] = round(done / max(total, 1) * 100)

                pages = parse_pdf(path, file_hash, progress_callback=progress, cancelled=cancel.is_set)
                now = timestamp()
                project = {"id": project_id, "name": Path(filename).stem, "fileHash": file_hash,
                           "filename": filename, "version": 1, "pages": pages, "tables": [],
                           "history": [], "undoStack": [], "redoStack": [],
                           "createdAt": now, "updatedAt": now}
                with jobs_lock, store.lock:
                    if cancel.is_set():
                        raise ValueError("CANCELLED")
                    store.save(project)
                    jobs[job_id].update(status="complete", progress=100, projectId=project_id)
            except Exception as error:
                with jobs_lock:
                    detail = str(error) if isinstance(error, ValueError) else "IMPORT_FAILED"
                    code = detail.split(":", 1)[0]
                    jobs[job_id].update(status="cancelled" if cancel.is_set() or code == "CANCELLED" else "failed", error=code, errorDetail=detail)
                # Only discard this uncommitted import, never a saved project.
                if not (directory / "project.json").exists():
                    path.unlink(missing_ok=True)
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

        executor.submit(run)
        return {"jobId": job_id}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/projects")
    def list_projects():
        return store.list()

    @app.post("/api/projects", status_code=202)
    async def import_pdf(file: UploadFile = File(...)):
        project_id = uuid.uuid4().hex
        directory = store.directory(project_id)
        directory.mkdir()
        path = directory / "source.pdf"
        size = 0
        try:
            with path.open("xb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise HTTPException(413, "PDF_TOO_LARGE")
                    target.write(chunk)
            if size == 0:
                raise HTTPException(422, "EMPTY_FILE")
            return submit_import(path, Path(file.filename or "paper.pdf").name, project_id)
        except Exception:
            path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        finally:
            await file.close()

    @app.get("/api/demo", status_code=202)
    def demo():
        sample = resource_root() / "samples" / "demo.pdf"
        if not sample.exists():
            raise HTTPException(404, "SAMPLE_NOT_INSTALLED")
        project_id = uuid.uuid4().hex
        directory = store.directory(project_id)
        directory.mkdir()
        target = directory / "source.pdf"
        target.write_bytes(sample.read_bytes())
        return submit_import(target, "TableProof demo.pdf", project_id)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id):
        with jobs_lock:
            if job_id not in jobs:
                raise HTTPException(404, "JOB_NOT_FOUND")
            return {k: v for k, v in jobs[job_id].items() if k != "cancel"}

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id):
        with jobs_lock:
            if job_id not in jobs:
                raise HTTPException(404, "JOB_NOT_FOUND")
            job = jobs[job_id]
            if job["status"] in {"pending", "running"}:
                job["cancel"].set()
            return {"status": job["status"]}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id):
        return read(project_id)

    @app.get("/api/projects/{project_id}/source")
    def source(project_id):
        read(project_id)
        return FileResponse(store.directory(project_id) / "source.pdf", media_type="application/pdf")

    @app.post("/api/projects/{project_id}/tables")
    def extract(project_id, body: TableRequest):
        with store.lock:
            project = read(project_id)
            check_version(project, body.version)
            try:
                validate_box(body.bbox)
                if not all(math.isfinite(v) for v in body.columnLines):
                    raise ValueError("INVALID_COLUMN_LINES")
                if body.supersedes and not any(t["id"] == body.supersedes for t in project["tables"]):
                    raise ValueError("TABLE_NOT_FOUND")
                table = extract_table(store.directory(project_id) / "source.pdf", project["pages"],
                                      project["fileHash"], body.page, body.bbox, body.columnLines)
                before = snapshot_project(project)
                table["supersedes"] = body.supersedes
                project["tables"].append(table)
                record_change(project, {"type": "extract", "tableId": table["id"], "supersedes": body.supersedes}, before)
                project["version"] += 1
                project["updatedAt"] = timestamp()
                store.save(project)
                return project
            except ValueError as error:
                raise HTTPException(422, str(error))

    @app.post("/api/projects/{project_id}/operations")
    def operate(project_id, body: OperationRequest):
        with store.lock:
            project = read(project_id)
            check_version(project, body.version)
            try:
                operation = copy.deepcopy(body.operation)
                if operation.get("type") == "context":
                    if "context" in operation:
                        raise ValueError("INVALID_OPERATION: select context from the original PDF")
                    validate_box(operation.get("bbox", []))
                    operation["context"] = select_context(project["pages"], project["fileHash"],
                                                          operation.get("page"), operation["bbox"], operation.get("kind"))
                updated = apply_operation(project, operation)
                updated["version"] = project["version"] + 1
                updated["updatedAt"] = timestamp()
                store.save(updated)
                return updated
            except (ValueError, KeyError, TypeError) as error:
                raise HTTPException(422, str(error) if isinstance(error, ValueError) else "INVALID_OPERATION")

    @app.get("/api/projects/{project_id}/export.xlsx")
    def export(project_id):
        with store.lock:
            project = read(project_id)
        try:
            content = export_xlsx(project)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="tableproof-research.xlsx"'})

    frontend = Path(frontend_dir) if frontend_dir else resource_root() / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/")
        def missing_frontend():
            return JSONResponse({"detail": "Build frontend first: see README.md"}, status_code=503)
    return app
