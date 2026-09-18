"""Offline finite HeyGen v3 registry compiled from a checked-in official snapshot.

Native path/query/body boundaries are retained. Authentication, callback delivery,
idempotency headers, ownership, and execution belong to the operator runtime.
"""

import copy
import json
import re
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator

from .manifest_schema import pond_schema
from .nonvideo_policy import DISABLED_ACTIONS, DISABLED_REASON, restrict_nonvideo_schemas
from .render_policy import restrict_schemas
from .tool_guides import action_guide

METHODS = {"get", "post", "put", "patch", "delete"}
FORBIDDEN_FIELDS = frozenset(
    {
        "callback_url",
        "callback_id",
        "webhook_url",
        "headers",
        "header",
        "authorization",
        "authentication",
        "auth",
        "api_key",
        "apikey",
        "x_api_key",
        "access_token",
        "refresh_token",
        "idempotency_key",
        "cookies",
        "cookie",
    }
)
INTERNAL_UPLOADS = {
    "create_asset_upload",
    "complete_asset_upload",
    "create_asset_upload_batch",
    "complete_asset_batch",
}
COMPLETIONS = {
    "design_voice": "snapshot",
    "create_video": "video",
    "generate_from_template": "video",
    "create_video_agent": "session",
    "send_video_agent_message": "session",
    "create_avatar": "avatar",
    "clone_voice": "voice",
    "create_model_audio_voice": "professional_voice",
    "create_speech": "speech",
    "generate_model_speech": "speech",
    "create_brand_kit": "brand_kit",
    "create_video_translation": "translation",
    "generate_from_proofread": "translation",
    "create_proofread": "proofread",
    "create_lipsync": "lipsync",
    "create_hyperframes_render": "hyperframes",
    "create_ai_clipping": "clipping",
    "create_background_removal": "background_removal",
    "create_filler_word_removal": "filler_removal",
    "create_podcast": "podcast",
    "create_workflow_run": "workflow",
    "create_video_batch": "video_batch",
    "create_video_translation_batch": "translation_batch",
    "create_lipsync_batch": "lipsync_batch",
    "create_video_quality_comparison": "comparison",
    "create_video_quality_comparison_batch": "comparison_batch",
    "upload_asset": "asset",
    "upload_assets_batch": "asset_batch",
}
RIGHTS_REQUIRED = {
    "create_avatar",
    "clone_voice",
    "create_model_audio_voice",
    "create_brand_kit",
    "upload_asset",
    "upload_assets_batch",
    "create_video_translation",
    "create_proofread",
    "generate_from_proofread",
    "upload_proofread_srt",
    "create_lipsync",
    "create_background_removal",
    "create_filler_word_removal",
    "create_ai_clipping",
    "create_hyperframes_render",
    "create_video_translation_batch",
    "create_lipsync_batch",
    "create_video_quality_comparison",
    "create_video_quality_comparison_batch",
}
FILE_DESCRIPTOR = {
    "type": "object",
    "additionalProperties": False,
    "description": "A Pond file descriptor. The operator fetches and validates the bytes before "
    "uploading them to HeyGen. Use a public HTTPS URL that remains valid during the run; "
    "supply the real filename and MIME type. Runtime transfer limits also apply.",
    "properties": {
        "url": {
            "type": "string",
            "pattern": "^https://",
            "maxLength": 8192,
            "description": "HTTPS download URL for the actual file, not a sharing-page URL.",
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": "Original filename including its extension.",
        },
        "media_type": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": "Actual MIME type, such as video/mp4 or audio/mpeg.",
        },
    },
    "required": ["url", "name", "media_type"],
}


def _action_id(operation_id):
    operation_id = re.sub(r"V3$", "", operation_id)
    operation_id = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", operation_id)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", operation_id).lower()


def _forbidden(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    return re.sub(r"[^a-z0-9]", "_", name.lower()) in FORBIDDEN_FIELDS


def _classification(path, action_id, tags):
    if not path.startswith("/v3/"):
        return "legacy", "Legacy v1/v2 operation; use the corresponding finite v3 action."
    if path.startswith("/v3/avatar-realtime"):
        return "excluded", "Live-avatar sessions require an ongoing stream and are outside scope."
    if path.endswith("/consent"):
        return "excluded", "Consent-link handoffs require a human step and are outside scope."
    if action_id in DISABLED_ACTIONS:
        return "disabled", DISABLED_REASON
    if action_id == "stream_model_speech":
        return "covered", "Completed audio is provided by generate_model_speech; no live stream."
    if action_id in INTERNAL_UPLOADS:
        return "internal", "Upload plumbing is completed by upload_asset or upload_assets_batch."
    if set(tags) & {"User", "Webhooks", "Billing", "Account"}:
        return "operator", "Account information and webhook administration are operator-only."
    return (
        "public",
        "Available as a finite Pond task with a complete result or intentional snapshot.",
    )


class _Compiler:
    def __init__(self, source):
        self.source = source
        self.defs = {}

    def schema(self, value):
        """Preserve JSON Schema constraints while relocating reachable local references."""
        if isinstance(value, list):
            return [self.schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key == "$ref":
                prefix = "#/components/schemas/"
                if not item.startswith(prefix):
                    raise ValueError("The pinned schema contains an unsupported reference.")
                name = item.removeprefix(prefix)
                result[key] = "#/$defs/" + name
                if name not in self.defs:
                    self.defs[name] = {}  # Reserve before recursion for recursive native schemas.
                    self.defs[name] = self.schema(self.source["components"]["schemas"][name])
            elif key == "properties":
                result[key] = {
                    name: self.schema(prop) for name, prop in item.items() if not _forbidden(name)
                }
            elif key == "discriminator":
                result[key] = copy.deepcopy(item)
                if "mapping" in result[key]:
                    result[key]["mapping"] = {
                        name: ref.replace("#/components/schemas/", "#/$defs/")
                        for name, ref in result[key]["mapping"].items()
                    }
            elif key == "required":
                result[key] = [name for name in item if not _forbidden(name)]
            else:
                result[key] = self.schema(item)
        return result


def _dereference(schema, definitions):
    if "$ref" not in schema:
        return schema
    return {
        **definitions[schema["$ref"].removeprefix("#/$defs/")],
        **{key: value for key, value in schema.items() if key != "$ref"},
    }


def _object(properties, required=()):
    result = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        result["required"] = list(required)
    return result


def _parameters(source, path_item, operation):
    result = []
    for param in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        if "$ref" in param:
            prefix = "#/components/parameters/"
            if not param["$ref"].startswith(prefix):
                raise ValueError(
                    "The pinned operation contains an unsupported parameter reference."
                )
            param = source["components"]["parameters"][param["$ref"].removeprefix(prefix)]
        result.append(param)
    return result


def _local_refs(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"].removeprefix("#/$defs/")
        for child in value.values():
            yield from _local_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _local_refs(child)


def _reachable_definitions(schema, definitions):
    pending, reachable = set(_local_refs(schema)), {}
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable[name] = definitions[name]
        pending.update(_local_refs(definitions[name]))
    return {name: reachable[name] for name in sorted(reachable)}


def _compile_input(source, path_item, operation, row):
    compiler = _Compiler(source)
    properties, required = {}, []
    for location in ("path", "query"):
        params, required_params = {}, []
        for param in _parameters(source, path_item, operation):
            if param.get("in") != location or _forbidden(param["name"]):
                continue
            if row["id"] == "list_assets" and param["name"] == "username":
                continue
            schema = compiler.schema(param.get("schema", {}))
            if param.get("description"):
                schema["description"] = param["description"]
            params[param["name"]] = schema
            if param.get("required"):
                required_params.append(param["name"])
        if params:
            properties[location] = _object(params, required_params)
            if required_params:
                required.append(location)
    request = operation.get("requestBody", {})
    content = request.get("content", {})
    if content:
        media_type = "application/json" if "application/json" in content else next(iter(content))
        properties["body"] = compiler.schema(content[media_type].get("schema", {}))
        row["request_content_type"] = media_type
        if request.get("required"):
            required.append("body")
    if row["id"] == "upload_asset":
        properties["body"] = _object({"file": copy.deepcopy(FILE_DESCRIPTOR)}, ["file"])
        row["transport"] = "multipart_file"
    if row["id"] == "create_video_agent":
        body = _dereference(properties["body"], compiler.defs)
        body["properties"]["mode"] = {
            "type": "string",
            "const": "generate",
            "default": "generate",
            "description": "One-shot generation only. Chat sessions and human-input pauses "
            "are not supported by this action.",
        }
        properties["body"] = body
    if row["requires_confirm"]:
        properties["confirm"] = {
            "type": "boolean",
            "const": True,
            "description": "Set true only after the user authorizes this operation, its selected "
            "scope, and any provider charges. Required for creations and mutations.",
        }
        required.append("confirm")
    if row["rights_required"]:
        properties["rights_confirmed"] = {
            "type": "boolean",
            "const": True,
            "description": "Confirm that the user has the necessary rights and permission for "
            "the supplied material and any person's image or voice. For entirely generated "
            "fictional material, confirm it is authorized. This is not a consent-link workflow.",
        }
        required.append("rights_confirmed")
    for location in ("path", "query", "body"):
        if location in properties:
            properties[location].setdefault(
                "description",
                {
                    "path": "Exact IDs from permitted previous results; never invent IDs.",
                    "query": "Catalog filters and pagination; omit optional defaults.",
                    "body": "Complete native inputs. Collect required fields and permissions "
                    "before dispatch.",
                }[location],
            )
    result = _object(properties, required)
    result["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    restrict_schemas(result, compiler.defs)
    restrict_nonvideo_schemas(compiler.defs)
    definitions = _reachable_definitions(result, compiler.defs)
    if definitions:
        result["$defs"] = definitions
    return result


@lru_cache(maxsize=1)
def _catalog():
    source = json.loads(files(__package__).joinpath("data/heygen-v3.json").read_text())
    rows, coverage_rows = {}, []
    for path, item in source["paths"].items():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            action_id = _action_id(operation["operationId"])
            tags = operation.get("tags", [])
            classification, reason = _classification(path, action_id, tags)
            preview = bool(operation.get("x-excluded", False))
            if preview:
                reason += (
                    " Marked x-excluded in the pinned schema; account availability is unverified."
                )
            coverage_rows.append(
                {
                    "id": action_id,
                    "operation_id": operation["operationId"],
                    "method": method.upper(),
                    "path": path,
                    "classification": classification,
                    "reason": reason,
                    "provider_preview": preview,
                    "x-excluded": preview,
                }
            )
            if classification not in {"public", "operator", "disabled"}:
                continue
            mutation = method != "get"
            idempotency = [
                param
                for param in _parameters(source, item, operation)
                if param.get("in") == "header" and param["name"].lower() == "idempotency-key"
            ]
            row = {
                "id": action_id,
                "operation_id": operation["operationId"],
                "method": method.upper(),
                "path": path,
                "tags": tags,
                "summary": operation.get("summary", action_id.replace("_", " ").title()),
                "native_description": operation.get("description", ""),
                "access": classification,
                "mutation": mutation,
                "requires_confirm": mutation,
                "rights_required": action_id in RIGHTS_REQUIRED,
                "completion": COMPLETIONS.get(action_id, "mutation" if mutation else "snapshot"),
                "transport": "json",
                "provider_preview": preview,
                "x-excluded": preview,
                "supports_idempotency": bool(idempotency),
                "requires_idempotency": any(param.get("required") for param in idempotency),
                "operator_parameters": ["query.username"] if action_id == "list_assets" else [],
            }
            row["input_schema"] = _compile_input(source, item, operation, row)
            if action_id in rows:
                raise ValueError("The pinned registry contains duplicate action identifiers.")
            rows[action_id] = row
    upload_batch = {
        "id": "upload_assets_batch",
        "operation_id": "uploadAssetsBatchWorkflow",
        "method": "POST",
        "path": "/v3/assets/direct-uploads/batches",
        "tags": ["Asset Batches"],
        "summary": "Upload Asset Files as a Completed Batch",
        "native_description": "Import one to 100 actual files into the asset library. "
        "The operator downloads the files, requests upload slots, transfers the bytes, "
        "finalizes the batch, and waits for every item to settle.",
        "access": "public",
        "mutation": True,
        "requires_confirm": True,
        "rights_required": True,
        "completion": "asset_batch",
        "transport": "upload_batch",
        "synthetic": True,
        "provider_preview": False,
        "x-excluded": False,
        "supports_idempotency": True,
        "requires_idempotency": False,
        "operator_parameters": [],
    }
    upload_batch["input_schema"] = copy.deepcopy(rows["upload_asset"]["input_schema"])
    upload_batch["input_schema"]["properties"]["body"] = _object(
        {
            "files": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": copy.deepcopy(FILE_DESCRIPTOR),
                "description": "Files to transfer and ingest; per-file and aggregate runtime "
                "limits apply. A list of upload slots is not a completed upload.",
            },
            "title": {
                "type": "string",
                "description": "Optional display title for the asset batch.",
            },
        },
        ["files"],
    )
    rows[upload_batch["id"]] = upload_batch
    upload_batch["input_schema"]["properties"]["body"]["description"] = (
        "Files to download, transfer and fully ingest in this task, with an optional batch title."
    )
    coverage_rows.append(
        {
            "id": upload_batch["id"],
            "operation_id": upload_batch["operation_id"],
            "method": upload_batch["method"],
            "path": upload_batch["path"],
            "classification": "synthetic",
            "reason": "Complete native direct-upload batch workflow: "
            "download, presign, PUT bytes, finalize, and wait for asset ingestion.",
        }
    )
    for row in rows.values():
        guide, examples = action_guide(row)
        row["description"] = guide
        row["input_schema"]["examples"] = examples
    return rows, coverage_rows


def operations():
    """Return isolated registry rows, including operator-only operations."""
    return copy.deepcopy(_catalog()[0])


def action_manifest():
    """Return public, finite Pond actions with complete standalone input schemas."""
    return [
        {
            "id": row["id"],
            "name": row["summary"],
            "description": row["description"],
            "input_schema": pond_schema(row["input_schema"]),
        }
        for row in _catalog()[0].values()
        if row["access"] == "public"
    ]


def coverage():
    """Account for every pinned native operation and every synthetic workflow."""
    return copy.deepcopy(_catalog()[1])


def _check_operator_fields(value):
    if isinstance(value, dict):
        for name, child in value.items():
            if _forbidden(name):
                raise ValueError(
                    "Callback, authentication, and header fields are operator-controlled."
                )
            _check_operator_fields(child)
    elif isinstance(value, list):
        for child in value:
            _check_operator_fields(child)


def _error_detail(error):
    # Never echo instance values, unrecognized keys, or provider error text.
    path = [
        str(item) if isinstance(item, int) else re.sub(r"[^a-zA-Z0-9_]", "", item)[:80]
        for item in error.absolute_path
    ]
    if error.validator == "required":
        missing = [key for key in error.validator_value if key not in error.instance]
        if missing:
            path.append(missing[0])
    field = ".".join(path) or "parameters"
    reason = {
        "required": "is required",
        "additionalProperties": "contains unsupported fields",
        "type": "has the wrong type",
        "enum": "must match a documented allowed value",
        "const": "must match the required value",
        "oneOf": "must match one documented variant",
        "anyOf": "must match a documented variant",
        "minimum": "is below the allowed minimum",
        "maximum": "exceeds the allowed maximum",
        "minItems": "needs more items",
        "maxItems": "has too many items",
        "pattern": "has an invalid format",
        "minLength": "is too short",
        "maxLength": "is too long",
    }.get(error.validator, "does not match the documented schema")
    return f"{field} {reason}."


def validate_action(action_id, parameters):
    """Validate without coercion; return a copy normalized for one-shot execution.

    Runtime authorization is separate: this function does not grant access to
    private resources or operator-only actions just because a request validates.
    """
    row = _catalog()[0].get(action_id)
    if row is None:
        raise ValueError("Unsupported action; choose an advertised action identifier.")
    if row["access"] == "disabled":
        raise ValueError(DISABLED_REASON)
    _check_operator_fields(parameters)
    validator = Draft202012Validator(row["input_schema"])
    error = next(validator.iter_errors(parameters), None)
    if error:
        raise ValueError(_error_detail(error))
    result = copy.deepcopy(parameters)
    if action_id == "create_video_agent":
        result["body"]["mode"] = "generate"
    return result
