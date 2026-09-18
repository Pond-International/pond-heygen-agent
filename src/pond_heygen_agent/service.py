"""Short, request-driven task steps; no worker sleeps while HeyGen renders."""

import asyncio
import logging
import time

from .store import RETENTION, TERMINAL
from .video_usage import POLICY, UsageError, resolve_usage

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL = 20
STEP_TIMEOUT = 180


class TaskService:
    def __init__(self, store, provider, save_artifact, *, clock=time.time, measure_video=None):
        self.store, self.provider, self.save_artifact = store, provider, save_artifact
        self.clock = clock
        self.measure_video = measure_video
        self.lock = asyncio.Lock()

    async def _meter(self, task, records):
        if task.get("usage_policy") != POLICY:
            return 1  # Finish preserves the old policy for pre-upgrade tasks.
        if "measured_quantity" in task:
            return task["measured_quantity"]
        measured = dict(task.get("measured_durations", {}))

        async def measure(url):
            if url not in measured:
                if self.measure_video is None:
                    raise UsageError("No actual duration is available for the completed video.")
                measured[url] = str(await self.measure_video(url))
                await self.store.progress(task["task_id"], measured_durations=measured)
            return measured[url]

        try:
            quantity = await resolve_usage(records, measure)
        except UsageError as error:
            await self.store.finish(
                task["task_id"],
                "failed",
                error={
                    "code": "usage_unavailable",
                    "message": str(error)
                    + " No new generation was submitted; HeyGen may still charge.",
                },
            )
            return None
        await self.store.progress(task["task_id"], measured_quantity=quantity)
        return quantity

    async def step(self, task_id):
        # Modal's coordinator is max_containers=1/max_inputs=1 across all steps.
        # This lock provides equivalent semantics to embedded/local callers.
        async with self.lock:
            task = await self.store.get(task_id)
            if not task or task["status"] in TERMINAL:
                return
            if self.clock() >= task["deadline"]:
                await self.store.finish(
                    task_id,
                    "expired",
                    error={
                        "code": "deadline_exceeded",
                        "message": "The video deadline expired. "
                        "HeyGen may still finish and charge; no new video was started.",
                    },
                )
                return
            try:
                async with asyncio.timeout(min(STEP_TIMEOUT - 10, task["deadline"] - self.clock())):
                    if task.get("job"):
                        await self._poll(task)
                    else:
                        await self._submit(task)
            except TimeoutError:
                # Do not remove the submission marker: the next step can distinguish
                # an interrupted paid request from a never-started queued task.
                LOGGER.warning("step_timeout task=%s", task_id)
            except Exception as error:
                LOGGER.warning("step_failed task=%s type=%s", task_id, type(error).__name__)
                await self.store.finish(
                    task_id,
                    "failed",
                    error={
                        "code": "internal_error",
                        "message": "The video task could not be processed. "
                        "It was not automatically regenerated.",
                    },
                )

    async def _submit(self, task):
        task_id = task["task_id"]
        previous = await self.store.map.get("claim:submit:" + task_id)
        if previous:
            if self.clock() - previous["at"] >= STEP_TIMEOUT:
                await self.store.finish(
                    task_id,
                    "failed",
                    error={
                        "code": "submission_uncertain",
                        "message": "The generation submission was "
                        "interrupted. Check HeyGen before another request; it may have charged.",
                    },
                )
            return
        await self._reap_slots()
        if not await self.store.reserve_slot(task_id):
            await self.store.progress(task_id, message="Waiting for a generation slot.")
            return
        if not await self.store.claim("submit:" + task_id):
            return
        await self.store.progress(task_id, status="running", message="Submitting to HeyGen.")
        request = task["request"]
        parameters = dict(request["parameters"])
        parts = request["messages"][0]["parts"]
        parameters["_instruction"] = "\n".join(p["text"] for p in parts if p["type"] == "text")
        files = [p["file"] for p in parts if p["type"] == "file"]
        try:
            job = await self.provider.create(request["action_id"], parameters, files, task_id)
        except Exception as error:
            from .provider import ProviderError

            if not isinstance(error, ProviderError):
                raise
            if not error.ambiguous:
                await self.store.release_slot(task_id)
            await self.store.finish(
                task_id, "failed", error={"code": error.code, "message": error.message}
            )
            return
        await self.store.progress(
            task_id,
            job=job,
            next_check=self.clock() + POLL_INTERVAL,
            message="HeyGen is generating the video.",
        )

    async def _poll(self, task):
        now, task_id = self.clock(), task["task_id"]
        if now < task.get("next_check", 0):
            return
        await self.store.progress(task_id, next_check=now + POLL_INTERVAL)
        try:
            state = await self.provider.status(task["job"])
        except Exception as error:
            from .provider import ProviderError

            if not isinstance(error, ProviderError):
                raise
            await self.store.progress(
                task_id,
                next_check=now + max(POLL_INTERVAL, min(error.retry_after or POLL_INTERVAL, 300)),
                message="Waiting for a status update from HeyGen.",
            )
            return
        if state["status"] == "failed":
            await self.store.release_slot(task_id)
            await self.store.finish(
                task_id,
                "failed",
                error={
                    "code": "generation_failed",
                    "message": "HeyGen could not generate the video.",
                },
            )
        elif state["status"] == "completed":
            await self.store.release_slot(task_id)
            quantity = await self._meter(
                task,
                [
                    {
                        "key": "video:" + task["job"]["id"],
                        "duration": state.get("duration"),
                        "url": state["video_url"],
                    }
                ],
            )
            if quantity is None:
                return
            await self.store.progress(task_id, message="Saving the finished MP4.")
            artifact = await self.save_artifact(task_id, state["video_url"], int(now + RETENTION))
            if self.clock() >= task["deadline"]:
                await self.store.finish(
                    task_id,
                    "expired",
                    error={
                        "code": "deadline_exceeded",
                        "message": "The deadline expired while saving the video.",
                    },
                )
            else:
                await self.store.finish(task_id, "completed", artifact=artifact, quantity=quantity)

    async def _reap_slots(self):
        # A Pond timeout does not cancel HeyGen. Only free abandoned slots when
        # the provider confirms completion/failure; ambiguous submissions stay held.
        for index in range(2):
            slot = await self.store.map.get(f"slot:{index}")
            if not slot:
                continue
            owner = await self.store.get_internal(slot["task_id"])
            if owner and owner["status"] not in TERMINAL and self.clock() >= owner["deadline"]:
                await self.store.finish(
                    owner["task_id"],
                    "expired",
                    error={
                        "code": "deadline_exceeded",
                        "message": "The deadline expired; HeyGen may still charge for generation.",
                    },
                )
                owner = await self.store.get_internal(owner["task_id"])
            if not owner or not owner.get("job") or owner["status"] not in TERMINAL:
                continue
            if self.clock() < owner.get("next_check", 0):
                continue
            await self.store.progress(owner["task_id"], next_check=self.clock() + POLL_INTERVAL)
            try:
                state = await self.provider.status(owner["job"])
            except Exception:
                continue
            if state["status"] in {"completed", "failed"}:
                await self.store.release_slot(owner["task_id"])
