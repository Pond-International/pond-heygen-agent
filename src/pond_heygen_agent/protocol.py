"""Pond V1 inputs and the chat agent's self-contained discovery guide."""

import copy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from . import __version__
from .media_files import SUPPORTED_MEDIA
from .render_policy import MANAGED_COST_NOTE
from .tool_registry import action_manifest, operations, validate_action

MAX_REQUEST_BYTES = 65536
MAX_RUN_SECONDS = 1800
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
INPUT_TYPES = {"image/png", "image/jpeg", "application/pdf"}
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class InputError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Common(Strict):
    target_duration_seconds: int = Field(
        30,
        ge=5,
        le=60,
        description="Target length: default 30 seconds; 5-60 seconds allowed. "
        "For a quick test use 10. Actual render length varies; this is not a hard spending cap. "
        "For scripted videos, supply text of suitable spoken length; it is never shortened.",
    )
    language: Text = Field(
        "English",
        max_length=80,
        description="Spoken language, e.g. English "
        "or Spanish. For presenter videos the supplied script must already be "
        "in this language; no translation is performed.",
    )
    orientation: Literal["landscape", "portrait"] = Field(
        "landscape",
        description="landscape for presentations/YouTube (16:9), portrait for "
        "mobile/social (9:16). Default landscape; collect the destination when known.",
    )
    avatar_id: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        description="Optional "
        "verified presenter LOOK ID from the presets listed here. "
        "Never invent an ID or use a group ID. Omit for the default.",
    )
    voice_id: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        description="Optional "
        "verified voice ID from the presets listed here. Omit to use "
        "a public voice compatible with the requested language.",
    )


class BriefParameters(Common):
    brief: Text = Field(
        max_length=8000,
        description="Self-contained description of the video. "
        "A broad but usable idea is enough. Include what is being presented and "
        "why it matters; for 'promote our product', collect the product's purpose "
        "and benefits before dispatch. Preserve facts and must-haves; do not "
        "invent product claims, statistics, prices, or testimonials. HeyGen writes "
        "the script and scenes. Use the presenter action for exact spoken text.",
    )
    audience: Text | None = Field(
        None,
        max_length=500,
        description="Who will watch and their "
        "familiarity with the topic. Optional; reuse conversation context.",
    )
    purpose: Text | None = Field(
        None,
        max_length=500,
        description="Desired outcome such as explain, introduce, onboard, or promote. Optional.",
    )
    key_messages: list[Annotated[Text, Field(description="One factual point to communicate.")]] = (
        Field(
            default_factory=list,
            max_length=10,
            description="Up to ten factual points to communicate, ordered "
            "by importance. Helpful but optional; do not fabricate facts.",
        )
    )
    tone: Text | None = Field(
        None,
        max_length=500,
        description="Delivery tone, e.g. warm and "
        "professional or energetic. Optional; let HeyGen choose if unknown.",
    )
    visual_style: Text | None = Field(
        None,
        max_length=1500,
        description="Optional art direction: "
        "colors, branding, typography, motion, backgrounds, and vibe. "
        "Explain how any attached images/PDF should be used.",
    )
    call_to_action: Text | None = Field(
        None,
        max_length=500,
        description="Optional closing instruction, URL, or next step; use the user's real details.",
    )


class PresenterParameters(Common):
    script: str = Field(
        min_length=1,
        max_length=1000,
        description="Exact final spoken script, "
        "already in the selected language. It is not rewritten. Pond may draft "
        "it with the user before submitting. Aim roughly 60-75 English words for "
        "30 seconds or up to 150 for 60; language and delivery affect timing. "
        "Use spoken words only, not scene directions or an unfinished outline.",
    )
    presenter: Literal["avatar", "portrait"] = Field(
        "avatar",
        description="avatar uses an "
        "existing verified presenter; portrait "
        "animates exactly one attached image.",
    )
    portrait_permission: bool = Field(
        False,
        description="Required true for portrait mode only. "
        "Confirm the user owns or has permission to animate the "
        "pictured person. Do not infer permission from an upload.",
    )


class User(Strict):
    id: Text
    locale: Text
    timezone: Text


class File(Strict):
    url: str = Field(pattern=r"^https://", max_length=8192)
    name: Text = Field(max_length=255)
    media_type: Literal[
        "image/png",
        "image/jpeg",
        "application/pdf",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "audio/wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "application/json",
        "application/x-subrip",
        "text/vtt",
        "application/zip",
    ]


class TextPart(Strict):
    type: Literal["text"]
    text: Text = Field(max_length=12000)


class FilePart(Strict):
    type: Literal["file"]
    file: File


class Message(Strict):
    id: Text
    role: Literal["user"]
    created_at: str = Field(
        pattern=r"^\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)$"
    )
    parts: list[Annotated[TextPart | FilePart, Field(discriminator="type")]] = Field(
        min_length=1, max_length=16
    )


class Execution(Strict):
    accepted_output_modes: list[Text] = Field(min_length=1)
    deadline_ms: int = Field(ge=1, le=MAX_RUN_SECONDS * 1000)


class RunRequest(Strict):
    run_id: Text = Field(max_length=255)
    agent_id: Text = Field(max_length=255)
    conversation_id: Text = Field(max_length=255)
    history_truncated: bool
    action_id: Text
    user: User
    messages: list[Message] = Field(min_length=1, max_length=1)
    parameters: dict
    execution: Execution


PARAMETERS = {"generate_video": BriefParameters, "generate_presenter_video": PresenterParameters}


def normalize(body: dict) -> dict:
    try:
        run = RunRequest.model_validate(body)
    except ValidationError as error:
        raise InputError(
            "invalid_request", "The request does not match Pond Protocol V1.", 400
        ) from error
    if run.action_id not in PARAMETERS:
        row = operations().get(run.action_id)
        if not row or row["access"] != "public":
            raise InputError("unsupported_operation", "Choose an advertised action.", 400)
        if "application/json" not in run.execution.accepted_output_modes:
            raise InputError(
                "invalid_input",
                "Native actions require application/json output "
                "for resource metadata, plus the desired media types from /manifest.",
            )
        if len(set(run.execution.accepted_output_modes)) != len(
            run.execution.accepted_output_modes
        ):
            raise InputError("invalid_input", "accepted_output_modes must be unique.")
        if any(isinstance(p, FilePart) for p in run.messages[0].parts):
            raise InputError(
                "invalid_input",
                "For native actions, put each file URL or asset_id "
                "in its documented body field; message attachments are not inferred.",
            )
        try:
            parameters = validate_action(run.action_id, run.parameters)
        except ValueError as error:
            raise InputError("invalid_input", str(error)) from error
        result = run.model_dump(mode="json")
        result["parameters"] = parameters
        return result
    if "video/mp4" not in run.execution.accepted_output_modes:
        raise InputError("invalid_input", "Include video/mp4 in accepted_output_modes.")
    if len(set(run.execution.accepted_output_modes)) != len(run.execution.accepted_output_modes):
        raise InputError("invalid_request", "accepted_output_modes must be unique.", 400)
    try:
        params = PARAMETERS[run.action_id].model_validate(run.parameters)
    except ValidationError as error:
        fields = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
        raise InputError("invalid_input", "Check these parameters: " + ", ".join(fields)) from error
    files = [p.file for p in run.messages[0].parts if isinstance(p, FilePart)]
    if any(file.media_type not in INPUT_TYPES for file in files):
        raise InputError("invalid_input", "Convenience actions accept PNG/JPEG/PDF only.")
    if len(files) > 5:
        raise InputError("invalid_input", "Attach at most five files (20 MiB total).")
    if isinstance(params, PresenterParameters):
        if not params.script.strip():
            raise InputError("invalid_input", "Provide a non-empty final script.")
        if params.presenter == "portrait":
            if not params.portrait_permission or len(files) != 1:
                raise InputError(
                    "invalid_input", "Portrait mode requires permission and one image."
                )
            if files[0].media_type not in {"image/png", "image/jpeg"} or params.avatar_id:
                raise InputError(
                    "invalid_input", "Portrait mode takes PNG/JPEG, without avatar_id."
                )
        elif files:
            raise InputError("invalid_input", "Use portrait mode to animate an attached image.")
    result = run.model_dump(mode="json")
    result["parameters"] = params.model_dump(mode="json", exclude_none=True)
    return result


def _schema(model, presets):
    schema = copy.deepcopy(model.model_json_schema())
    for name, prop in schema["properties"].items():
        prop.pop("title", None)
        if "anyOf" in prop:
            value = next(p for p in prop.pop("anyOf") if p.get("type") != "null")
            prop.update(value)
            prop.pop("default", None)
        if name in {"avatar_id", "voice_id"}:
            entries = presets.get("avatars" if name == "avatar_id" else "voices", [])
            if entries:
                prop["enum"] = [p["id"] for p in entries]
                prop["description"] += (
                    " Available: " + "; ".join(f"{p['name']} = {p['id']}" for p in entries) + "."
                )
    schema.pop("title", None)
    return schema


def manifest(presets=None):
    from .nonvideo_policy import POLICY_NOTE
    from .video_usage import PRICING_PLAN

    presets = presets or {}
    brief = _schema(BriefParameters, presets)
    presenter = _schema(PresenterParameters, presets)
    brief["examples"] = [
        {
            "brief": "Introduce our appointment app for small salons: clients book "
            "online, reminders reduce missed appointments, and owners save time.",
            "audience": "Salon owners",
            "target_duration_seconds": 30,
            "orientation": "portrait",
            "tone": "Friendly and practical",
        }
    ]
    presenter["examples"] = [
        {"script": "Welcome to our team. We are glad you are here."},
        {
            "script": "Hello, and welcome to today's update.",
            "presenter": "portrait",
            "portrait_permission": True,
        },
    ]
    return {
        "protocol": "marketplace-agent",
        "protocol_version": "1.0",
        "agent_version": __version__,
        "metadata": {
            "pricing_plans": [dict(PRICING_PLAN)],
            "name": "HeyGen Media Agent",
            "category": "content",
            "short_description": "One-shot HeyGen video generation, editing, and media tools.",
            "description": "<p>Finite HeyGen tools: video generation and revisions, "
            "avatar/voice catalogs, video translations, existing subtitles, lipsync, editing, "
            "assets, "
            "brands, templates, batches, "
            "and workflows. Each action finishes within one Pond task, with metadata and completed "
            "files. Live-avatar sessions and interactive consent flows are excluded. Some tools "
            "require account entitlements or already verified assets; see each action.</p>"
            "<p>" + POLICY_NOTE + "</p>"
            "<p>For a strong first cut, include audience, purpose, facts, destination, language, "
            "visual style, and a call to action when known. Broad usable briefs are welcome; "
            "optional preferences are not a mandatory questionnaire. Uploaded portraits should "
            "show one clear, front-facing, well-lit face. Permission is required.</p>"
            "<p>Files and instructions go to the operator's HeyGen account. Convenience actions "
            "disable session memory; native Video Agent tasks use their incognito_mode setting. "
            "Neither overrides HeyGen's retention policy. Requested duration is "
            "approximate. Provider charges may apply even when a Pond request expires.</p>",
            "setup_instructions": "Choose an action and read its entire schema and guide. "
            "Native parameters use path/query/body, and confirm/rights_confirmed where required. "
            "Collect missing essentials before dispatch; creative preferences are optional. "
            "Catalog/private IDs must be real, owned by this Pond user, or operator-shared. "
            "Native actions require application/json in accepted_output_modes; add desired media "
            "types (video/mp4, video/webm, audio/mpeg, audio/wav, audio/mp4, audio/ogg, image/png, "
            "image/jpeg, application/x-subrip, text/vtt). Put native file inputs in body fields, "
            "not message attachments. Result metadata states partial failures and limitations. "
            "No account administration, subscriptions, or consent approvals occur automatically. "
            "The two convenience actions still accept a self-contained brief, "
            "or a complete script and presenter choice. Ask only for missing essential facts or "
            "portrait permission. Never invent catalog IDs. Default to English, landscape, and "
            "a 30-second target. Reference PNG/JPEG/PDF files belong in message file parts, not "
            "invented parameter keys. Portrait mode needs exactly one PNG/JPEG. Request video/mp4 "
            "and allow 1800000 ms; poll the task until terminal. No user input is possible after "
            "submission. Save/download the returned MP4 within seven days. Configure the saved "
            "Pond plan as pay_as_you_go, amount_minor=13, usage_quantity=1, usage_unit=other, "
            "custom_usage_unit=video_second ($0.13 per actual completed video second). "
            "Sum distinct completed video outputs and round up once per run. Requested duration "
            "is not the billed duration. A 30-second output costs $3.90; 60 seconds costs $7.80. "
            "Alternate encodings, captioned versions, background layers, and repeat polling "
            "are not charged again. Catalogs, status reads and downloads report zero video "
            "seconds. JSON-only delivery of a newly generated video still counts its duration. "
            "Partial success counts only completed outputs; failed/expired tasks report zero. "
            "Unknown actual duration causes usage_unavailable rather than a guessed charge. "
            "Manifest pricing only prefills Pond; save the marketplace plan separately. "
            "Historical tasks retain their original usage. Files last seven days; provider charges "
            "can apply to failed/expired tasks. Professional retraining outcomes cannot be proven "
            "by the documented API and are never falsely reported successful. "
            "Explicit video settings are restricted to 720p and Avatar III/IV. Translation "
            "and lipsync use speed mode. HyperFrames permits draft/standard at 1080p, its "
            "lowest supported resolution. Use only the allowed schema values; unsupported "
            "options are rejected before submission, not silently downgraded. "
            + MANAGED_COST_NOTE
            + " "
            + POLICY_NOTE,
        },
        "actions": [
            {
                "id": "generate_video",
                "name": "Video from Brief",
                "description": "Use for a "
                "new video from an idea or brief, including scripting and visual composition. "
                "Collect the subject and real facts; optionally audience, purpose, style, and CTA. "
                "HeyGen makes remaining creative choices in one pass. PNG/JPEG/PDF references may "
                "guide content and visuals; do not use this action to animate a specific face. "
                + MANAGED_COST_NOTE,
                "input_schema": brief,
            },
            {
                "id": "generate_presenter_video",
                "name": "Scripted Presenter or Talking Photo",
                "description": "Use when exact spoken words and a talking presenter are wanted. "
                "Provide the final script; use a listed avatar or portrait mode with one permitted "
                "PNG/JPEG. Pond can draft the script before calling. No rewriting, translation, "
                "multi-scene direction, persistent avatar creation, or later approval step. "
                "Output is 720p; stock-avatar generation explicitly uses Avatar IV.",
                "input_schema": presenter,
            },
        ]
        + action_manifest(),
        "capabilities": {
            "sync": False,
            "streaming": False,
            "async_tasks": True,
            "cancellation": False,
            "attachments": True,
            "feedback": False,
        },
        "input_modes": ["text/plain", *SUPPORTED_MEDIA],
        "output_modes": list(SUPPORTED_MEDIA),
        "limits": {
            "max_request_bytes": MAX_REQUEST_BYTES,
            "max_attachment_bytes": MAX_ATTACHMENT_BYTES,
            "max_run_seconds": MAX_RUN_SECONDS,
        },
    }
