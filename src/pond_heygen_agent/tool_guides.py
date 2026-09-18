"""Practical, self-contained guides over the official native operation schemas.

Family advice supplies preparation and quality context; native descriptions,
required fields, and operation-specific examples make each action independent.
"""

import copy
import json

from .nonvideo_policy import POLICY_NOTE
from .render_policy import MANAGED_COST_NOTE

# Preparation, ID discovery, and quality/cost guidance genuinely differ by family.
FAMILIES = {
    "Video Agent": (
        "Use a complete brief with the subject, real facts, audience, and intended outcome. "
        "Specify exact wording or visual constraints when they matter. Orientation, a curated "
        "style, and brand settings are optional; omitted creative choices are made by HeyGen.",
        "PNG/JPEG/PDF reference material should clearly support the requested narrative. Native "
        "files accept URL, asset_id, or base64 variants; keep URLs valid throughout the run.",
        "Discover looks with list_avatar_looks, voices with list_voices, styles with "
        "list_video_agent_styles, and brands with list_brand_kits/list_brand_glossaries. "
        "Session/resource IDs must come from this user's earlier results.",
        "Longer briefs can produce longer videos; a requested duration is a creative target, "
        "not a spending cap. New generations and revisions can incur new render charges.",
    ),
    "Brand": (
        "Keep brand names, pronunciations, colors, and legal assets accurate. A glossary may "
        "start with only a unique name; pronunciation changes generated audio while captions "
        "retain spelling. Translation-only glossary terms do not change ordinary narration.",
        "For a brand-kit import, provide a public website you are licensed to use; logos, "
        "fonts, and colors are collected from that site. A glossary itself needs no file.",
        "Use list_brand_kits/get_brand_kit or list_brand_glossaries/get_brand_glossary. "
        "Use existing role assignments and complete term lists when editing an owned brand.",
        "Importing a site takes background processing. Brand settings can improve consistency "
        "without changing source facts; downstream video and translation charges still apply.",
    ),
    "Avatars": (
        "Choose photo for a supplied portrait, digital_twin for authorized footage, or prompt "
        "for a generated character. Keep identity/group IDs separate from individual look IDs. "
        "Prompt aspect_ratio and references are optional; the provider can choose the ratio.",
        "A photo should show one unobscured, well-lit face. Footage should show one speaker "
        "clearly with stable lighting; supply usable original media. Rights confirmation is "
        "required. Existing consent prerequisites must already be satisfied; this task cannot "
        "complete a consent-link handoff.",
        "list_avatar_groups finds identities; list_avatar_looks and get_avatar_look find usable "
        "looks and supported_api_engines. For a shared public avatar, inspect its capabilities "
        "before selecting an engine; mutations require an owned private resource.",
        "Avatar creation and training consume provider resources and may take several minutes. "
        "More reference images can guide appearance; they do not establish permission.",
    ),
    "Voices": (
        "For speech use the final spoken text and a compatible voice. create_speech requires "
        "a starfish-capable voice; plain text and speed 1.0 are useful defaults. For SSML, use "
        'break durations in seconds, such as <break time="0.35s"/>. design_voice searches '
        "for up to three matching voices from a description; clone_voice builds a private clone.",
        "Speech and voice search need no files. Cloning needs a clean recording of one "
        "permitted speaker with little room noise or music. Provide the real audio via a "
        "supported URL/asset_id/base64 variant and confirm the speaker's permission.",
        "Call list_voices with query.engine=starfish for create_speech. Use query.type=private "
        "and get_voice for owned clones. Copy a returned voice ID exactly; never invent one.",
        "Speech cost depends on usage; longer text creates longer audio. Slower speed changes "
        "delivery and duration. Cloning has separate processing costs; semantic voice design "
        "returns candidates whose samples should be evaluated before a full narration.",
    ),
    "Models": (
        "Professional voice creation needs a name, language, professional mode, and recordings. "
        "Retraining uses the existing voice_id plus audio and retains its name/language/mode. "
        "Model speech needs a trained voice, text, and language; seed is optional.",
        "Training recordings must contain at least 20 minutes of the same permitted speaker "
        "across one to ten audio inputs. Prefer clean, consistent speech without music or "
        "other speakers. Model speech itself needs no source file.",
        "Use list_model_audio_voices and get_model_audio_voice. Model-backed voice IDs are "
        "a separate catalog; the voice must be ACTIVE before inference.",
        "Professional creation requires an available purchased slot and consumes the provider's "
        "training allowance. Retraining makes the existing voice unavailable while PENDING. "
        "Longer synthesis text increases inference usage; a seed helps repeat comparisons.",
    ),
    "Videos": (
        "Use type=avatar for a known look and exact script or supplied audio; type=image "
        "animates a permitted picture; type=studio composes ordered whole-frame scenes. "
        "Keep script and supplied audio mutually exclusive. Resolution is 720p; avatar "
        "engines are avatar_iii or avatar_iv (default), including batch and studio inputs. "
        "Aspect ratio, captions, fit, background, and voice settings remain available.",
        "Use one clear face for image animation and clean audio for lipsync. Studio scenes "
        "need accessible source images/videos. Obtain rights to all source material.",
        "Use list_avatar_looks/get_avatar_look for actual look IDs and supported_api_engines; "
        "list_voices for voices; upload_asset/list_assets for owned media. list_videos and "
        "get_video return prior video IDs; get_video_scenes describes their scenes.",
        "Duration, engine, and the number of scenes affect processing and charges. "
        "Use a short script for a first render. Check look compatibility; transparent "
        "WebM requires matting support and cannot also set a background.",
    ),
    "Templates": (
        "Inspect the chosen template before generation, then supply variables matching its "
        "names and types. Keep user facts exact. Title, dimension, fps, captions, scene_ids, "
        "sharing, GIF, and glossary settings are optional native controls.",
        "Prepare accessible images/audio/video only for template variables that require them. "
        "A text-only template needs no file. Match variable media types and aspect ratios.",
        "Use list_templates, then get_template to obtain template_id, editable variables, and "
        "scene IDs. Do not guess variable names; private templates must belong to this user.",
        "Each generation renders a fresh video and can incur charges. Reusing a template "
        "improves layout consistency. Explicit dimensions must fit 1280x720 or 720x1280 "
        "and preserve the template's aspect ratio. Omitted dimensions and internal engines "
        "remain provider-managed. More scenes and longer speech increase work.",
    ),
    "Background Removal": (
        "Provide the source video; optional layers select the background-removal outputs. "
        "Choose this family when isolating an existing video's subject is the requested edit.",
        "Use an accessible source video with a clear subject, stable lighting, and minimal "
        "motion blur. Check the documented layer settings and confirm source-media rights.",
        "Use upload_asset/get_asset for owned source footage, or a direct HTTPS source. "
        "Keep the returned job_id for get_background_removal/list_background_removals.",
        "Longer or larger footage requires more processing. Fine hair, transparent objects, "
        "and heavy blur can make edges less accurate; inspect the generated layers.",
    ),
    "Video Translate": (
        "Translation needs source video and target languages. Only speed mode is supported, "
        "including batches. Input language can be detected; speaker_num, glossaries, "
        "source/target SRT, trim times, and sound controls are optional when supported. "
        "Audio-only translation and new proofread preparation are disabled. An existing "
        "ready proofread can still be edited and rendered into video.",
        "Provide clear speech with visible mouths for visual dubbing; source video and SRT "
        "accept documented URL or asset_id variants. Edited SRT must retain valid sequence "
        "numbers and timestamps. Confirm permission to translate and reproduce the speakers.",
        "Use list_video_translation_languages for accepted language names; proofread input "
        "uses the native documented language codes. Use list_video_translations for jobs, "
        "get_proofread for an owned proofread ID, and list_brand_glossaries for glossary IDs.",
        "Multiple video output languages produce separately metered video seconds. "
        "Trim start_time/end_time only when the user "
        "wants an excerpt. Proofreading and final rendering are distinct processing stages.",
    ),
    "Lipsync": (
        "Use replacement audio and a source video to align mouth movement without translating "
        "the text. Only speed mode is supported, including batches. Native sound, "
        "duration, trim, format, and fps controls remain available.",
        "Use clean final audio, a clearly visible speaker, and timing compatible with the "
        "source. Supply URL or asset_id inputs and permission for both the person and audio.",
        "Source assets come from upload_asset/list_assets. Use list_lipsyncs/get_lipsync "
        "for owned job IDs and results; a video ID is not a lipsync ID.",
        "Processing depends on video length. Dynamic duration can improve fit but changes "
        "timing; preserve format "
        "when required for an existing editing pipeline.",
    ),
    "HyperFrames": (
        "Render an authored HTML/JS composition ZIP. Quality is draft or standard (default), "
        "and resolution is 1080p, the provider's lowest supported tier for this action. "
        "Choose fps, format, aspect_ratio, entry composition, and variable overrides only "
        "when needed. Other defaults are 30 fps, MP4, and 16:9.",
        "The ZIP must contain index.html at its root or the entry path specified in "
        "composition, together with its required scripts and assets. Submit as URL, asset_id, "
        "or base64 with application/zip; verify the project before sending it.",
        "Use upload_asset/get_asset for an owned project archive; retain render_id from "
        "creation and inspect it with get_hyperframes_render/list_hyperframes_renders.",
        "Draft/standard quality and the baseline 1080p tier remain available. Confirm "
        "current account pricing before spending. High frame rate and duration increase work.",
    ),
    "Audio": (
        "Describe the mood, instrumentation, tempo, or sound event in query.query. "
        "query.type selects music or sound_effects; min_score and limit tune relevance.",
        "No input file is required. Review returned previews and licensing metadata before "
        "incorporating a sound into a production.",
        "Use returned search records and their media identifiers or URLs; do not fabricate "
        "a music ID. Follow the returned pagination token to continue the same search.",
        "A tighter query and higher min_score improve precision but may return fewer matches. "
        "Searching supplies candidates; downstream media generation has separate costs.",
    ),
    "Assets": (
        "Search finds image/icon candidates; upload imports actual bytes for reuse; list/get "
        "inspect owned media. A source URL must link to the file itself. Preserve the real "
        "filename and media_type when using the complete upload action.",
        "Use supported, intact images, audio, videos, documents, subtitles, or project archives. "
        "The operator checks file bytes and enforces transfer-size limits; a sharing page or "
        "local file path is not a downloadable file. Confirm upload rights.",
        "Use upload_asset's completed asset_id in later AssetInput objects. list_assets and "
        "get_asset discover this user's own assets. search_assets uses type=image or icon "
        "and a descriptive query; public search results are candidates with their own licenses.",
        "Uploading larger files takes longer and may consume storage; reusing a completed "
        "asset avoids retransferring it. Search/list/get return data without rendering media.",
    ),
    "AI Clipping": (
        "Extract short highlights from a longer source using create_ai_clipping. Input "
        "language and output_settings are optional; specify destination format and desired "
        "clip behavior only where exposed by the native schema.",
        "Use an accessible source video with clear speech and complete context. Avoid "
        "cutting off sentences in the uploaded source; confirm rights to republish excerpts.",
        "Source media may be a URL or owned asset. Use list_ai_clipping/get_ai_clipping "
        "with the job_id returned by creation to inspect its selected clips.",
        "Longer source footage takes more analysis. Highlight selection is a creative "
        "judgment; inspect each returned clip for context and unintended omissions.",
    ),
    "Filler Word Removal": (
        "Remove detected filler words from existing speech video. Source video is essential; "
        "a title is optional. Use this for a finished recording that needs tighter delivery.",
        "Supply clear speech with limited overlapping speakers or background music and "
        "confirm source rights. Preserve an original copy for comparison.",
        "Use a direct source URL or owned uploaded asset. Save filler_word_removal_id "
        "and use get_filler_word_removal to inspect the same edit.",
        "Longer footage requires more work. Automatic removal can change cadence and "
        "occasionally intent; review the finished edit before publication.",
    ),
    "Podcasts": (
        "Provide a topic, source_files, or both, plus host/guest avatar and voice IDs. "
        "Use real grounding facts. layout defaults to landscape and duration to auto; "
        "instructions can set the studio and tone.",
        "Grounding files may be PDF, image, or video supplied through the documented "
        "URL/asset_id variants, up to five sources. Ensure their contents support the topic.",
        "Use list_avatar_looks and list_voices for both participants. Podcast IDs come "
        "from create_podcast/list_podcasts; inspect an owned result with get_podcast.",
        "Two-avatar dialogue and longer target durations require more generation work. "
        "Auto duration lets HeyGen choose a length; use a supported explicit duration "
        "when the user has a clear length preference.",
    ),
    "Durable Workflows": (
        "Create/publish a complete product_graph only after reading the node-type catalog. "
        "Use declared inputs, bindings, and outputs; creation publishes immutable version 1. "
        "A draft update needs expected_revision from the latest read. Starting a run needs "
        "workflow_id and values matching the chosen version's declared inputs.",
        "Graph authoring needs JSON, not a file. Media run inputs accept owned asset IDs, "
        "public HTTPS AssetInput URLs, or bounded inline base64; imported media must remain "
        "accessible for ingestion. Check all source permissions before a media-generating run.",
        "Use get_workflow_node_types, list_workflow_definitions/get_workflow, and "
        "list_workflow_versions/get_workflow_version. Version numbers are immutable; omit "
        "version_number only when the latest published version is intended. Runtime keys "
        "and authentication are operator controlled.",
        "Authoring/publishing a graph does not generate its media. A run's nodes may create "
        "multiple charged artifacts. Pin a version for repeatable execution, inspect inputs, "
        "and authorize the full graph before running it. Cancellation does not undo charges.",
    ),
    "Video Quality": (
        "Compare video_a and video_b with the original prompt, caller-supplied model labels, "
        "and question_id. Choose engagement, prompt_intent, composition, temporal_consistency, "
        "or craft for the actual scoring criterion; q1 is an engagement alias.",
        "Provide comparable, accessible candidate videos through URL, asset_id, or base64. "
        "Match their intended content and duration where possible and confirm source rights.",
        "Asset IDs come from uploads. model_a/model_b are descriptive labels supplied by "
        "the user, not catalog IDs. judge_model_version must be an allowed provider version; "
        "omit it to use the active judge. Save comparison_id or batch_id from the result.",
        "Each pair incurs evaluation work; a batch allows up to 100 comparisons. Automated "
        "scores represent a selected criterion and do not establish factual correctness or "
        "legal permission. The original prompt supplies context, not the scoring criterion.",
    ),
    "User": (
        "Inspect the operator's own account profile and usage only from an authenticated "
        "operator workflow. No public Pond action exposes this account administration.",
        "No files are needed.",
        "The authenticated operator account supplies identity.",
        "This is an account snapshot; reported balances are not a guarantee of future cost.",
    ),
    "Webhooks": (
        "Administer event subscriptions and signing secrets only from an authenticated "
        "operator workflow. Use the event-type catalog before editing subscriptions.",
        "No files are needed. Endpoint URLs must be controlled by the operator.",
        "Use list_webhook_event_types/list_webhook_endpoints; never share signing secrets.",
        "Changing or rotating a subscription can interrupt delivery. Coordinate consumers "
        "before mutation; this administration is excluded from the public Pond manifest.",
    ),
}

BATCH_FAMILY = {
    "Batches": "Videos",
    "Video Translation Batches": "Video Translate",
    "Lipsync Batches": "Lipsync",
    "Asset Batches": "Assets",
}

COMPLETION_TEXT = {
    "snapshot": "The returned read/search/status snapshot is the finished task. A resource "
    "inside the snapshot may still be processing; a status query does not promise a new render.",
    "mutation": "The requested synchronous resource change is acknowledged with its resulting "
    "record or deletion/cancellation outcome. Creating or publishing a workflow definition "
    "does not execute its graph, and stopping work does not imply an artifact was produced.",
    "video": "The video has finished rendering and its output is available; an accepted "
    "request or a video_id alone does not finish this task.",
    "session": "The one-shot session turn has finished with a newly completed video. "
    "Queued/working status, storyboards, a pre-existing video, or a request for human input "
    "do not count as completion. Required choices must be settled before dispatch.",
    "avatar": "Avatar training/generation has settled successfully and the new avatar/look "
    "is usable. An identity ID, pending training, or outstanding consent is not completion.",
    "voice": "The instant clone reaches the provider's complete state and returns its "
    "usable voice identity; a pending voice_clone_id is not completion.",
    "professional_voice": "Training reaches ACTIVE and the model-backed voice is available "
    "for inference. PENDING is unfinished and FAILED is a failed task.",
    "speech": "Complete generated audio is available as a file result, with timing metadata "
    "when the provider supplies it. This action does not expose a live audio stream.",
    "brand_kit": "The website import reaches completed and the assembled brand kit is "
    "available; an immediately allocated brand_kit_id is not the finished import.",
    "translation": "All requested translation outputs have reached a terminal state; "
    "successful results include their generated media. Multiple target languages are tracked "
    "individually; an accepted ID list is not a finished translation.",
    "proofread": "All requested proofread sessions are prepared with their editable "
    "transcripts/subtitle resources. This task ends at that usable preparation stage; "
    "a later edited SRT and final-video generation are separate one-shot actions.",
    "lipsync": "The replacement-audio job has finished and its synchronized output is "
    "available; a lipsync_id by itself is only a submission receipt.",
    "hyperframes": "The composition render has finished with a downloadable video in "
    "the requested container. An allocated render_id is unfinished work.",
    "clipping": "Clip analysis/generation has finished and the resulting clips and "
    "metadata are available; an accepted job ID does not finish the task.",
    "background_removal": "Background removal has finished and the requested output "
    "layers/media are available. Queued and processing jobs remain unfinished.",
    "filler_removal": "The edited recording has finished processing and its output "
    "is available. A filler_word_removal_id alone is a submission receipt.",
    "podcast": "The podcast video has finished generating and its media output is "
    "available. A topic/script/session ID alone is not the finished podcast.",
    "workflow": "The run and its nodes have settled and final declared outputs are "
    "collected. Queued node IDs or an accepted run_id do not finish execution.",
    "comparison": "The comparison has finished and its evaluation is available, "
    "including when the provider initially accepted it asynchronously with HTTP 202.",
    "asset": "The source bytes have been transferred and the asset is usable in HeyGen. "
    "A presigned URL, upload slot, or unfinalized asset ID is not a finished upload.",
}

NOTES = {
    "create_video_agent": "Only mode=generate is accepted. Supply all necessary creative "
    "decisions in the initial prompt; no human response is possible while this task runs.",
    "send_video_agent_message": "Request one self-contained revision of an owned session. "
    "State exact changes and settle every required choice before submission. The runtime "
    "requires a newly completed result and treats any human-input pause as unfinished.",
    "create_brand_kit": "Import runs in the background; wait for assembled colors, logos, "
    "and fonts before applying the kit to a video.",
    "update_brand_kit": "Each supplied role object replaces its whole assignment; send "
    "all roles to keep. An empty object clears the assignment. Omit a field to preserve it; "
    "null is rejected. Role edits require an assembled kit; renaming may occur sooner.",
    "update_brand_glossary": "Read first, modify the whole list, and send that replacement "
    "list. Omitted fields remain unchanged; an empty array clears all entries in that field.",
    "design_voice": "This is semantic voice discovery, not recording-based voice training. "
    "A different seed can return another batch of up to three matches.",
    "create_model_audio_voice": "At least 20 minutes of recordings are required. New "
    "professional voices need an available slot; existing voice_id retrains the same voice. "
    "The provider may not expose a distinct training receipt for retraining. An existing "
    "ACTIVE voice alone cannot verify that this new training finished; if its new completion "
    "cannot be established, the task reports an unverifiable result instead of success.",
    "generate_from_template": "Read get_template first and copy its exact variable keys "
    "and value types. Supply every text variable to fill: an omitted text variable retains "
    "its literal placeholder, even if get_template returned a current value. Omitted media "
    "variables keep their existing media. Replace the example's headline key with a real key.",
    "upload_proofread_srt": "This replaces the subtitles with the supplied edited SRT. "
    "It does not itself render the translated video; use generate_from_proofread next.",
    "download_proofread_srt": "The completed result is the current SRT subtitle text/file "
    "for this proofread, suitable for editing before a separate upload.",
    "generate_from_proofread": "Use a prepared proofread whose subtitles already contain "
    "the final approved wording. The task renders that state into translated video.",
    "create_workflow": "The complete product_graph is validated and published as version 1 "
    "atomically. Duplicate names conflict; invalid graphs create nothing.",
    "update_workflow_draft": "Use expected_revision from get_workflow. A stale revision "
    "is rejected; read again before deciding how to reapply the intended graph update.",
    "publish_workflow_version": "Send the complete product_graph to publish. The mutable "
    "draft is neither read nor modified. Identical latest content returns that same version; "
    "republishing older content creates a new version.",
    "create_workflow_run": "The operator supplies the required durable idempotency key. "
    "Omitted version_number resolves once to the latest published version for this run.",
    "cancel_workflow_run": "A settled cancellation or already-terminal status is returned. "
    "Cancellation cannot move a completed run backwards or undo produced outputs.",
    "list_assets": "The operator supplies the account username internally. Public callers "
    "receive only assets authorized for their identity and do not supply account credentials.",
    "upload_asset": "Supply body.file as a Pond HTTPS file descriptor. The operator "
    "downloads the bytes and sends the actual multipart file, then verifies ingestion.",
    "upload_assets_batch": "Provide one to 100 body.files descriptors. The operator computes "
    "the real lengths, uploads every file, finalizes the batch, and collects every outcome.",
}


def _resolve(schema, definitions):
    if "$ref" in schema:
        return {
            **definitions[schema["$ref"].removeprefix("#/$defs/")],
            **{key: value for key, value in schema.items() if key != "$ref"},
        }
    return schema


def _sample(schema, definitions, name="value"):
    schema = _resolve(schema, definitions)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None:
        return copy.deepcopy(schema["default"])
    for union in ("oneOf", "anyOf"):
        if union in schema:
            variant = next((s for s in schema[union] if s.get("type") != "null"), schema[union][0])
            return _sample(variant, definitions, name)
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {
            key: _sample(schema["properties"][key], definitions, key)
            for key in schema.get("required", [])
        }
    if kind == "array":
        return [
            _sample(schema.get("items", {}), definitions, name.rstrip("s"))
            for _ in range(max(1, schema.get("minItems", 0)))
        ]
    if kind in {"integer", "number"}:
        return max(1, schema.get("minimum", 1))
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    if kind == "string":
        values = {
            "url": "https://example.org/source.mp4",
            "video": "https://example.org/source.mp4",
            "name": "Product introduction",
            "title": "Product introduction",
            "text": "Welcome. Here is how to book your first appointment.",
            "prompt": "Introduce our salon booking app and its appointment reminders.",
            "query": "warm natural light in a small salon",
            "language": "en",
            "version_number": "1",
            "schema_version": "1.0.0",
            "model_a": "candidate-a",
            "model_b": "candidate-b",
            "voice_name": "Permitted narrator",
            "output_language": "Spanish (Spain)",
            "type": "text",
            "username": "operator-injected",
            "message": "Shorten the introduction and retain the facts.",
        }
        if name.endswith("_id"):
            value = "replace-with-owned-" + name.replace("_", "-")
        elif name.endswith("_ids"):
            value = "replace-with-owned-id"
        elif name.endswith("url"):
            value = "https://example.org/source.mp4"
        else:
            value = values.get(name, "example")
        return value[: schema.get("maxLength", len(value))]
    return {}


def _asset(filename):
    return {"type": "url", "url": "https://example.org/" + filename}


def _example(row):
    schema = row["input_schema"]
    result = _sample(schema, schema.get("$defs", {}))
    key = row["id"]
    bodies = {
        "create_video_agent": {
            "prompt": "Create a short welcome video for new salon staff. "
            "Explain that clients book online and receive appointment reminders.",
            "orientation": "landscape",
            "mode": "generate",
        },
        "create_brand_glossary": {"name": "Salon terminology"},
        "create_brand_kit": {"url": "https://example.org", "name": "Our salon"},
        "update_brand_kit": {"name": "Salon brand 2026"},
        "update_brand_glossary": {"name": "Approved salon terminology"},
        "create_avatar": {
            "type": "prompt",
            "name": "Fictional training host",
            "prompt": "A friendly fictional adult presenter in a bright studio.",
            "aspect_ratio": "16:9",
        },
        "create_speech": {
            "text": "Welcome to our team. We are glad you are here.",
            "voice_id": "replace-with-starfish-voice-id",
            "speed": 1.0,
        },
        "design_voice": {"prompt": "Warm, clear, reassuring English narrator", "locale": "en-US"},
        "clone_voice": {"audio": _asset("permitted-speaker.wav"), "voice_name": "Our narrator"},
        "create_model_audio_voice": {
            "mode": "professional",
            "name": "Our narrator",
            "language": "en",
            "audio": [_asset("speaker-20-minutes.wav")],
        },
        "generate_model_speech": {
            "voice_id": "replace-with-active-model-voice-id",
            "text": "Welcome to the training session.",
            "language": "en",
        },
        "create_video": {
            "type": "avatar",
            "avatar_id": "replace-with-catalog-look-id",
            "script": "Welcome to our team. Clients can book appointments online.",
            "aspect_ratio": "16:9",
        },
        "generate_from_template": {
            "variables": {"headline": {"type": "text", "content": "Welcome to our team"}},
            "title": "Welcome from our team",
        },
        "create_background_removal": {"video": _asset("presenter.mp4")},
        "create_video_translation": {
            "video": _asset("welcome.mp4"),
            "output_languages": ["Spanish (Spain)"],
            "mode": "speed",
        },
        "create_proofread": {
            "video": _asset("welcome.mp4"),
            "output_languages": ["es"],
            "title": "Spanish welcome transcript",
        },
        "upload_proofread_srt": {"srt": _asset("approved-spanish.srt")},
        "create_lipsync": {
            "video": _asset("presenter.mp4"),
            "audio": _asset("final-narration.wav"),
        },
        "create_hyperframes_render": {"project": _asset("composition.zip"), "quality": "standard"},
        "update_avatar_group": {"default_voice_id": "replace-with-verified-voice-id"},
        "update_avatar_look": {"name": "Approved presenter look"},
        "upload_asset": {
            "file": {
                "url": "https://example.org/portrait.png",
                "name": "portrait.png",
                "media_type": "image/png",
            }
        },
        "send_video_agent_message": {
            "message": "Revise the existing video: shorten the opening "
            "to one sentence, keep all product facts, and render the final cut."
        },
        "create_ai_clipping": {
            "video": _asset("training-session.mp4"),
            "title": "Training highlights",
        },
        "create_filler_word_removal": {
            "video": _asset("interview.mp4"),
            "title": "Clean interview",
        },
        "create_podcast": {
            "topic": "How to help clients book their next salon visit online",
            "host_avatar_id": "replace-with-host-look-id",
            "guest_avatar_id": "replace-with-guest-look-id",
            "host_voice_id": "replace-with-host-voice-id",
            "guest_voice_id": "replace-with-guest-voice-id",
            "duration": "1min",
        },
        "create_workflow_run": {
            "workflow_id": "replace-with-owned-workflow-id",
            "version_number": 1,
            "inputs": {},
        },
        "create_video_quality_comparison": {
            "prompt": "A presenter introduces online salon appointments.",
            "model_a": "candidate-a",
            "model_b": "candidate-b",
            "video_a": _asset("candidate-a.mp4"),
            "video_b": _asset("candidate-b.mp4"),
            "question_id": "composition",
        },
    }
    for batch, field, single in (
        ("create_video_batch", "videos", "create_video"),
        ("create_video_translation_batch", "video_translations", "create_video_translation"),
        ("create_lipsync_batch", "lipsyncs", "create_lipsync"),
        ("create_video_quality_comparison_batch", "comparisons", "create_video_quality_comparison"),
    ):
        bodies[batch] = {field: [copy.deepcopy(bodies[single])]}
    bodies["upload_assets_batch"] = {
        "files": [bodies["upload_asset"]["file"]],
        "title": "Brand assets",
    }
    graph = {
        "schema_version": "1.0.0",
        "inputs": {"script": {"type": "text", "required": True}},
        "nodes": [
            {
                "id": "render",
                "type": "replace_with_catalog_node_type",
                "config": {},
                "bindings": {
                    "replace_with_input_port": {"kind": "run_input", "name": "script"},
                },
            }
        ],
        "outputs": {"video": {"node_id": "render", "port": "replace_with_output_port"}},
    }
    bodies["create_workflow"] = {"name": "Welcome video", "product_graph": graph}
    bodies["update_workflow_draft"] = {"product_graph": graph, "expected_revision": 1}
    bodies["publish_workflow_version"] = {"product_graph": graph}
    if key in bodies:
        result["body"] = copy.deepcopy(bodies[key])
    queries = {
        "list_voices": {"engine": "starfish", "language": "English", "type": "public", "limit": 20},
        "list_avatar_looks": {"ownership": "public", "limit": 20},
        "list_avatar_groups": {"ownership": "public", "limit": 20},
        "search_assets": {"query": "bright modern salon interior", "type": "image", "limit": 10},
        "search_audio_sounds": {
            "query": "soft upbeat acoustic background",
            "type": "music",
            "limit": 10,
        },
        "bulk_video_statuses": {"video_ids": "replace-with-owned-video-id"},
        "bulk_video_translation_statuses": {
            "video_translation_ids": "replace-with-owned-translation-id"
        },
        "bulk_lipsync_statuses": {"lipsync_ids": "replace-with-owned-lipsync-id"},
        "bulk_asset_statuses": {"asset_ids": "replace-with-owned-asset-id"},
    }
    if key in queries:
        result["query"] = queries[key]
    elif "query" in schema["properties"]:
        params = schema["properties"]["query"]["properties"]
        if "limit" in params:
            result.setdefault("query", {})["limit"] = params["limit"].get("default", 10)
    return result


def _essential(schema, definitions, prefix=""):
    schema = _resolve(schema, definitions)
    for union in ("oneOf", "anyOf"):
        if union in schema:
            options = [
                _essential(variant, definitions, prefix)
                for variant in schema[union]
                if variant.get("type") != "null"
            ]
            return "one native variant: (" + ") or (".join(options) + ")"
    required = schema.get("required", [])
    if not required:
        return (
            prefix.rstrip(".") + " per the selected native schema"
            if prefix
            else "no required inputs"
        )
    names = []
    for name in required:
        child = schema.get("properties", {}).get(name, {})
        if name in {"body", "path", "query"}:
            names.append(_essential(child, definitions, prefix + name + "."))
        else:
            names.append(prefix + name)
    return ", ".join(names)


def _optional(schema):
    definitions = schema.get("$defs", {})
    defaults = []
    for wrapper in ("query", "body"):
        part = _resolve(schema["properties"].get(wrapper, {}), definitions)
        for name, value in part.get("properties", {}).items():
            if name not in part.get("required", []) and value.get("default") is not None:
                defaults.append(wrapper + "." + name + "=" + json.dumps(value["default"]))
    return ("Documented defaults: " + ", ".join(defaults[:8]) + ". ") if defaults else ""


def action_guide(row):
    """Return a full guide and schema-valid practical example for one operation."""
    tag = row["tags"][0] if row["tags"] else "Assets"
    family = BATCH_FAMILY.get(tag, tag)
    preparation, file_advice, ids, cost = FAMILIES[family]
    if row["access"] == "public" and family in {"Avatars", "Voices", "Models", "Video Quality"}:
        preparation = (
            "Use existing ready resources and the exact identifiers returned by this user's "
            "catalogs or previous tasks. Creation/training, standalone speech, and new quality "
            "scoring are disabled until separately priced. Semantic voice search remains available."
        )
        file_advice = (
            "Catalog reads and edits do not need training recordings. Supply only fields in this "
            "action's schema; use ready avatars/voices within a video-generation action."
        )
        ids = (
            "Use list_avatar_groups/list_avatar_looks, list_voices/get_voice, or "
            "list_model_audio_voices/get_model_audio_voice for the matching resource family. "
            "Quality reads require an owned comparison or batch ID from a prior task."
        )
        cost = "Reading, selecting, or editing existing resources creates no video seconds."
    native = row["native_description"].split("\n\n", 1)[0]
    native = {
        "create_video": "Create a 720p avatar, image, or studio video. Avatar engines are "
        "Avatar III and Avatar IV; omitted/null engine uses Avatar IV.",
        "create_video_translation": "Translate video into one or more target languages "
        "using speed mode. Each language creates a separate output.",
        "create_lipsync": "Replace the audio on existing video and synchronize mouth "
        "movement with speed mode.",
    }.get(row["id"], native)
    if (
        family in {"Video Agent", "Templates", "Podcasts", "Durable Workflows"}
        or row["id"] == "generate_from_proofread"
    ):
        cost += " " + MANAGED_COST_NOTE
    # Native docs describe HTTP submission; the completion paragraph describes the Pond task.
    choose = f"Choose {row['id']} to {row['summary'].lower()}. {native}"
    note = NOTES.get(row["id"], "")
    if family in {
        "Avatars",
        "Voices",
        "Models",
        "Video Translate",
        "Durable Workflows",
        "Video Quality",
    }:
        note += " " + POLICY_NOTE
    if row["id"] in {"create_workflow", "update_workflow_draft", "publish_workflow_version"}:
        note += " The graph example shows binding structure. Replace its node-type and port "
        note += "placeholders with actual get_workflow_node_types values and populate config "
        note += "to match that node's schema before dispatch."
    if row.get("provider_preview"):
        note += " This operation is present in the pinned official schema but marked "
        note += "x-excluded there. Provider-account availability has not been live-verified."
    if row["method"] == "DELETE":
        note += " Confirm the exact owned resource to delete before dispatch. Deletion is "
        note += "a persistent change and may make that resource unavailable to dependent work."
    if tag in BATCH_FAMILY or row["completion"].endswith("_batch"):
        note += " Batch input limits apply after expansion where one entry targets multiple "
        note += "languages. Items settle independently; inspect per-item failures and follow "
        note += "all returned pagination tokens before treating a batch snapshot as exhaustive."
        cost += " A batch multiplies work across its entries; begin with one representative item."
    completion = row["completion"]
    if completion.endswith("_batch"):
        done = "Every batch item has reached a terminal state and all successful outputs "
        done += "and individual failures are collected across every page. Allocated batch "
        done += "IDs, upload slots, or a first page alone do not finish this task."
    else:
        done = COMPLETION_TEXT[completion]
    if completion == "snapshot":
        cost = "This action reads/searches current records and does not start a render. " + cost
    example = _example(row)
    description = "\n\n".join(
        [
            choose,
            "Essential inputs: "
            + _essential(row["input_schema"], row["input_schema"].get("$defs", {}))
            + ". Supply path, query, and body values in their named objects. "
            + note,
            "Optional settings and quality defaults: "
            + _optional(row["input_schema"])
            + preparation,
            "Files and preparation: " + file_advice,
            "IDs and discovery: " + ids + " Examples use illustrative IDs and URLs; replace them "
            "with verified catalog IDs, owned resources, and actual source URLs before dispatch.",
            "Example parameters: " + json.dumps(example, ensure_ascii=False, separators=(",", ":")),
            "Cost and quality: " + cost + " The operator controls credentials, request headers, "
            "idempotency, and callbacks. A task timeout does not reverse provider charges.",
            "Completion: " + done,
        ]
    )
    return description, [example]
