"""Explicit operator setup/recovery commands; never prints credentials."""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx
import modal
from dotenv import dotenv_values, set_key

from .provider import HeyGenClient, ProviderError

APP_NAME = "pond-heygen-agent"


def setup_credentials(path: Path, allow_unconfigured: bool):
    values = {**dotenv_values(path)} if path.exists() else {}
    for key in ("HEYGEN_API_KEY", "POND_AGENT_ACCESS_KEY", "ARTIFACT_SIGNING_KEY"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    if not values.get("HEYGEN_API_KEY") and not allow_unconfigured:
        raise ValueError(
            "Set HEYGEN_API_KEY in .env, or use --allow-unconfigured for a disabled deployment."
        )
    # Generated credential material is a private operator artifact, never repo content.
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    path.chmod(0o600)
    for key in ("POND_AGENT_ACCESS_KEY", "ARTIFACT_SIGNING_KEY"):
        values[key] = values.get(key) or secrets.token_urlsafe(32)
        set_key(str(path), key, values[key])
    if values.get("HEYGEN_API_KEY"):
        set_key(str(path), "HEYGEN_API_KEY", values["HEYGEN_API_KEY"])
    subprocess.run(
        [
            sys.executable,
            "-m",
            "modal",
            "secret",
            "create",
            APP_NAME + "-secrets",
            "--from-dotenv",
            str(path),
            "--force",
        ],
        check=True,
    )
    print(
        "Dedicated Modal secret updated. Local credentials are in the protected, gitignored .env."
    )


async def configure(path, base_url):
    if not base_url.startswith("https://") or not base_url.rstrip("/").endswith(".modal.run"):
        raise ValueError(
            "Use the actual HTTPS Modal base URL returned by deployment, without a path."
        )
    values = {**dotenv_values(path), **os.environ}
    state = modal.Dict.from_name(APP_NAME + "-state", create_if_missing=True)
    config = {"base_url": base_url.rstrip("/"), "ready": False, "presets": {}}
    if values.get("HEYGEN_API_KEY"):
        async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
            provider = HeyGenClient(values["HEYGEN_API_KEY"], client=http)
            await provider._request("GET", "/v3/users/me")
            presets = await provider.discover_presets()
            # Optional operator-owned catalog explicitly opts private IDs into sharing.
            override = values.get("HEYGEN_PRESETS_JSON")
            if override:
                presets = json.loads(override)
                if not isinstance(presets, dict):
                    raise ValueError("HEYGEN_PRESETS_JSON must be an object.")
                for avatar in presets.get("avatars", []):
                    data = await provider._request("GET", "/v3/avatars/looks/" + avatar["id"])
                    if data.get("status") not in (None, "completed") or "avatar_iv" not in (
                        data.get("supported_api_engines") or []
                    ):
                        raise ValueError("An enabled avatar is not ready for Avatar IV.")
                    avatar["name"] = data["name"]
                for voice in presets.get("voices", []):
                    data = await provider._request("GET", "/v3/voices/" + voice["id"])
                    voice.update(name=data["name"], language=data["language"])
            if not presets.get("avatars") or not presets.get("voices"):
                raise ValueError(
                    "No usable presenter/voice presets found; generation stays disabled."
                )
            config.update(presets=presets, ready=True)
    await state.put.aio("config", config)
    print(
        json.dumps(
            {
                "base_url": config["base_url"],
                "generation_ready": config["ready"],
                "avatar_presets": len(config["presets"].get("avatars", [])),
                "voice_presets": len(config["presets"].get("voices", [])),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "configure", "cleanup", "release-slot"])
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--allow-unconfigured", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--task-id")
    parser.add_argument("--confirmed-provider-finished", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup_credentials(args.env_file, args.allow_unconfigured)
        elif args.command == "configure":
            if not args.base_url:
                parser.error("configure requires --base-url")
            asyncio.run(configure(args.env_file, args.base_url))
        else:
            coordinator = modal.Cls.from_name(APP_NAME, "Coordinator")()
            if args.command == "cleanup":
                print(coordinator.cleanup.remote())
            else:
                if not args.task_id or not args.confirmed_provider_finished:
                    parser.error(
                        "release-slot requires --task-id and --confirmed-provider-finished"
                    )
                print(coordinator.release_uncertain_slot.remote(args.task_id))
    except (ValueError, ProviderError):
        # Provider bodies, URLs and credentials must not escape through tracebacks.
        print(
            "Setup failed: check credentials, the base URL, and verified preset configuration.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
