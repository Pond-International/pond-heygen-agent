"""Private HeyGen resource ownership, separate from the shared provider account."""

import hashlib
import json
import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")


class AccessDenied(ValueError):
    """A resource is not accessible to the current Pond identity."""


class ResourceAccess:
    def __init__(self, mapping, scope: tuple[str, str], *, shared=None):
        if len(scope) != 2 or any(not isinstance(s, str) or not s for s in scope):
            raise ValueError("Both Pond agent and user identity are required.")
        self.mapping = mapping
        self.owner = hashlib.sha256(json.dumps(list(scope)).encode()).hexdigest()
        self.shared = {kind: frozenset(ids) for kind, ids in (shared or {}).items()}

    @staticmethod
    def _valid(kind, identifier):
        return (
            isinstance(kind, str)
            and isinstance(identifier, str)
            and bool(_IDENTIFIER.fullmatch(kind))
            and bool(_IDENTIFIER.fullmatch(identifier))
        )

    @staticmethod
    def _key(kind, identifier):
        return f"resource:{kind}:{identifier}"

    async def allowed(self, kind: str, identifier: str, *, write=False) -> bool:
        if not self._valid(kind, identifier):
            return False
        if identifier in self.shared.get(kind, ()):
            return not write
        record = await self.mapping.get(self._key(kind, identifier))
        return bool(record and record.get("owner") == self.owner and not record.get("deleted"))

    async def require(self, kind: str, identifier: str, *, write=False):
        if not await self.allowed(kind, identifier, write=write):
            raise AccessDenied(
                "The referenced resource is not available to this caller or operation. "
                "Use your own resource or an operator-shared preset."
            )

    async def remember(self, kind: str, identifier: str, *, metadata=None):
        if not self._valid(kind, identifier):
            raise AccessDenied("The provider returned an invalid resource identifier.")
        if identifier in self.shared.get(kind, ()):
            return
        key = self._key(kind, identifier)
        existing = await self.mapping.get(key)
        if existing and existing.get("owner") != self.owner:
            raise AccessDenied("The resource is already assigned to another caller.")
        record = {"kind": kind, "id": identifier, "owner": self.owner, "metadata": metadata or {}}
        # Runtime mutations are serialized by the single Modal coordinator. Atomic
        # insert also prevents first ownership assignment racing another caller.
        if existing:
            await self.mapping.put(key, record)
        elif not await self.mapping.put(key, record, skip_if_exists=True):
            await self.require(kind, identifier, write=True)

    async def owned(self, kind: str) -> list[dict]:
        rows = []
        async for key, record in self.mapping.items():
            if (
                key.startswith(f"resource:{kind}:")
                and record.get("owner") == self.owner
                and not record.get("deleted")
            ):
                rows.append(record)
        return sorted(rows, key=lambda row: row["id"])

    async def forget(self, kind: str, identifier: str):
        await self.require(kind, identifier, write=True)
        # Keep ownership tombstones so a repeated/stale response cannot cause an
        # unrelated caller to claim a deleted provider resource's identifier.
        key = self._key(kind, identifier)
        previous = await self.mapping.get(key)
        await self.mapping.put(key, {**previous, "deleted": True})
