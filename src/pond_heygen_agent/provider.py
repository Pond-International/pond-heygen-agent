"""HeyGen REST v3 submission and polling, with an explicit preset allowlist."""

import hashlib
import math
import re
from copy import deepcopy
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from pond_heygen_agent.media import ATTACHMENT_TYPES, MediaError, safe_fetch

API_ORIGIN = "https://api.heygen.com"
MAX_ATTACHMENT_BYTES = 20 * 1024**2
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_:.-]{1,255}$")
_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "hi": "Hindi",
    "ar": "Arabic",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "sv": "Swedish",
}


class ProviderError(Exception):
    """Sanitized provider error; ambiguous submissions must not be recreated."""

    def __init__(
        self,
        code: str,
        message: str,
        ambiguous: bool = False,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ambiguous = ambiguous
        self.retry_after = retry_after


def _identifier(value) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _language(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return _LANGUAGES.get(normalized.split("-")[0], value.strip())


def _matches_language(voice: dict, language: str) -> bool:
    return _language(str(voice.get("language", ""))).casefold() == language.casefold()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0, min(seconds, 3600)) if math.isfinite(seconds) else None
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            return max(0, min(seconds, 3600))
        except (TypeError, ValueError, OverflowError):
            return None


class HeyGenClient:
    def __init__(
        self,
        api_key: str,
        presets: dict | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._api_key = api_key
        self._presets = deepcopy(presets)
        self._client = client

    async def _request(self, method: str, path: str, *, paid: bool = False, **kwargs):
        if not self._api_key:
            raise ProviderError("provider_unavailable", "HeyGen credentials are not configured.")
        if not path.startswith("/v3/") or "?" in path or "#" in path:
            raise ProviderError("invalid_request", "Invalid provider operation.")
        headers = {"X-Api-Key": self._api_key, **kwargs.pop("headers", {})}
        request = httpx.Request(method, API_ORIGIN + path, headers=headers, **kwargs)
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, trust_env=False)
        try:
            # Explicit requests avoid inheriting user-facing bearer auth or cookies.
            response = await client.send(request, auth=None, follow_redirects=False)
        except httpx.HTTPError:
            raise ProviderError(
                "submission_ambiguous" if paid else "provider_unavailable",
                "HeyGen did not confirm the submission; it may still be running."
                if paid
                else "HeyGen could not be reached.",
                ambiguous=paid,
            ) from None
        finally:
            if owned:
                await client.aclose()
        if response.status_code == 429:
            raise ProviderError(
                "rate_limited",
                "HeyGen is rate limiting requests.",
                retry_after=_retry_after(response),
            )
        if response.status_code in (401, 403):
            raise ProviderError(
                "provider_authentication", "HeyGen rejected the configured credentials."
            )
        if (
            response.status_code >= 500
            or response.status_code in (408, 409)
            or response.is_redirect
        ):
            raise ProviderError(
                "submission_ambiguous" if paid else "provider_unavailable",
                "HeyGen did not confirm the submission; it may still be running."
                if paid
                else "HeyGen is temporarily unavailable.",
                ambiguous=paid,
                retry_after=_retry_after(response),
            )
        if not response.is_success:
            raise ProviderError("provider_rejected", "HeyGen rejected the request.")
        try:
            payload = response.json()
            if not isinstance(payload, dict) or "data" not in payload:
                raise ValueError
            return payload["data"]
        except (ValueError, TypeError):
            raise ProviderError(
                "submission_ambiguous" if paid else "provider_response_invalid",
                "HeyGen returned an invalid response.",
                ambiguous=paid,
            ) from None

    async def _public_voices(self, language: str) -> list[dict]:
        rows = await self._request(
            "GET",
            "/v3/voices",
            params={
                "type": "public",
                "language": language,
                "limit": 100,
            },
        )
        if not isinstance(rows, list):
            raise ProviderError("provider_response_invalid", "HeyGen returned an invalid catalog.")
        voices = {
            row["voice_id"]: {
                "id": row["voice_id"],
                "name": row["name"],
                "language": row["language"],
            }
            for row in rows
            if isinstance(row, dict)
            and row.get("type") == "public"
            and _identifier(row.get("voice_id"))
            and isinstance(row.get("name"), str)
            and row["name"].strip()
            and _matches_language(row, language)
        }
        return sorted(voices.values(), key=lambda row: (row["name"].casefold(), row["id"]))[:6]

    async def discover_presets(self) -> dict:
        """Choose a bounded public catalog, using look IDs and Avatar IV eligibility."""
        voices = await self._public_voices("English")
        groups = await self._request(
            "GET",
            "/v3/avatars",
            params={
                "ownership": "public",
                "limit": 50,
            },
        )
        if not isinstance(groups, list):
            raise ProviderError("provider_response_invalid", "HeyGen returned an invalid catalog.")
        groups = sorted(
            (
                row
                for row in groups
                if isinstance(row, dict)
                and _identifier(row.get("id"))
                and isinstance(row.get("name"), str)
                and row["name"].strip()
                and row.get("status") in (None, "completed")
            ),
            key=lambda row: (row["name"].casefold(), row["id"]),
        )
        voice_ids = {voice["id"] for voice in voices}
        avatars = []
        for group in groups[:12]:
            looks = await self._request(
                "GET",
                "/v3/avatars/looks",
                params={
                    "ownership": "public",
                    "group_id": group["id"],
                    "limit": 50,
                },
            )
            if not isinstance(looks, list):
                raise ProviderError(
                    "provider_response_invalid", "HeyGen returned an invalid catalog."
                )
            eligible = sorted(
                (
                    row
                    for row in looks
                    if isinstance(row, dict)
                    and _identifier(row.get("id"))
                    and isinstance(row.get("name"), str)
                    and row["name"].strip()
                    and row.get("group_id") == group["id"]
                    and row.get("status") in (None, "completed")
                    and "avatar_iv" in (row.get("supported_api_engines") or [])
                ),
                key=lambda row: (row["name"].casefold(), row["id"]),
            )
            for look in eligible:
                default_voice = look.get("default_voice_id") or group.get("default_voice_id")
                if default_voice not in voice_ids:
                    default_voice = voices[0]["id"] if voices else None
                if default_voice is not None:
                    avatars.append(
                        {
                            "id": look["id"],
                            "name": f"{group['name']} — {look['name']}",
                            "voice_id": default_voice,
                        }
                    )
                if len(avatars) >= 6:
                    break
            if len(avatars) >= 6:
                break
        result = {"avatars": avatars, "voices": voices}
        self._presets = deepcopy(result)
        return result

    async def _select(self, parameters: dict, need_avatar: bool) -> tuple[dict | None, dict]:
        presets = self._presets
        if presets is None:
            presets = await self.discover_presets()
        avatars = presets.get("avatars", [])
        voices = presets.get("voices", [])
        avatar_id = parameters.get("avatar_id")
        voice_id = parameters.get("voice_id")
        avatar = next((row for row in avatars if row.get("id") == avatar_id), None)
        if avatar_id and avatar is None:
            raise ProviderError("invalid_preset", "Choose an avatar from the configured presets.")
        if need_avatar and avatar is None:
            avatar = avatars[0] if avatars else None
            if avatar is None:
                raise ProviderError(
                    "presets_unavailable", "No verified presenter preset is configured."
                )
        language = _language(parameters.get("language") or "English")
        compatible = [row for row in voices if _matches_language(row, language)]
        if voice_id:
            voice = next((row for row in compatible if row.get("id") == voice_id), None)
            if voice is None:
                raise ProviderError(
                    "invalid_preset",
                    "Choose a configured voice matching the requested language.",
                )
        else:
            if not compatible:
                if not voices:
                    raise ProviderError(
                        "presets_unavailable", "No verified voice preset is configured."
                    )
                compatible = await self._public_voices(language)
            voice = next(
                (row for row in compatible if avatar and row["id"] == avatar.get("voice_id")), None
            )
            if voice is None:
                voice = compatible[0] if compatible else None
            if voice is None:
                raise ProviderError(
                    "presets_unavailable",
                    "No verified voice is available for the requested language.",
                )
        if not _identifier(voice.get("id")) or (avatar and not _identifier(avatar.get("id"))):
            raise ProviderError("presets_unavailable", "The configured presets are invalid.")
        return avatar, voice

    @staticmethod
    def _prompt(parameters: dict) -> str:
        brief = parameters.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            raise ProviderError("invalid_request", "A video brief is required.")
        duration = parameters.get("target_duration_seconds", 30)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not 1 <= duration <= 60
        ):
            raise ProviderError(
                "invalid_request", "The target duration must be between 1 and 60 seconds."
            )
        parts = [
            "Create one finished video using the specified avatar and voice only.",
            "Do not use other private avatars, cloned voices, or workspace assets.",
        ]
        if parameters.get("_instruction"):
            parts.append(
                "Additional context (the structured fields below take precedence):\n"
                + str(parameters["_instruction"])
            )
        parts.append(f"Brief: {brief}")
        for field in ("audience", "purpose", "tone", "visual_style", "call_to_action"):
            if parameters.get(field):
                parts.append(f"{field.replace('_', ' ').title()}: {parameters[field]}")
        if parameters.get("key_messages"):
            parts.append("Key messages:\n" + "\n".join(parameters["key_messages"]))
        parts.append(f"Language: {_language(parameters.get('language') or 'English')}")
        parts.append(f"Target duration: {duration} seconds. Keep the video under 60 seconds.")
        prompt = "\n\n".join(parts)
        if len(prompt) > 10_000:
            raise ProviderError(
                "invalid_request", "The combined video brief exceeds 10000 characters."
            )
        return prompt

    async def _assets(self, files: list[dict], portrait: bool, key: str) -> list[dict]:
        if len(files) > 5 or (portrait and len(files) != 1):
            raise ProviderError(
                "invalid_request", "Provide up to five references or exactly one portrait."
            )
        remaining = MAX_ATTACHMENT_BYTES
        prepared = []
        allowed = {"image/png", "image/jpeg"} if portrait else ATTACHMENT_TYPES
        for descriptor in files:
            declared = descriptor.get("media_type")
            if declared and declared.lower().split(";")[0].strip() not in allowed:
                raise ProviderError(
                    "invalid_file", "Only PNG, JPEG, and PDF references are supported."
                )
            try:
                data, mime = await safe_fetch(
                    descriptor["url"],
                    remaining,
                    allowed,
                    self._client,
                )
            except (MediaError, KeyError) as error:
                message = str(error) if isinstance(error, MediaError) else "A file URL is required."
                raise ProviderError("invalid_file", message) from None
            if declared and declared.lower().split(";")[0].strip() != mime:
                raise ProviderError(
                    "invalid_file", "The file does not match its declared media type."
                )
            remaining -= len(data)
            prepared.append((data, mime))
        assets = []
        for index, (data, mime) in enumerate(prepared):
            extension = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf"}[mime]
            upload_key = hashlib.sha256(f"{key}:asset:{index}".encode()).hexdigest()
            result = await self._request(
                "POST",
                "/v3/assets",
                headers={"Idempotency-Key": upload_key},
                files={"file": (f"reference-{index + 1}.{extension}", data, mime)},
            )
            if not isinstance(result, dict) or not _identifier(result.get("asset_id")):
                raise ProviderError(
                    "provider_response_invalid", "HeyGen did not confirm the file upload."
                )
            assets.append({"type": "asset_id", "asset_id": result["asset_id"]})
        return assets

    async def create(
        self,
        action: str,
        parameters: dict,
        files: list[dict],
        idempotency_key: str,
    ) -> dict:
        """Validate, upload, and submit exactly one paid request without retries."""
        if action not in ("generate_video", "generate_presenter_video"):
            raise ProviderError("unsupported_action", "This generation action is not supported.")
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ProviderError("invalid_request", "The submission key is invalid.")
        orientation = parameters.get("orientation", "landscape")
        if orientation not in ("landscape", "portrait"):
            raise ProviderError("invalid_request", "Choose landscape or portrait orientation.")
        portrait = (
            action == "generate_presenter_video" and parameters.get("presenter") == "portrait"
        )
        if portrait and parameters.get("portrait_permission") is not True:
            raise ProviderError(
                "invalid_request", "Permission to animate this portrait must be confirmed."
            )
        if action == "generate_video":
            body = {
                "prompt": self._prompt(parameters),
                "mode": "generate",
                "incognito_mode": True,
                "orientation": orientation,
            }
        else:
            if parameters.get("presenter", "avatar") not in ("avatar", "portrait"):
                raise ProviderError("invalid_request", "Choose an avatar or portrait presenter.")
            script = parameters.get("script")
            if not isinstance(script, str) or not script.strip():
                raise ProviderError("invalid_request", "An exact presenter script is required.")
            if not portrait and files:
                raise ProviderError(
                    "invalid_request", "Avatar presenter videos do not accept reference files."
                )
            body = {
                "type": "image" if portrait else "avatar",
                "script": script,
                "resolution": "720p",
                "output_format": "mp4",
                "aspect_ratio": "16:9" if orientation == "landscape" else "9:16",
            }
        avatar, voice = await self._select(parameters, need_avatar=not portrait)
        body["voice_id"] = voice["id"]
        if not portrait:
            body["avatar_id"] = avatar["id"]
        assets = await self._assets(files, portrait, idempotency_key)
        if action == "generate_video":
            if assets:
                body["files"] = assets
            result = await self._request("POST", "/v3/video-agents", paid=True, json=body)
            kind, identifier_key = "session", "session_id"
        else:
            if portrait:
                body["image"] = assets[0]
            else:
                body["engine"] = {"type": "avatar_iv"}
            result = await self._request(
                "POST",
                "/v3/videos",
                paid=True,
                json=body,
                headers={"Idempotency-Key": idempotency_key},
            )
            kind, identifier_key = "video", "video_id"
        if not isinstance(result, dict) or not _identifier(result.get(identifier_key)):
            raise ProviderError(
                "submission_ambiguous",
                "HeyGen did not return a valid submission identifier.",
                ambiguous=True,
            )
        return {"kind": kind, "id": result[identifier_key]}

    async def status(self, job: dict) -> dict:
        kind, identifier = job.get("kind"), job.get("id")
        if kind not in ("session", "video") or not _identifier(identifier):
            raise ProviderError("invalid_request", "The provider job identifier is invalid.")
        path = "/v3/video-agents/" if kind == "session" else "/v3/videos/"
        data = await self._request("GET", path + identifier)
        if not isinstance(data, dict):
            raise ProviderError(
                "provider_response_invalid", "HeyGen returned an invalid job status."
            )
        state = data.get("status")
        if state == "failed":
            return {"status": "failed", "message": "HeyGen could not generate the video."}
        if kind == "session":
            if state not in (
                "thinking",
                "waiting_for_input",
                "reviewing",
                "generating",
                "completed",
            ):
                return {"status": "processing"}
            if _identifier(data.get("video_id")):
                return await self.status({"kind": "video", "id": data["video_id"]})
            if state == "waiting_for_input":
                return {
                    "status": "failed",
                    "message": "HeyGen requested input in a one-shot session.",
                }
            return {"status": "processing"}
        if state == "completed" and isinstance(data.get("video_url"), str) and data["video_url"]:
            result = {"status": "completed", "video_url": data["video_url"]}
            duration = data.get("duration")
            if (
                isinstance(duration, (int, float))
                and not isinstance(duration, bool)
                and math.isfinite(duration)
                and duration >= 0
            ):
                result["duration"] = float(duration)
            return result
        return {"status": "pending" if state in ("pending", "waiting") else "processing"}
