"""Short, durable native-tool steps; no worker waits while provider jobs run."""

import json

from .media import MediaError
from .media_files import MAX_BUNDLE_BYTES, MAX_OUTPUT_FILES
from .provider import ProviderError
from .resource_access import AccessDenied
from .service import POLL_INTERVAL, STEP_TIMEOUT, TaskService
from .store import RETENTION
from .tool_registry import operations


def provider_finished(state):
    """Only release render capacity after a verified provider terminal outcome."""
    return state["status"] == "completed" or (
        state["status"] == "failed"
        and state.get("error", {}).get("code")
        in {
            "provider_job_failed",
            "prerequisite_required",
            "provider_outcome_unverifiable",
        }
    )


class NativeTaskService(TaskService):
    def __init__(self, store, jobs, save_file, *, reap=None, **kwargs):
        super().__init__(store, jobs, save_file, **kwargs)
        self.jobs, self.save_file, self.reap = jobs, save_file, reap

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
                        "message": "Submission was interrupted. Check HeyGen before retrying; "
                        "it may have charged. No mutation was retried.",
                    },
                )
            return
        request = task["request"]
        mutation = operations()[request["action_id"]]["mutation"]
        if mutation:
            if self.reap:
                await self.reap()
            if not await self.store.reserve_slot(task_id):
                await self.store.progress(task_id, message="Waiting for a provider job slot.")
                return
        if not await self.store.claim("submit:" + task_id):
            return
        await self.store.progress(task_id, status="running", message="Executing the HeyGen action.")
        try:
            job = await self.jobs.start(request["action_id"], request["parameters"], task_id)
        except (ProviderError, AccessDenied, MediaError, ValueError) as error:
            if not getattr(error, "ambiguous", False):
                await self.store.release_slot(task_id)
            await self.store.finish(
                task_id,
                "failed",
                error={
                    "code": getattr(error, "code", "invalid_input"),
                    "message": str(error),
                },
            )
            return
        await self.store.progress(
            task_id, job=job, next_check=0, message="Waiting for the complete HeyGen result."
        )
        await self._poll(await self.store.get(task_id))

    async def _poll(self, task):
        now, task_id = self.clock(), task["task_id"]
        if task.get("completed_result"):
            await self._save(task)
            return
        if now < task.get("next_check", 0):
            return
        await self.store.progress(task_id, next_check=now + POLL_INTERVAL)
        try:
            state = await self.jobs.poll(task["job"])
        except ProviderError as error:
            await self.store.progress(
                task_id,
                next_check=now + max(POLL_INTERVAL, min(error.retry_after or 20, 300)),
                message="Waiting for a provider status update.",
            )
            return
        if state.get("job"):
            await self.store.progress(task_id, job=state["job"])
        if state["status"] == "failed":
            if provider_finished(state):
                await self.store.release_slot(task_id)
            await self.store.finish(
                task_id,
                "failed",
                error=state.get("error")
                or {
                    "code": "provider_failed",
                    "message": "HeyGen could not complete this action.",
                },
            )
        elif state["status"] == "completed":
            await self.store.release_slot(task_id)
            await self.store.progress(
                task_id,
                completed_result=state,
                saved_files=[],
                saved_bytes=0,
                message="Saving completed output files.",
            )
            await self._save(await self.store.get(task_id))

    async def _save(self, task):
        task_id = task["task_id"]
        state = task["completed_result"]
        quantity = await self._meter(task, state.get("video_usage", []))
        if quantity is None:
            return
        accepted = set(task["request"]["execution"]["accepted_output_modes"])
        files = [
            file for file in state.get("files", []) if set(file.get("media_types", ())) & accepted
        ]
        metadata = json.dumps(state.get("data", {}), ensure_ascii=False, allow_nan=False).encode()
        files.append(
            {"name": "result.json", "content": metadata, "media_types": ["application/json"]}
        )
        if len(files) > MAX_OUTPUT_FILES or len(metadata) > 2 * 1024**2:
            await self.store.finish(
                task_id,
                "failed",
                error={
                    "code": "output_limit",
                    "message": "The completed output exceeds the delivery limit.",
                },
            )
            return
        saved = task.get("saved_files", [])
        if len(saved) < len(files):
            file = dict(files[len(saved)])
            file["media_types"] = list(set(file["media_types"]) & accepted)
            try:
                artifact = await self.save_file(
                    task_id, len(saved), file, int(self.clock() + RETENTION)
                )
            except MediaError as error:
                attempts = task.get("save_attempts", 0) + 1
                if attempts >= 3:
                    await self.store.finish(
                        task_id,
                        "failed",
                        error={
                            "code": "artifact_unavailable",
                            "message": str(error),
                        },
                    )
                else:
                    await self.store.progress(
                        task_id,
                        save_attempts=attempts,
                        message="Retrying completed-file delivery; no new generation.",
                    )
                return
            total = task.get("saved_bytes", 0) + artifact.pop("_byte_count", 0)
            if total > MAX_BUNDLE_BYTES:
                await self.store.finish(
                    task_id,
                    "failed",
                    error={
                        "code": "output_limit",
                        "message": "Completed files exceed the 200 MiB bundle limit.",
                    },
                )
                return
            saved = [*saved, artifact]
            await self.store.progress(
                task_id, saved_files=saved, saved_bytes=total, save_attempts=0
            )
        if len(saved) == len(files):
            if self.clock() >= task["deadline"]:
                await self.store.finish(
                    task_id,
                    "expired",
                    error={
                        "code": "deadline_exceeded",
                        "message": "The deadline expired during file delivery.",
                    },
                )
            else:
                await self.store.finish(task_id, "completed", artifacts=saved, quantity=quantity)
