"""Durable records with atomic reservations and write-once terminal results."""

import copy
import hashlib
import json
import time
from datetime import UTC, datetime

from .video_usage import POLICY

RETENTION = 7 * 86400
TERMINAL = {"completed", "failed", "expired"}


def timestamp(now):
    return datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z")


class Conflict(ValueError):
    pass


class Retired(ValueError):
    pass


class MemoryMap:
    """Local adapter sharing the same atomic put contract as Modal Dict."""

    def __init__(self):
        self.data = {}

    async def get(self, key):
        return copy.deepcopy(self.data.get(key))

    async def put(self, key, value, *, skip_if_exists=False):
        if skip_if_exists and key in self.data:
            return False
        self.data[key] = copy.deepcopy(value)
        return True

    async def delete(self, key):
        self.data.pop(key, None)

    async def items(self):
        for item in list(self.data.items()):
            yield copy.deepcopy(item)


class TaskStore:
    def __init__(self, mapping, *, clock=time.time):
        self.map, self.clock = mapping, clock

    async def accept(self, request):
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task_id = "task_" + hashlib.sha256(request["run_id"].encode()).hexdigest()[:40]
        now = self.clock()
        task = {
            "task_id": task_id,
            "run_id": request["run_id"],
            "fingerprint": fingerprint,
            "request": request,
            "usage_policy": POLICY,
            "status": "queued",
            "created_at": now,
            "deadline": now + request["execution"]["deadline_ms"] / 1000,
            "updated_at": timestamp(now),
            "retention_until": now + RETENTION,
        }
        created = await self.map.put("task:" + task_id, task, skip_if_exists=True)
        existing = task if created else await self.map.get("task:" + task_id)
        if not existing or existing["fingerprint"] != fingerprint:
            raise Conflict("This run_id was already used for a different request.")
        effective = await self.get(task_id)
        if effective is None:
            raise Retired("This run_id is outside retention; it will not be generated again.")
        return effective, created

    async def get(self, task_id):
        record = await self.get_internal(task_id)
        if not record or self.clock() >= record["retention_until"]:
            return None
        return record

    async def get_internal(self, task_id):
        """Coordinator-only retained state; never use this for public task access.

        Active provider slots intentionally survive public retention so their known
        upstream jobs can be checked and reaped after a long period without traffic.
        """
        base = await self.map.get("task:" + task_id)
        if not base or base.get("retired"):
            return None
        terminal = await self.map.get("terminal:" + task_id) or {}
        progress = await self.map.get("progress:" + task_id) or {}
        return {**base, **progress, **terminal}

    async def claim(self, key, value=None):
        return await self.map.put(
            "claim:" + key, value or {"at": self.clock()}, skip_if_exists=True
        )

    async def progress(self, task_id, **changes):
        previous = await self.map.get("progress:" + task_id) or {}
        await self.map.put(
            "progress:" + task_id, {**previous, **changes, "updated_at": timestamp(self.clock())}
        )

    async def finish(
        self,
        task_id,
        status,
        *,
        artifact=None,
        output=None,
        artifacts=None,
        error=None,
        quantity=None,
    ):
        assert status in TERMINAL
        task = await self.map.get("task:" + task_id) or {}
        video_seconds = task.get("usage_policy") == POLICY
        if status != "completed":
            quantity = 0
        elif not video_seconds:
            quantity = 1
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Successful tasks must supply their measured integer usage.")
        now = self.clock()
        result = {
            "status": status,
            "updated_at": timestamp(now),
            "retention_until": now + RETENTION,
            "usage": {
                "unit_of_measurement": "other" if video_seconds else "result",
                "quantity": quantity,
            },
        }
        if status == "completed":
            if artifact is not None:
                artifacts = [artifact]
            if output is None:
                output = [
                    {"type": "artifact_ref", "artifact_id": item["id"]}
                    for item in (artifacts or [])
                ]
            result.update(output=output, artifacts=artifacts or [])
        else:
            result["error"] = error
        await self.map.put("terminal:" + task_id, result, skip_if_exists=True)

    async def reserve_slot(self, task_id):
        for index in range(2):
            key = f"slot:{index}"
            current = await self.map.get(key)
            if current and current["task_id"] == task_id:
                return True
            if await self.map.put(key, {"task_id": task_id}, skip_if_exists=True):
                return True
        return False

    async def release_slot(self, task_id):
        # Mutating coordinator runs with one Modal input globally; slot deletion
        # cannot race a new reservation. Atomic put still protects submissions.
        for index in range(2):
            key = f"slot:{index}"
            current = await self.map.get(key)
            if current and current["task_id"] == task_id:
                await self.map.delete(key)

    async def sweep(self):
        """Called by the single coordinator, on activity/manual command, never cron."""
        active = {s["task_id"] for i in range(2) if (s := await self.map.get(f"slot:{i}"))}
        removed = 0
        async for key, record in self.map.items():
            if not key.startswith("task:") or record.get("retired"):
                continue
            task_id = record["task_id"]
            terminal = await self.map.get("terminal:" + task_id) or {}
            expires = terminal.get("retention_until", record["retention_until"])
            if self.clock() < expires or task_id in active:
                continue
            # Keep a small tombstone: a very late matching retry must not incur a new charge.
            await self.map.put(key, {"fingerprint": record["fingerprint"], "retired": True})
            for prefix in ("progress:", "terminal:"):
                await self.map.delete(prefix + task_id)
            async for claim_key, _ in self.map.items():
                if claim_key.startswith("claim:") and task_id in claim_key:
                    await self.map.delete(claim_key)
            removed += 1
        return removed


def public_task(task):
    fields = {"task_id", "run_id", "status", "updated_at", "output", "artifacts", "usage", "error"}
    result = {k: v for k, v in task.items() if k in fields}
    if task["status"] not in TERMINAL:
        result["poll_after_ms"] = 20000
    return result
