"""CPU-only Modal wrapper: no GPU, cron, webhook, or render-wait loop."""

import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import httpx
import modal

from .api import create_api
from .artifacts import ARTIFACT_PATTERN, ArtifactSigner
from .duration_probe import measure_video_url
from .media import download_video
from .media_files import MAX_FILE_BYTES, SUPPORTED_MEDIA, fetch_media, inspect_media
from .provider import HeyGenClient
from .resource_access import ResourceAccess
from .service import STEP_TIMEOUT, TaskService
from .store import RETENTION, TERMINAL, TaskStore
from .tool_jobs import ToolJobs
from .tool_runtime import ToolRuntime
from .tool_service import NativeTaskService, provider_finished

APP_NAME = "pond-heygen-agent"
SECRET_NAME = APP_NAME + "-secrets"
ARTIFACT_ROOT = Path("/artifacts")
app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .uv_pip_install(
        "fastapi==0.116.1",
        "pydantic==2.11.7",
        "httpx==0.28.1",
        "pillow==12.3.0",
        "jsonschema==4.26.0",
    )
    .add_local_python_source("pond_heygen_agent")
    .add_local_dir(Path(__file__).parent / "data", "/root/pond_heygen_agent/data")
)
state = modal.Dict.from_name(APP_NAME + "-state", create_if_missing=True)
artifacts = modal.Volume.from_name(APP_NAME + "-artifacts", create_if_missing=True)
secret = modal.Secret.from_name(
    SECRET_NAME, required_keys=["POND_AGENT_ACCESS_KEY", "ARTIFACT_SIGNING_KEY"]
)


class ModalMap:
    def __init__(self, mapping):
        self.mapping = mapping

    async def get(self, key):
        return await self.mapping.get.aio(key, None)

    async def put(self, key, value, *, skip_if_exists=False):
        return await self.mapping.put.aio(key, value, skip_if_exists=skip_if_exists)

    async def delete(self, key):
        await self.mapping.pop.aio(key, None)

    async def items(self):
        async for item in self.mapping.items.aio():
            yield item


@app.cls(
    image=image,
    secrets=[secret],
    volumes={ARTIFACT_ROOT: artifacts},
    cpu=0.5,
    memory=512,
    min_containers=0,
    max_containers=1,
    scaledown_window=2,
    timeout=STEP_TIMEOUT,
)
@modal.concurrent(max_inputs=1)
class Coordinator:
    """Single writer keeps slot allocation and lifecycle mutations serialized."""

    @modal.enter()
    async def start(self):
        self.store = TaskStore(ModalMap(state))
        # Attachment transport pins IPs with per-request TLS SNI; do not reuse
        # an IP-keyed connection for another hostname hosted at that IP.
        self.http = httpx.AsyncClient(
            timeout=30, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
        )

    @modal.exit()
    async def close(self):
        await self.http.aclose()

    @modal.method()
    async def step(self, task_id: str):
        config = await state.get.aio("config", {})
        if not config.get("ready") or not os.environ.get("HEYGEN_API_KEY"):
            await self.store.finish(
                task_id,
                "failed",
                error={
                    "code": "temporarily_unavailable",
                    "message": "HeyGen generation is not configured.",
                },
            )
            return
        provider = HeyGenClient(os.environ["HEYGEN_API_KEY"], config["presets"], self.http)
        signer = ArtifactSigner(os.environ["ARTIFACT_SIGNING_KEY"])

        def native_jobs(task):
            request = task["request"]
            shared = dict(config.get("shared_resources", {}))
            shared["look"] = list(
                set(shared.get("look", []))
                | {p["id"] for p in config["presets"].get("avatars", [])}
            )
            shared["voice"] = list(
                set(shared.get("voice", []))
                | {p["id"] for p in config["presets"].get("voices", [])}
            )
            access = ResourceAccess(
                self.store.map, (request["agent_id"], request["user"]["id"]), shared=shared
            )
            return ToolJobs(
                ToolRuntime(
                    os.environ["HEYGEN_API_KEY"],
                    access,
                    client=self.http,
                    username=config.get("heygen_username"),
                    consent_groups=config.get("consent_approved_groups", []),
                )
            )

        async def reap():
            for index in range(2):
                slot = await self.store.map.get(f"slot:{index}")
                owner = await self.store.get_internal(slot["task_id"]) if slot else None
                if not owner or not owner.get("job"):
                    continue
                if owner["status"] not in TERMINAL and time.time() >= owner["deadline"]:
                    await self.store.finish(
                        owner["task_id"],
                        "expired",
                        error={
                            "code": "deadline_exceeded",
                            "message": "Provider processing outlasted this task.",
                        },
                    )
                    owner = await self.store.get_internal(owner["task_id"])
                if owner["status"] not in TERMINAL or time.time() < owner.get("next_check", 0):
                    continue
                await self.store.progress(owner["task_id"], next_check=time.time() + 20)
                try:
                    if owner["request"]["action_id"] in {
                        "generate_video",
                        "generate_presenter_video",
                    }:
                        status = await provider.status(owner["job"])
                        finished = status["status"] in {"completed", "failed"}
                    else:
                        status = await native_jobs(owner).poll(owner["job"])
                        finished = provider_finished(status)
                    if finished:
                        await self.store.release_slot(owner["task_id"])
                except Exception:
                    pass  # Retain capacity when provider completion is unknown.

        async def save_file(task_id, index, file, expires):
            artifact_id = "art_" + hashlib.sha256(f"{task_id}:{index}".encode()).hexdigest()[:40]
            if "content" in file:
                content = file["content"]
                mime = inspect_media(content, set(file["media_types"]))
            else:
                content, mime = await fetch_media(
                    file["url"], MAX_FILE_BYTES, set(file["media_types"]), self.http
                )
            suffix = SUPPORTED_MEDIA[mime]
            metadata = {
                "suffix": suffix,
                "media_type": mime,
                "name": f"output-{index + 1}{suffix}" if index else f"result{suffix}",
            }
            if mime == "application/json":
                metadata["name"] = "result.json"
            await artifacts.reload.aio()
            path = ARTIFACT_ROOT / (artifact_id + suffix)
            stage = path.with_suffix(".part")
            await asyncio.to_thread(stage.write_bytes, content)
            stage.replace(path)
            await artifacts.commit.aio()
            await self.store.map.put("artifact:" + artifact_id, metadata)
            return {
                "id": artifact_id,
                "type": "file",
                "_byte_count": len(content),
                "file": {
                    "name": metadata["name"],
                    "media_type": mime,
                    "url": signer.url(config["base_url"], artifact_id, expires),
                },
            }

        async def save(task_id, url, expires):
            artifact_id = "art_" + task_id.removeprefix("task_")
            path = ARTIFACT_ROOT / (artifact_id + ".mp4")
            await artifacts.reload.aio()
            metadata = await download_video(url, path)
            await artifacts.commit.aio()
            print(
                json.dumps(
                    {
                        "event": "artifact_saved",
                        "task_id": task_id,
                        "byte_count": metadata["byte_count"],
                    }
                )
            )
            return {
                "id": artifact_id,
                "type": "file",
                "file": {
                    "name": "video.mp4",
                    "media_type": "video/mp4",
                    "url": signer.url(config["base_url"], artifact_id, expires),
                },
            }

        task = await self.store.get(task_id)

        async def measure(url):
            return await measure_video_url(url, self.http)

        if task and task["request"]["action_id"] not in {
            "generate_video",
            "generate_presenter_video",
        }:
            await NativeTaskService(
                self.store, native_jobs(task), save_file, reap=reap, measure_video=measure
            ).step(task_id)
        else:
            service = TaskService(self.store, provider, save, measure_video=measure)
            service._reap_slots = reap
            await service.step(task_id)
        # Opportunistic maintenance only when normal work wakes the coordinator.
        last_cleanup = await state.get.aio("last_cleanup", 0)
        if time.time() - last_cleanup > 86400:
            await self._cleanup()

    async def _cleanup(self):
        removed_tasks = await self.store.sweep()
        await artifacts.reload.aio()
        removed_files = 0
        for path in ARTIFACT_ROOT.iterdir():
            if path.is_file() and ARTIFACT_PATTERN.fullmatch(path.stem):
                if time.time() - path.stat().st_mtime >= RETENTION:
                    path.unlink()
                    removed_files += 1
        if removed_files:
            await artifacts.commit.aio()
        await state.put.aio("last_cleanup", time.time())
        return {"expired_tasks_removed": removed_tasks, "expired_videos_removed": removed_files}

    @modal.method()
    async def cleanup(self):
        return await self._cleanup()

    @modal.method()
    async def release_uncertain_slot(self, task_id: str):
        """Operator-only recovery after checking the HeyGen dashboard. Never cancels jobs."""
        record = await self.store.get(task_id)
        if record and record["status"] not in {"failed", "expired"}:
            raise ValueError("Only failed/expired tasks can have a slot manually released.")
        await self.store.release_slot(task_id)
        return {"released_task": task_id}


@app.function(
    image=image,
    secrets=[secret],
    volumes={ARTIFACT_ROOT: artifacts},
    cpu=0.25,
    memory=256,
    min_containers=0,
    max_containers=2,
    scaledown_window=2,
    timeout=60,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    store = TaskStore(ModalMap(state))
    artifact_cache = Path("/tmp/heygen-artifact-cache")
    artifact_cache.mkdir(exist_ok=True)
    volume_lock = asyncio.Lock()

    async def config():
        return await state.get.aio("config", {})

    async def ready():
        return bool(os.environ.get("HEYGEN_API_KEY") and (await config()).get("ready"))

    async def presets():
        return (await config()).get("presets", {})

    async def dispatch(task_id):
        await Coordinator().step.spawn.aio(task_id)

    async def prepare_artifact(artifact_id):
        metadata = await store.map.get("artifact:" + artifact_id) or {"suffix": ".mp4"}
        cached = artifact_cache / (artifact_id + metadata["suffix"])
        if not cached.exists():
            async with volume_lock:
                await artifacts.reload.aio()
                source = ARTIFACT_ROOT / cached.name
                if source.is_file() and not cached.exists():
                    # FileResponse reads the local copy: no Volume files remain
                    # open when another concurrent request reloads the Volume.
                    staging = cached.with_suffix(".tmp")
                    await asyncio.to_thread(shutil.copyfile, source, staging)
                    staging.replace(cached)
        return cached

    return create_api(
        store,
        dispatch,
        os.environ["POND_AGENT_ACCESS_KEY"],
        ArtifactSigner(os.environ["ARTIFACT_SIGNING_KEY"]),
        ARTIFACT_ROOT,
        ready=ready,
        presets=presets,
        prepare_artifact=prepare_artifact,
    )
