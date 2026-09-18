"""Pond discovery, short asynchronous requests, and signed MP4 delivery."""

import hashlib
import inspect
import json
import logging
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .artifacts import ARTIFACT_PATTERN
from .media_files import SUPPORTED_MEDIA
from .protocol import MAX_REQUEST_BYTES, InputError, manifest, normalize
from .store import TERMINAL, Conflict, Retired, public_task

LOGGER = logging.getLogger(__name__)


def fail(status, code, message):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def create_api(
    store,
    dispatch,
    access_key,
    signer,
    artifact_root: Path,
    *,
    ready=True,
    presets=None,
    prepare_artifact=None,
):
    if not access_key:
        raise ValueError("POND_AGENT_ACCESS_KEY is required")
    app = FastAPI(title="Pond HeyGen Agent", docs_url=None, redoc_url=None, openapi_url=None)

    async def value(item):
        result = item() if callable(item) else item
        return await result if inspect.isawaitable(result) else result

    def authenticate(request):
        provided = request.headers.get("authorization", "")
        if not secrets.compare_digest(provided.encode(), f"Bearer {access_key}".encode()):
            fail(401, "unauthorized", "The Access Key is missing or invalid.")
        version = request.headers.get("x-agent-protocol-version", "")
        if not re.fullmatch(r"\d+\.\d+", version):
            fail(400, "invalid_request", "The protocol version must be Major.Minor.")
        if version != "1.0":
            fail(400, "unsupported_protocol_version", "Only Pond Protocol 1.0 is supported.")

    @app.exception_handler(HTTPException)
    async def expected_error(request, error):
        content = {"error": error.detail}
        if getattr(request.state, "run_id", None):
            content["run_id"] = request.state.run_id
        return JSONResponse(content, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        LOGGER.error("api_failed type=%s", type(error).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "The request could not be processed."}},
            status_code=500,
        )

    @app.get("/manifest")
    async def discovery():
        return manifest(await value(presets) or {})

    @app.get("/health")
    async def health():
        # Never invokes HeyGen or starts a generation job.
        configured = bool(await value(ready))
        return {
            "status": "ok",
            "agent_version": __version__,
            "protocol_version": "1.0",
            "generation_ready": configured,
            "reason": "ready" if configured else "heygen_not_configured",
        }

    async def schedule(task):
        if task["status"] in TERMINAL:
            return
        if store.clock() >= task["deadline"]:
            await store.finish(
                task["task_id"],
                "expired",
                error={
                    "code": "deadline_exceeded",
                    "message": "The task deadline expired. HeyGen may still charge "
                    "for a previously submitted generation.",
                },
            )
            return
        bucket = int(store.clock() // 20)
        marker = f"dispatch:{task['task_id']}:{bucket}"
        if not await store.claim(marker):
            return
        try:
            await dispatch(task["task_id"])
        except Exception as error:
            # A later poll can safely re-dispatch a short coordinator step; the
            # durable submission marker prevents creating another paid video.
            LOGGER.warning("dispatch_failed task=%s type=%s", task["task_id"], type(error).__name__)

    @app.post("/runs")
    async def runs(request: Request):
        authenticate(request)
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            fail(415, "unsupported_content_type", "Send application/json.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                fail(400, "invalid_request", "The request exceeds the 64 KiB limit.")
        try:
            raw = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            fail(400, "invalid_request", "Send a valid JSON request.")
        try:
            run = normalize(raw)
        except InputError as error:
            fail(error.status, error.code, error.message)
        request.state.run_id = run["run_id"]
        if request.headers.get("idempotency-key") != run["run_id"]:
            fail(400, "invalid_request", "Idempotency-Key must match run_id.")
        task_id = "task_" + hashlib.sha256(run["run_id"].encode()).hexdigest()[:40]
        existing = await store.map.get("task:" + task_id)
        if not existing and not await value(ready):
            fail(503, "temporarily_unavailable", "HeyGen generation is not configured yet.")
        try:
            task, _ = await store.accept(run)
        except Conflict as error:
            fail(409, "idempotency_conflict", str(error))
        except Retired as error:
            fail(410, "task_not_found", str(error))
        await schedule(task)
        result = public_task(await store.get(task["task_id"]))
        status = 200 if result["status"] in TERMINAL else 202
        if status == 200:
            # Terminal /runs responses use the run schema, not the task schema.
            result.pop("task_id", None)
            result.pop("updated_at", None)
            if result["status"] == "expired":
                result["status"] = "failed"
        return JSONResponse(result, status_code=status)

    @app.get("/tasks/{task_id}")
    async def tasks(task_id: str, request: Request):
        authenticate(request)
        if not re.fullmatch(r"task_[0-9a-f]{40}", task_id):
            fail(404, "task_not_found", "The task was not found or has expired.")
        task = await store.get(task_id)
        if task is None:
            fail(404, "task_not_found", "The task was not found or has expired.")
        await schedule(task)
        return public_task(await store.get(task_id))

    @app.api_route("/artifacts/{artifact_id}", methods=["GET", "HEAD"])
    async def artifact(artifact_id: str, expires: str = "", signature: str = ""):
        try:
            signer.verify(artifact_id, expires, signature)
        except ValueError:
            fail(403, "artifact_unavailable", "This video link is invalid or expired.")
        if not ARTIFACT_PATTERN.fullmatch(artifact_id):
            fail(404, "artifact_unavailable", "The video was not found.")
        metadata = await store.map.get("artifact:" + artifact_id) or {
            "suffix": ".mp4",
            "media_type": "video/mp4",
            "name": "video.mp4",
        }
        if metadata.get("suffix") != SUPPORTED_MEDIA.get(metadata.get("media_type")):
            fail(404, "artifact_unavailable", "The file metadata is invalid.")
        path = (
            await prepare_artifact(artifact_id)
            if prepare_artifact
            else artifact_root / (artifact_id + metadata["suffix"])
        )
        if not path.is_file():
            fail(404, "artifact_unavailable", "The video was not found or has expired.")
        return FileResponse(
            path,
            media_type=metadata["media_type"],
            filename=metadata["name"],
            content_disposition_type="inline"
            if metadata["media_type"].startswith(("video/", "audio/"))
            else "attachment",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    return app
