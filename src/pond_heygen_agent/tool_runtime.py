"""Registered native operations with tenant authorization and bounded transport.

Only internal code may call request(); Pond input cannot select a host, method,
path template, headers, credentials, or retry policy.
"""

import base64
import copy
import hashlib
import re

import httpx
from jsonschema import Draft202012Validator

from .media import MediaError, _public_target
from .media_files import MAX_FILE_BYTES, fetch_media, inspect_media
from .provider import API_ORIGIN, ProviderError, _retry_after
from .render_policy import apply_render_defaults
from .resource_access import AccessDenied
from .tool_registry import operations, validate_action

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")
RESOURCE_FIELDS = {
    "voice_id": "voice",
    "avatar_id": "look",
    "look_id": "look",
    "avatar_group_id": "avatar",
    "group_id": "avatar",
    "asset_id": "asset",
    "video_id": "video",
    "session_id": "session",
    "template_id": "template",
    "brand_kit_id": "brand_kit",
    "brand_glossary_id": "brand_glossary",
    "glossary_id": "brand_glossary",
    "proofread_id": "proofread",
    "video_translation_id": "translation",
    "lipsync_id": "lipsync",
    "filler_word_removal_id": "filler_removal",
    "render_id": "hyperframes",
    "podcast_id": "podcast",
    "workflow_id": "workflow_definition",
    "run_id": "workflow",
    "comparison_id": "comparison",
    "folder_id": "folder",
    "ai_clipping_id": "clipping",
    "character_id": "look",
}
PATH_KINDS = (
    ("/video-quality/comparisons", "comparison"),
    ("/video-translations/proofreads", "proofread"),
    ("/video-translations", "translation"),
    ("/models/audio/voices", "professional_voice"),
    ("/models/audio/tts", "professional_voice"),
    ("/video-agents", "session"),
    ("/avatars/looks", "look"),
    ("/avatars", "avatar"),
    ("/voices", "voice"),
    ("/templates", "template"),
    ("/videos", "video"),
    ("/assets", "asset"),
    ("/background-removals", "background_removal"),
    ("/lipsyncs", "lipsync"),
    ("/hyperframes", "hyperframes"),
    ("/brand-kits", "brand_kit"),
    ("/brand-glossaries", "brand_glossary"),
    ("/ai-clipping", "clipping"),
    ("/filler-word-removals", "filler_removal"),
    ("/podcasts", "podcast"),
    ("/workflow-runs", "workflow"),
    ("/workflows", "workflow_definition"),
)
UNSCOPED_CATALOGS = {
    "list_video_agent_styles",
    "search_audio_sounds",
    "search_assets",
    "list_video_translation_languages",
    "get_workflow_node_types",
}
PUBLIC_CATALOGS = {"list_voices", "list_avatar_groups", "list_avatar_looks"}
PRIVATE_METADATA = {
    "owner",
    "username",
    "user_id",
    "space_id",
    "workspace_id",
    "folder_id",
    "api_key",
    "access_token",
    "authorization",
    "upload_url",
    "upload_headers",
    "total",
    "total_count",
    "count",
}
NATIVE_IDS = {
    "avatar": ("id",),
    "look": ("id",),
    "video": ("video_id", "id"),
    "session": ("session_id", "id"),
    "voice": ("voice_id", "voice_clone_id", "id"),
    "professional_voice": ("voice_id", "id"),
    "asset": ("asset_id", "id"),
    "template": ("template_id", "id"),
    "brand_kit": ("brand_kit_id", "id"),
    "brand_glossary": ("brand_glossary_id", "id"),
    "translation": ("video_translation_id", "id"),
    "proofread": ("proofread_id", "id"),
    "lipsync": ("lipsync_id", "id"),
    "hyperframes": ("render_id", "id"),
    "clipping": ("ai_clipping_id", "id"),
    "background_removal": ("id",),
    "filler_removal": ("filler_word_removal_id", "id"),
    "podcast": ("podcast_id", "id"),
    "workflow": ("id",),
    "workflow_definition": ("id",),
    "comparison": ("comparison_id", "id"),
}


def kind_for(row):
    kind = next((kind for path, kind in PATH_KINDS if row["path"].startswith("/v3" + path)), "")
    return kind + "_batch" if "/batches" in row["path"] else kind


def data_of(envelope):
    return envelope.get("data", envelope) if isinstance(envelope, dict) else envelope


def resource_kind(field, family):
    if field == "batch_id":
        return family if family.endswith("_batch") else family + "_batch"
    if field == "job_id":
        return family
    for suffix, kind in RESOURCE_FIELDS.items():
        if field == suffix or field.endswith("_" + suffix):
            if suffix == "voice_id" and family == "professional_voice":
                return family
            return kind
    return None


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if key.lower() not in PRIVATE_METADATA
        }
    return value


class ToolRuntime:
    def __init__(self, api_key, access, *, client=None, username=None, consent_groups=()):
        self.api_key, self.access, self.client = api_key, access, client
        self.username, self.consent_groups = username, frozenset(consent_groups)

    async def upload_batch(self, parameters, task_id):
        """Execute all staging writes under a durable task claim, never retrying writes.

        Uploads are bounded to 100 MiB in aggregate to fit one short transfer step.
        If a transfer is interrupted its receipt remains for operator recovery;
        neither the presign nor finalize operation is automatically recreated.
        """
        params = validate_action("upload_assets_batch", parameters)
        key = "upload:" + task_id
        if not await self.access.mapping.put(key, {"phase": "preflight"}, skip_if_exists=True):
            raise ProviderError(
                "submission_uncertain",
                "This upload was already attempted; "
                "inspect its provider assets before submitting again.",
                ambiguous=True,
            )
        prepared, total = [], 0
        for file in params["body"]["files"]:
            content, mime = await fetch_media(
                file["url"], MAX_FILE_BYTES - total, {file["media_type"]}, self.client
            )
            total += len(content)
            prepared.append((file["name"], mime, content))
        body = {
            "files": [
                {
                    "filename": name,
                    "content_type": mime,
                    "size_bytes": len(content),
                    "checksum_sha256": hashlib.sha256(content).hexdigest(),
                }
                for name, mime, content in prepared
            ]
        }
        if params["body"].get("title"):
            body["title"] = params["body"]["title"]
        await self.access.mapping.put(key, {"phase": "presign_submitting"})
        slots = data_of(await self.request("POST", "/v3/assets/direct-uploads/batches", json=body))
        await self.access.mapping.put(key, {"phase": "uploading", "slots": slots, "uploaded": 0})
        if len(slots.get("items", [])) != len(prepared):
            raise ProviderError(
                "provider_response_invalid",
                "HeyGen returned an invalid upload batch.",
                ambiguous=True,
            )
        await self.access.remember("asset_batch", slots["batch_id"])
        for index, (slot, (_, mime, content)) in enumerate(
            zip(slots["items"], prepared, strict=True)
        ):
            await self.access.remember("asset", slot["asset_id"])
            url, address = await _public_target(slot["upload_url"])
            headers = {
                k: v
                for k, v in slot.get("upload_headers", {}).items()
                if k.lower() in {"content-type", "content-md5"}
                or k.lower().startswith(("x-amz-", "x-ms-", "x-goog-"))
            }
            headers.setdefault("Content-Type", mime)
            headers["Host"] = url.netloc.decode("ascii")
            request = httpx.Request(
                "PUT",
                url.copy_with(host=address),
                content=content,
                headers=headers,
                extensions={"sni_hostname": url.host},
            )
            owned = self.client is None
            client = self.client or httpx.AsyncClient(timeout=60, trust_env=False)
            try:
                response = await client.send(request, auth=None, follow_redirects=False)
                if not response.is_success:
                    raise MediaError("The presigned upload could not be completed.")
            except httpx.HTTPError:
                raise MediaError(
                    "The file upload was interrupted; no automatic upload retry."
                ) from None
            finally:
                if owned:
                    await client.aclose()
            await self.access.mapping.put(
                key, {"phase": "uploading", "slots": slots, "uploaded": index + 1}
            )
        await self.access.mapping.put(
            key, {"phase": "finalize_submitting", "batch_id": slots["batch_id"]}
        )
        result = await self.request(
            "POST", "/v3/assets/complete/batches", json={"batch_id": slots["batch_id"]}
        )
        await self.access.mapping.put(key, {"phase": "processing", "batch_id": slots["batch_id"]})
        return result

    async def request(self, method, path, **kwargs):
        if not self.api_key:
            raise ProviderError("provider_unavailable", "HeyGen credentials are not configured.")
        if not re.fullmatch(r"/v3/[A-Za-z0-9_./-]+", path) or ".." in path:
            raise ValueError("Invalid registered provider path.")
        mutation = method != "GET"
        headers = {"X-Api-Key": self.api_key, **kwargs.pop("headers", {})}
        request = httpx.Request(method, API_ORIGIN + path, headers=headers, **kwargs)
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=45, trust_env=False)
        try:
            response = await client.send(request, auth=None, follow_redirects=False)
        except httpx.HTTPError:
            raise ProviderError(
                "submission_ambiguous" if mutation else "provider_unavailable",
                "HeyGen did not confirm the request; no mutation was retried.",
                ambiguous=mutation,
            ) from None
        finally:
            if owned:
                await client.aclose()
        if not response.is_success:
            uncertain = mutation and (
                response.status_code >= 500
                or response.status_code in {408, 409}
                or response.is_redirect
            )
            code = (
                "submission_ambiguous"
                if uncertain
                else "rate_limited"
                if response.status_code == 429
                else "provider_authentication"
                if response.status_code == 401
                else "provider_entitlement"
                if response.status_code == 403
                else "provider_rejected"
            )
            raise ProviderError(
                code,
                f"HeyGen returned HTTP {response.status_code}. "
                "Check action inputs and account access; writes are not retried.",
                ambiguous=uncertain,
                retry_after=_retry_after(response),
            )
        if response.status_code == 204:
            return {"data": {"deleted": True}}
        try:
            value = response.json()
            if not isinstance(value, (dict, list)):
                raise ValueError
            if isinstance(value, dict) and value.get("error"):
                raise ValueError
            return value if isinstance(value, dict) else {"data": value}
        except ValueError:
            raise ProviderError(
                "submission_ambiguous" if mutation else "provider_response_invalid",
                "HeyGen returned an invalid response.",
                ambiguous=mutation,
            ) from None

    async def require(self, kind, identifier, *, write=False):
        if await self.access.allowed(kind, identifier, write=write):
            return
        if not write and IDENTIFIER.fullmatch(str(identifier)):
            if await self.access.mapping.get(f"catalog:{kind}:{identifier}"):
                return
        await self.access.require(kind, identifier, write=write)

    async def authorize(self, value, family, *, write=False):
        """Inspect nested native IDs (including literal workflow bindings) before dispatch."""
        if isinstance(value, list):
            for item in value:
                await self.authorize(item, family, write=write)
        elif isinstance(value, dict):
            for key, item in value.items():
                singular = key[:-1] if key.endswith("_ids") else key
                target = resource_kind(singular, family)
                if target and item not in (None, "", []):
                    ids = item if isinstance(item, list) else str(item).split(",")
                    for identifier in ids:
                        await self.require(target, identifier, write=write)
                else:
                    await self.authorize(item, family, write=write)

    async def _media_inputs(self, value):
        if isinstance(value, list):
            for item in value:
                await self._media_inputs(item)
        elif isinstance(value, dict):
            if value.get("type") == "base64" and "data" in value:
                try:
                    raw = base64.b64decode(value["data"], validate=True)
                except ValueError:
                    raise MediaError("Invalid base64 media.") from None
                if len(raw) > MAX_FILE_BYTES:
                    raise MediaError("The file exceeds the permitted size.")
                inspect_media(raw, {value.get("media_type")})
            for key, item in value.items():
                if isinstance(item, str) and (key == "url" or key.endswith("_url")):
                    await _public_target(item)
                elif key != "data":
                    await self._media_inputs(item)

    async def _typed_value(self, value, type_name):
        if type_name in {"video", "audio", "image", "avatar"} and isinstance(value, str):
            await self.require("look" if type_name == "avatar" else "asset", value)
        else:
            await self.authorize(value, "workflow")
            await self._media_inputs(value)

    async def _workflow_graph(self, graph, inputs=None):
        if not isinstance(graph, dict):
            raise AccessDenied("The workflow graph could not be inspected.")
        declarations = graph.get("inputs", {})
        for name, value in (inputs or {}).items():
            if name not in declarations:
                raise ValueError("A workflow input is not declared in the selected version.")
            await self._typed_value(value, declarations[name]["type"])
        nodes = graph.get("nodes", [])
        if not nodes:
            return False
        catalog = data_of(await self.request("GET", "/v3/workflows/node-types"))
        variants = {
            (family["family"], variant.get("variant")): variant
            for family in catalog.get("families", [])
            for variant in family.get("variants", [])
        }
        video_ports = set()
        for node in nodes:
            row = variants.get((node["type"], node.get("variant")))
            if row is None:
                candidates = [v for (family, _), v in variants.items() if family == node["type"]]
                row = candidates[0] if len(candidates) == 1 and not node.get("variant") else None
            if row is None or re.search(
                r"live|realtime|consent|webhook|http|credential", node["type"], re.I
            ):
                raise AccessDenied("This workflow node is not a verifiable finite media operation.")
            video_ports.update(
                (node["id"], port["name"])
                for port in row.get("output_ports", [])
                if port.get("type") == "video"
            )
            config = node.get("config", {})
            schema = row.get("config_schema", {})

            # No external schema resolution, including from provider-controlled schema metadata.
            def external_refs(value):
                if isinstance(value, dict):
                    if "$ref" in value and not value["$ref"].startswith("#"):
                        return True
                    return any(external_refs(v) for v in value.values())
                return isinstance(value, list) and any(external_refs(v) for v in value)

            if external_refs(schema) or not Draft202012Validator(schema).is_valid(config):
                raise ValueError(
                    "The workflow node config does not match its inspectable provider schema."
                )
            await self.authorize(config, "workflow")
            await self._media_inputs(config)
            ports = {p["name"]: p for p in row.get("input_ports", [])}
            for name, binding in node.get("bindings", {}).items():
                if name not in ports:
                    raise ValueError("The workflow binding names an unknown input port.")
                if binding.get("kind", "literal") == "literal":
                    await self._typed_value(binding.get("value"), ports[name]["type"])
                else:
                    await self.authorize(binding, "workflow")
                    await self._media_inputs(binding)
        return any(
            (output.get("node_id"), output.get("port")) in video_ports
            for output in graph.get("outputs", {}).values()
            if isinstance(output, dict)
        )

    async def _workflow_input(self, action, body):
        if action in {"create_workflow", "update_workflow_draft", "publish_workflow_version"}:
            graph = body.get("product_graph")
            if graph is not None:
                await self._workflow_graph(graph)
        if action != "create_workflow_run":
            return
        root = "/v3/workflows/" + body["workflow_id"] + "/versions"
        if not body.get("version_number"):
            versions, token = [], None
            for _ in range(10):
                envelope = await self.request(
                    "GET", root, params={"limit": 100, **({"token": token} if token else {})}
                )
                data = data_of(envelope)
                rows = (
                    data if isinstance(data, list) else data.get("items", data.get("versions", []))
                )
                versions.extend(v["version_number"] for v in rows)
                token = envelope.get("next_token") or (
                    data.get("next_token") if isinstance(data, dict) else None
                )
                if not token:
                    break
            if token or not versions:
                raise ValueError(
                    "Supply an explicit published workflow version_number to verify this run."
                )
            body["version_number"] = max(versions)
        version = data_of(await self.request("GET", root + "/" + str(body["version_number"])))
        if not await self._workflow_graph(version.get("product_graph"), body.get("inputs")):
            raise ValueError(
                "Workflow execution requires a declared final video output under video-second "
                "pricing. Standalone non-video workflows are disabled until separately priced."
            )

    async def _filter(self, value, kind, public=False):
        if isinstance(value, list):
            result = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                identifiers = (
                    ("batch_id", "id") if kind.endswith("_batch") else NATIVE_IDS.get(kind, ("id",))
                )
                identifier = next((item[k] for k in identifiers if item.get(k)), None)
                is_public = bool(public)
                if is_public and IDENTIFIER.fullmatch(str(identifier)):
                    await self.access.mapping.put(f"catalog:{kind}:{identifier}", True)
                if is_public or (identifier and await self.access.allowed(kind, identifier)):
                    result.append(sanitize(item))
            return result
        if isinstance(value, dict):
            return {
                key: await self._filter(item, kind, public)
                if isinstance(item, list) or key == "data"
                else sanitize(item)
                for key, item in value.items()
                if key not in PRIVATE_METADATA
            }
        return value

    async def remember_result(self, action, result):
        row = operations()[action]
        value = data_of(result)
        if not isinstance(value, dict):
            return
        if action == "design_voice":
            for voice in value.get("voices", []):
                identifier = voice.get("voice_id")
                if identifier and IDENTIFIER.fullmatch(identifier):
                    await self.access.mapping.put(f"catalog:voice:{identifier}", True)
            return
        if not (
            action.startswith("create_")
            or action
            in {
                "clone_voice",
                "generate_from_template",
                "generate_from_proofread",
                "upload_asset",
            }
        ):
            return  # Updates echo references; only creation outputs may assign ownership.
        kind = row["completion"]
        if kind in {"snapshot", "mutation"}:
            kind = kind_for(row)
        identifiers = ("batch_id",) if kind.endswith("_batch") else NATIVE_IDS.get(kind, ("id",))
        for field in identifiers:
            for key in (field, field + "s" if field.endswith("_id") else field):
                item = value.get(key)
                for identifier in item if isinstance(item, list) else [item]:
                    if isinstance(identifier, str) and not await self.access.mapping.get(
                        f"catalog:{kind}:{identifier}"
                    ):
                        await self.access.remember(kind, identifier)
        if action == "create_avatar":
            for key, target in [("avatar_item", "look"), ("avatar_group", "avatar")]:
                if isinstance(value.get(key), dict) and value[key].get("id"):
                    identifier = value[key]["id"]
                    if not await self.access.mapping.get(f"catalog:{target}:{identifier}"):
                        await self.access.remember(target, identifier)
        if action == "create_video_agent" and value.get("video_id"):
            await self.access.remember("video", value["video_id"])

    async def execute(self, action, parameters, *, task_id=""):
        row = operations().get(action)
        if not row or row["access"] != "public":
            raise AccessDenied("This operation is reserved for the account operator.")
        params = copy.deepcopy(validate_action(action, parameters))
        # Apply controlled defaults at dispatch, not acceptance: existing allowed
        # requests must keep the same persisted idempotency fingerprint on upgrade.
        apply_render_defaults(action, params)
        family = kind_for(row)
        # Reading a resource for generation is allowed; editing/deleting requires ownership.
        path_write = row["method"] in {"PATCH", "PUT", "DELETE"} or action in {
            "send_video_agent_message",
            "stop_video_agent_session",
            "publish_workflow_version",
            "cancel_workflow_run",
        }
        await self.authorize(params.get("path", {}), family, write=path_write)
        await self.authorize(params.get("query", {}), family)
        await self.authorize(params.get("body", {}), family)
        await self._media_inputs(params)
        body = params.get("body", {})
        await self._workflow_input(action, body)
        if action == "create_avatar" and body.get("avatar_group_id"):
            await self.require("avatar", body["avatar_group_id"], write=True)
        if action == "create_avatar" and body.get("avatar_id"):
            look = data_of(await self.request("GET", "/v3/avatars/looks/" + body["avatar_id"]))
            await self.require("avatar", look.get("group_id"), write=True)
        if action == "create_avatar" and body.get("type") == "digital_twin":
            group = body.get("avatar_group_id")
            if group not in self.consent_groups:
                raise ProviderError(
                    "prerequisite_required",
                    "Digital twins require an operator-verified "
                    "consent-approved group. Interactive consent is excluded.",
                )
        if action == "create_model_audio_voice" and body.get("voice_id"):
            await self.require("professional_voice", body["voice_id"], write=True)
        path = row["path"]
        for key, identifier in params.get("path", {}).items():
            if not IDENTIFIER.fullmatch(str(identifier)):
                raise AccessDenied("Invalid resource identifier.")
            path = path.replace("{" + key + "}", str(identifier))
        query = params.get("query", {})
        if action == "list_assets":
            if not self.username:
                # No configured account name is needed to list only known, owned IDs.
                items = []
                for owned in (await self.access.owned("asset"))[:100]:
                    items.append(data_of(await self.request("GET", "/v3/assets/" + owned["id"])))
                return {"data": sanitize(items), "has_more": False}
            query["username"] = self.username
        if action == "list_voices":
            query.setdefault("type", "public")
        elif action in {"list_avatar_groups", "list_avatar_looks"}:
            query.setdefault("ownership", "public")
        if action == "create_video_agent":
            body["mode"] = "generate"
        if action == "create_background_removal":
            body["request_id"] = task_id
        kwargs = {"params": query} if query else {}
        if "body" in params:
            kwargs["json"] = body
        if row.get("supports_idempotency") and task_id:
            kwargs["headers"] = {"Idempotency-Key": task_id}
        if row.get("transport") == "multipart_file":
            descriptor = body["file"]
            data, mime = await fetch_media(
                descriptor["url"], MAX_FILE_BYTES, {descriptor["media_type"]}, self.client
            )
            kwargs.pop("json", None)
            kwargs["files"] = {"file": (descriptor["name"], data, mime)}
        if row.get("transport") == "upload_batch":
            raise ValueError("Batch upload requires the durable upload workflow adapter.")
        result = await self.request(row["method"], path, **kwargs)
        if row["method"] == "DELETE":
            for key, identifier in params.get("path", {}).items():
                target = RESOURCE_FIELDS.get(key, family)
                if target == "voice" and family == "professional_voice":
                    target = family
                await self.access.forget(target, identifier)
        elif row["mutation"]:
            await self.remember_result(action, result)
        if action == "search_assets" and query.get("scope") == "personal":
            return await self._filter(result, "asset")
        if action.startswith("list_") and action not in UNSCOPED_CATALOGS:
            # Child listings are already authorized through their parent path ID.
            if not params.get("path"):
                public = action in PUBLIC_CATALOGS and (
                    query.get("ownership") == "public" or query.get("type") == "public"
                )
                return await self._filter(result, family, public)
        return sanitize(result)
