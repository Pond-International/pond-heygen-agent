"""Finite, restartable completion adapters. Polling performs GET requests only."""

import copy
import re
from urllib.parse import urlsplit

from .media_files import SUPPORTED_MEDIA
from .provider import ProviderError
from .tool_registry import operations
from .tool_runtime import data_of, sanitize

MAX_ITEMS = 1000
MAX_PAGES = 10
READS_PER_POLL = 25
VIDEO_TYPES = ["video/mp4", "video/webm", "video/quicktime"]
AUDIO_TYPES = ["audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg"]
IMAGE_TYPES = ["image/png", "image/jpeg"]
PATHS = {
    "video": "/v3/videos",
    "session": "/v3/video-agents",
    "avatar": "/v3/avatars/looks",
    "voice": "/v3/voices",
    "professional_voice": "/v3/models/audio/voices",
    "brand_kit": "/v3/brand-kits",
    "translation": "/v3/video-translations",
    "proofread": "/v3/video-translations/proofreads",
    "lipsync": "/v3/lipsyncs",
    "hyperframes": "/v3/hyperframes/renders",
    "clipping": "/v3/ai-clipping",
    "background_removal": "/v3/background-removals",
    "filler_removal": "/v3/filler-word-removals",
    "podcast": "/v3/podcasts",
    "workflow": "/v3/workflow-runs",
    "comparison": "/v3/video-quality/comparisons",
    "asset": "/v3/assets",
}
STATES = {
    "video": ({"completed"}, {"pending", "processing", "waiting"}, {"failed"}),
    "session": ({"completed"}, {"thinking", "reviewing", "generating"}, {"failed"}),
    "avatar": ({"completed"}, {"processing"}, {"failed"}),
    "voice": ({"complete"}, {"processing"}, {"failed"}),
    "professional_voice": ({"ACTIVE"}, {"PENDING"}, {"FAILED"}),
    "brand_kit": ({"completed"}, {"loading"}, {"error"}),
    "translation": ({"completed"}, {"pending", "running"}, {"failed"}),
    "proofread": ({"completed"}, {"processing"}, {"failed"}),
    "lipsync": ({"completed"}, {"pending", "running"}, {"failed"}),
    "hyperframes": ({"completed"}, {"queued", "rendering"}, {"failed"}),
    "clipping": ({"completed"}, {"pending", "running"}, {"failed", "cancelled"}),
    "background_removal": ({"completed"}, {"pending", "processing"}, {"failed", "deleted"}),
    "filler_removal": ({"completed"}, {"pending", "running"}, {"failed"}),
    "podcast": ({"completed"}, {"processing"}, {"failed"}),
    "workflow": ({"succeeded"}, {"pending", "processing"}, {"partial", "failed", "canceled"}),
    "comparison": ({"completed"}, {"processing"}, {"failed"}),
    "asset": ({"completed"}, {"queued", "processing"}, {"failed", "not_found"}),
    "batch": ({"completed"}, {"processing"}, {"failed"}),
    "batch_item": ({"completed"}, {"queued", "processing"}, {"failed"}),
    "clip": ({"completed"}, {"pending"}, {"failed"}),
}
ID_FIELDS = {
    "video": ("video_id", "id"),
    "session": ("session_id",),
    "avatar": (),
    "voice": ("voice_clone_id", "voice_id"),
    "professional_voice": ("voice_id",),
    "brand_kit": ("brand_kit_id",),
    "translation": ("video_translation_ids", "video_translation_id"),
    "proofread": ("proofread_ids",),
    "lipsync": ("lipsync_id",),
    "hyperframes": ("render_id",),
    "clipping": ("ai_clipping_id",),
    "background_removal": ("id",),
    "filler_removal": ("filler_word_removal_id",),
    "podcast": ("podcast_id",),
    "workflow": ("id",),
    "comparison": ("comparison_id",),
    "asset": ("asset_id", "id"),
}


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
        raise ProviderError("provider_response_invalid", "HeyGen returned an invalid resource ID.")
    return value


def _state(status, data, files=None, code=None, message=None):
    result = {"status": status, "data": sanitize(data), "files": files or []}
    if code:
        result["error"] = {
            "code": code,
            "message": message or "HeyGen did not complete this operation.",
        }
    return result


def _classify(family, value):
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        return _state("failed", value, code="provider_response_invalid")
    status = value.get("status")
    if status in {"waiting_for_input", "pending_consent"}:
        return _state(
            "failed",
            value,
            code="prerequisite_required",
            message="HeyGen requires an interactive decision or consent. Supply a ready resource; "
            "this one-shot task cannot finish that interactive flow.",
        )
    success, pending, failed = STATES[family]
    if status in success:
        return _state("completed", value)
    if status in pending:
        return _state("processing", value)
    if status in failed:
        return _state("failed", value, code="provider_job_failed")
    return _state(
        "failed",
        value,
        code="provider_response_invalid",
        message="HeyGen returned an unknown or missing completion status.",
    )


def _file(url, name, types):
    if url is None or url == "":
        return []
    if not isinstance(url, str):
        raise ProviderError("provider_response_invalid", "HeyGen returned an invalid media URL.")
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
    except ValueError:
        raise ProviderError(
            "provider_response_invalid", "HeyGen returned an invalid media URL."
        ) from None
    suffix = parsed.path.rsplit(".", 1)[-1].lower()
    extensions = {
        "mp4",
        "webm",
        "mov",
        "wav",
        "mp3",
        "m4a",
        "ogg",
        "png",
        "jpg",
        "jpeg",
        "srt",
        "vtt",
        "json",
        "pdf",
    }
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:180]
    if suffix in extensions:
        filename += "." + suffix
    return [{"url": url, "name": filename, "media_types": list(types)}]


def _files(value, prefix):
    if not isinstance(value, dict):
        return []
    result = []
    groups = [
        (("video_url", "captioned_video_url", "preview_video_url"), VIDEO_TYPES),
        (("audio_url", "preview_audio_url"), AUDIO_TYPES),
        (("thumbnail_url", "preview_image_url"), IMAGE_TYPES),
        (
            ("srt_url", "original_srt_url", "srt_caption_url", "subtitle_url", "caption_url"),
            ["application/x-subrip"],
        ),
        (("vtt_caption_url",), ["text/vtt"]),
    ]
    for fields, types in groups:
        for field in fields:
            result.extend(_file(value.get(field), prefix + "-" + field.removesuffix("_url"), types))
    return result


def _aggregate(family, items, job, provider=None):
    files = [file for item in items for file in item.get("files", [])]
    errors = [item["error"] for item in items if item.get("error")]
    pending = any(item["status"] == "processing" for item in items)
    usable = bool(files) or any(item["status"] == "completed" for item in items)
    partial = bool(errors and usable) or any(
        isinstance(item.get("data"), dict) and item["data"].get("partial") for item in items
    )
    data = {"family": family, "items": items, "partial": partial}
    if provider is not None:
        data["provider"] = provider
    status = "processing" if pending else "failed" if errors and not usable else "completed"
    result = _state(status, data, files)
    result["video_usage"] = [
        record
        for item in items
        if item["status"] == "completed"
        for record in item.get("video_usage", [])
    ]
    if status == "failed":
        result["error"] = errors[0]
    result["job"] = job
    return result


class ToolJobs:
    def __init__(self, runtime):
        self.runtime = runtime

    async def start(self, action, parameters, task_id):
        family = operations()[action]["completion"]
        baseline = []
        if action == "send_video_agent_message":
            sid = _identifier(parameters.get("path", {}).get("session_id"))
            await self.runtime.access.require("session", sid, write=True)
            _, videos = await self._pages(PATHS["session"] + "/" + sid + "/videos", array=True)
            baseline = [_identifier(video.get("id")) for video in videos]
        initial = (
            await self.runtime.upload_batch(parameters, task_id)
            if action == "upload_assets_batch"
            else await self.runtime.execute(action, parameters, task_id=task_id)
        )
        value = data_of(initial)
        job = {
            "version": 1,
            "action": action,
            "family": family,
            "initial": sanitize(initial),
            "children": {},
            "baseline_video_ids": baseline,
            "revision": action == "send_video_agent_message",
            "retraining": family == "professional_voice"
            and bool(parameters.get("body", {}).get("voice_id")),
            "requested_layers": parameters.get("body", {}).get(
                "layers", ["foreground", "mask", "background"]
            ),
        }
        if family in {"snapshot", "mutation", "speech"}:
            return job
        try:
            if not isinstance(value, dict):
                raise ProviderError(
                    "provider_response_invalid", "HeyGen omitted the created resource."
                )
            if family == "avatar":
                ids = [(value.get("avatar_item") or {}).get("id")]
            else:
                fields = ("batch_id",) if family.endswith("_batch") else ID_FIELDS[family]
                ids = []
                for field in fields:
                    found = value.get(field)
                    if found:
                        ids.extend(found if isinstance(found, list) else [found])
            if not ids or len(ids) > MAX_ITEMS:
                raise ProviderError(
                    "provider_response_invalid", "HeyGen omitted IDs or exceeded the result limit."
                )
            job["ids"] = list(dict.fromkeys(_identifier(identifier) for identifier in ids))
            for identifier in job["ids"]:
                await self._remember(family, identifier, value)
        except ProviderError as error:
            job["error"] = {"code": error.code, "message": str(error)}
        return job

    async def _remember(self, family, identifier, value):
        await self.runtime.access.remember(
            "look" if family == "avatar" else family, _identifier(identifier)
        )

    async def _read(self, path, **kwargs):
        return sanitize(await self.runtime.request("GET", path, **kwargs))

    async def _pages(self, path, *, array=False):
        items, tokens, query, first = [], set(), {}, None
        for _ in range(MAX_PAGES):
            response = await self._read(path, **({"params": query} if query else {}))
            value = data_of(response)
            page = value if array else value.get("items") if isinstance(value, dict) else None
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ProviderError(
                    "provider_response_invalid", "HeyGen returned an invalid result page."
                )
            first = first if first is not None else value
            items.extend(page)
            if len(items) > MAX_ITEMS:
                raise ProviderError(
                    "resource_limit", "HeyGen results exceed the bounded collection limit."
                )
            pagination = response if array else value
            if not pagination.get("has_more"):
                return first, items
            token = pagination.get("next_token")
            if not isinstance(token, str) or not token or token in tokens:
                raise ProviderError(
                    "provider_response_invalid", "HeyGen pagination did not advance."
                )
            tokens.add(token)
            query = {"limit": 100, "token": token}
        raise ProviderError("resource_limit", "HeyGen results exceed the bounded page limit.")

    async def poll(self, job):
        job = copy.deepcopy(job)
        try:
            return await self._poll(job)
        except ProviderError as error:
            if error.code in {"provider_unavailable", "rate_limited"}:
                raise
            result = _state(
                "failed",
                {"family": job["family"], "initial": job["initial"]},
                code=error.code,
                message=str(error),
            )
            result["job"] = job
            return result

    async def _poll(self, job):
        family, initial = job["family"], data_of(job["initial"])
        if job.get("error"):
            return {**_state("failed", job["initial"]), "error": job["error"], "job": job}
        if family in {"snapshot", "mutation", "speech"}:
            files = (
                _files(initial, job["action"])
                if family == "speech" or job["action"] == "download_proofread_srt"
                else []
            )
            if family == "speech" and not (isinstance(initial, dict) and initial.get("audio_url")):
                return _state("failed", job["initial"], code="provider_response_invalid")
            return _state("completed", job["initial"], files)
        if family == "asset" and initial.get("url") and not initial.get("status"):
            return _state("completed", initial, self._asset_files(initial, job["ids"][0]))
        if family == "session":
            return await self._session(job)
        if family.endswith("_batch"):
            return await self._batch(job)
        reads = 0
        for identifier in job["ids"]:
            cached = job["children"].get(identifier)
            if cached and cached["status"] != "processing":
                continue
            if reads >= READS_PER_POLL:
                break
            reads += 1
            job["children"][identifier] = await self._one(family, identifier, job)
        items = [
            job["children"].get(identifier, _state("processing", {"id": identifier}))
            for identifier in job["ids"]
        ]
        return _aggregate(family, items, job)

    async def _one(self, family, identifier, job, *, asset_ready=False):
        try:
            return await self._inspect(family, identifier, job, asset_ready=asset_ready)
        except ProviderError as error:
            if error.code in {"provider_unavailable", "rate_limited"}:
                raise
            return _state("failed", {"id": identifier}, code=error.code, message=str(error))

    async def _inspect(self, family, identifier, job, *, asset_ready=False):
        path = PATHS[family] + "/" + _identifier(identifier)
        if family == "asset" and not asset_ready:
            statuses = data_of(
                await self._read(PATHS["asset"] + "/statuses", params={"asset_ids": identifier})
            )
            entry = (
                next((item for item in statuses if item.get("video_id") == identifier), {})
                if isinstance(statuses, list)
                else {}
            )
            state = _classify("asset", entry)
            if state["status"] != "completed":
                return state
        value = data_of(await self._read(path))
        if not isinstance(value, dict):
            return _state("failed", value, code="provider_response_invalid")
        await self._remember(family, identifier, value)
        if family == "asset":
            return _state("completed", value, self._asset_files(value, identifier))
        state = _classify(family, value)
        if (
            family == "professional_voice"
            and value.get("status") == "ACTIVE"
            and job.get("retraining")
        ):
            return _state(
                "failed",
                value,
                code="provider_outcome_unverifiable",
                message="HeyGen reports an ACTIVE voice but does not expose whether retraining "
                "succeeded or restored the previous voice after failure.",
            )
        if (
            state["status"] == "completed"
            or family == "workflow"
            and value.get("status") == "partial"
        ):
            state = await self._finished(family, identifier, value, job, state)
        return state

    @staticmethod
    def _asset_files(value, identifier):
        types = {
            "video": VIDEO_TYPES,
            "image": IMAGE_TYPES,
            "audio": AUDIO_TYPES,
            "pdf": ["application/pdf"],
        }.get(value.get("type"))
        if not types:
            types = [
                mime
                for mime, suffix in SUPPORTED_MEDIA.items()
                if str(value.get("name", "")).lower().endswith(suffix)
            ]
        if not types and value.get("mime_type") in SUPPORTED_MEDIA:
            types = [value["mime_type"]]
        if not types:
            return []  # Unknown optional source files remain available as resource metadata.
        return _file(value.get("url"), identifier + "-asset", types)

    async def _finished(self, family, identifier, value, job, state):
        files = _files(value, identifier)
        video_usage = []
        if family in {
            "video",
            "lipsync",
            "hyperframes",
            "filler_removal",
            "podcast",
        } and not value.get("video_url"):
            return _state(
                "failed",
                value,
                code="provider_response_invalid",
                message="HeyGen completed without its final video.",
            )
        if family == "translation" and not (value.get("video_url") or value.get("audio_url")):
            return _state("failed", value, code="provider_response_invalid")
        if family == "comparison" and not isinstance(value.get("result"), dict):
            return _state("failed", value, code="provider_response_invalid")
        if family in {
            "video",
            "lipsync",
            "hyperframes",
            "filler_removal",
            "podcast",
            "translation",
        }:
            if value.get("video_url"):
                duration_field = "output_duration" if family == "filler_removal" else "duration"
                video_usage.append(
                    {
                        "key": family + ":" + identifier,
                        "duration": value.get(duration_field),
                        "url": value["video_url"],
                    }
                )
        if family == "proofread":
            subtitles = data_of(await self._read(PATHS[family] + "/" + identifier + "/srt"))
            if not isinstance(subtitles, dict) or not subtitles.get("srt_url"):
                return _state("failed", value, code="provider_response_invalid")
            value = {**value, "subtitles": subtitles}
            files.extend(_files(subtitles, identifier))
        if family == "background_removal":
            layers = value.get("layers", {})
            if not isinstance(layers, dict) or not all(
                layers.get(layer) for layer in job["requested_layers"]
            ):
                return _state("failed", value, code="provider_response_invalid")
            for layer, url in layers.items():
                files.extend(_file(url, identifier + "-" + layer, VIDEO_TYPES))
            video_usage.append(
                {
                    "key": "background_removal:" + identifier,
                    "duration": value.get("duration"),
                    "url": next((url for url in layers.values() if url), None),
                }
            )
        if family == "clipping":
            clips = value.get("clips")
            if not isinstance(clips, list) or not clips:
                return _state("failed", value, code="provider_response_invalid")
            results = []
            for clip in clips:
                child = _classify("clip", clip)
                if child["status"] == "completed":
                    if not clip.get("video_url"):
                        child = _state("failed", clip, code="provider_response_invalid")
                    else:
                        child["files"] = _files(
                            clip, identifier + "-" + _identifier(clip.get("id"))
                        )
                        child["video_usage"] = [
                            {
                                "key": "clip:" + identifier + ":" + clip["id"],
                                "duration": clip.get("duration_seconds"),
                                "url": clip["video_url"],
                            }
                        ]
                results.append(child)
            result = _aggregate(family, results, job)
            result.pop("job")
            return result
        if family == "workflow":
            outputs = value.get("outputs")
            if not isinstance(outputs, list):
                return _state("failed", value, code="provider_response_invalid")
            ready = 0
            for output in outputs:
                if output.get("status") != "ready":
                    if state["status"] == "completed":
                        return _state("failed", value, code="provider_response_invalid")
                    continue
                if output.get("artifact_id"):
                    await self.runtime.access.remember(
                        "workflow_artifact", _identifier(output["artifact_id"])
                    )
                if output.get("delivery") == "reference":
                    types = {"video": VIDEO_TYPES, "audio": AUDIO_TYPES, "image": IMAGE_TYPES}.get(
                        output.get("type"), ["application/json"]
                    )
                    if not output.get("url"):
                        return _state("failed", value, code="provider_response_invalid")
                    files.extend(
                        _file(
                            output["url"],
                            identifier + "-" + str(output.get("name", "output")),
                            types,
                        )
                    )
                elif output.get("delivery") != "inline" or "value" not in output:
                    return _state("failed", value, code="provider_response_invalid")
                if output.get("type") == "video":
                    # A workflow artifact is the provider's durable produced-output identity.
                    # Arbitrary inline JSON is NOT trusted for duration or a video URL.
                    video_usage.append(
                        {
                            "key": "workflow:" + output["artifact_id"]
                            if output.get("artifact_id")
                            else None,
                            "duration": None,
                            "url": output.get("url")
                            if output.get("delivery") == "reference"
                            else None,
                        }
                    )
                ready += 1
            if ready and state["status"] == "failed":
                state = {**state, "status": "completed"}
                value = {**value, "partial": True}
        return {**state, "data": sanitize(value), "files": files, "video_usage": video_usage}

    async def _session(self, job):
        sid = job["ids"][0]
        value = data_of(await self._read(PATHS["session"] + "/" + sid))
        state = _classify("session", value)
        state["job"] = job
        if state["status"] != "completed":
            return state
        video_id = value.get("video_id")
        if job["revision"] and (not video_id or video_id in job["baseline_video_ids"]):
            if state["status"] == "completed":
                _, videos = await self._pages(PATHS["session"] + "/" + sid + "/videos", array=True)
                video_id = next(
                    (
                        video.get("id")
                        for video in videos
                        if video.get("id") not in job["baseline_video_ids"]
                    ),
                    None,
                )
            else:
                video_id = None
        if not video_id:
            return {**state, "status": "processing"}
        video_id = _identifier(video_id)
        await self._remember("video", video_id, {})
        video = await self._one("video", video_id, job)
        video["data"] = {"session": value, "video": video["data"]}
        video["job"] = job
        return video

    async def _batch(self, job):
        family = job["family"].removesuffix("_batch")
        identifier = job["ids"][0]
        provider, items = await self._pages(PATHS[family] + "/batches/" + identifier)
        parent = _classify("batch", provider)
        if parent.get("error", {}).get("code") == "provider_response_invalid":
            return {**parent, "job": job}
        indices = [item.get("item_index") for item in items]
        total = provider.get("total_items")
        if len(set(indices)) != len(items) or not isinstance(total, int) or total != len(items):
            return {**_state("failed", provider, code="provider_response_invalid"), "job": job}
        reads, results = 0, []
        for item in items:
            key = str(item["item_index"])
            value = item.get("comparison", {}) if family == "comparison" else item
            result = _classify("comparison" if family == "comparison" else "batch_item", value)
            child_id = (
                value.get("comparison_id") if family == "comparison" else value.get("video_id")
            )
            if child_id:
                await self._remember(family, child_id, value)
            if result["status"] == "completed":
                if not child_id:
                    result = _state("failed", item, code="provider_response_invalid")
                elif family == "comparison":
                    if not isinstance(value.get("result"), dict):
                        result = _state("failed", item, code="provider_response_invalid")
                else:
                    cached = job["children"].get(key)
                    if cached and cached["status"] != "processing":
                        result = cached
                    elif reads < READS_PER_POLL:
                        reads += 1
                        result = await self._one(
                            family, child_id, job, asset_ready=family == "asset"
                        )
                        job["children"][key] = result
                    else:
                        result = _state("processing", item)
            result = {**result, "item_index": item["item_index"]}
            results.append(result)
        if not results:
            return {**_state("failed", provider, code="provider_response_invalid"), "job": job}
        if parent["status"] == "processing" and all(
            item["status"] != "processing" for item in results
        ):
            parent["data"] = {key: value for key, value in provider.items() if key != "items"}
            results.append(parent)
        if parent["status"] == "failed" and not any(item["status"] == "failed" for item in results):
            results.append(parent)
        return _aggregate(job["family"], results, job, provider)
