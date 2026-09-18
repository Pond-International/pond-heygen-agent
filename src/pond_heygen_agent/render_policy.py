"""Local restrictions on explicit render settings, not a provider spending cap.

The upstream OpenAPI snapshot stays intact. These overlays narrow the same
schemas used for discovery and validation. Provider-managed choices inside
automatic generation, templates, and stored workflows remain outside this policy.
"""

REMOVED_REFS = {
    "#/$defs/CreateVideoFromCinematicAvatar",
    "#/$defs/CreateBatchVideoFromCinematicAvatar",
    "#/$defs/AvatarVEngineConfig",
}
VIDEO_INPUTS = {
    f"Create{batch}VideoFrom{kind}"
    for batch in ("", "Batch")
    for kind in ("Avatar", "Image", "Studio")
}
SPEED_ACTIONS = {"create_video_translation", "create_proofread", "create_lipsync"}
SPEED_BATCHES = {
    "create_video_translation_batch": "video_translations",
    "create_lipsync_batch": "lipsyncs",
}
MANAGED_COST_NOTE = (
    "Automatic generation and provider-managed template, proofread, podcast, or workflow "
    "settings remain available. Their internal engine, resolution, and charges are not "
    "enforced by this agent's explicit-option restrictions; this is not a spending cap."
)


def _remove_variants(value):
    if isinstance(value, list):
        for child in value:
            _remove_variants(child)
    elif isinstance(value, dict):
        for union in ("oneOf", "anyOf"):
            if union in value:
                value[union] = [v for v in value[union] if v.get("$ref") not in REMOVED_REFS]
        discriminator = value.get("discriminator", {})
        if "mapping" in discriminator:
            discriminator["mapping"] = {
                name: ref
                for name, ref in discriminator["mapping"].items()
                if ref not in REMOVED_REFS
            }
        for child in value.values():
            _remove_variants(child)


def restrict_schemas(root, definitions):
    """Narrow compiled schemas in place, before the registry prunes unused refs."""
    _remove_variants(root)
    _remove_variants(definitions)
    for name, allowed in (
        ("VideoResolution", "720p"),
        ("VideoTranslationMode", "speed"),
        ("HyperframesResolution", "1080p"),
    ):
        if name in definitions:
            definitions[name].update(
                enum=[allowed],
                default=allowed,
                description=f"This agent accepts only {allowed} for this setting.",
            )
    if "AvatarIIIEngineConfig" in definitions:
        definitions["AvatarIIIEngineConfig"]["description"] = (
            "Avatar III engine: video-avatar looks use Digital Twin; photo-avatar looks "
            "use Photo Avatar. This agent requests 720p. Raw image input, motion_prompt, "
            "and expressiveness are not supported with this engine."
        )
    if "VideoAspectRatio" in definitions:
        definitions["VideoAspectRatio"]["description"] = (
            "16:9/9:16 select landscape/portrait. 4:5, 5:4, and 1:1 select social ratios "
            "anchored to the 720p short edge (1:1 gives 720x720). auto preserves source "
            "aspect ratio within the tier's long-edge limit and falls back to 16:9 if "
            "source dimensions are unavailable."
        )
    for name in VIDEO_INPUTS | {"StudioAvatarInput"}:
        props = definitions.get(name, {}).get("properties", {})
        if props and name in {"CreateVideoFromAvatar", "CreateBatchVideoFromAvatar"}:
            definitions[name]["description"] = (
                "Create a 720p video from a HeyGen studio_avatar, digital_twin, or "
                "photo_avatar look. Supply an avatar_id and script or audio. Choose "
                "Avatar III or Avatar IV, compatible with the look; omitted/null engine "
                "uses Avatar IV."
            )
        if "resolution" in props:
            props["resolution"].update(
                default="720p",
                description="Output resolution is 720p. Omitted/null uses 720p.",
            )
        if "engine" in props:
            props["engine"].update(
                default={"type": "avatar_iv"},
                description="Choose avatar_iii or avatar_iv, supported by the selected look. "
                "Omitted/null uses avatar_iv.",
            )
            props["motion_prompt"]["description"] = (
                "Optional body-motion and gesture instructions for photo avatars. "
                "Not supported for video avatars on the default Avatar IV engine."
            )
            props["expressiveness"]["description"] = (
                "Photo-avatar expressiveness, Avatar IV only. Defaults to low when omitted."
            )
    batch = definitions.get("CreateVideoBatchRequest", {}).get("properties", {})
    if "videos" in batch:
        batch["videos"]["description"] = (
            "Video requests of type avatar, image, or studio, at 720p. "
            "Set folder_id on the batch, not on items. Max 100 per batch."
        )
    for name in ("CreateVideoTranslationRequest", "CreateProofreadRequest", "CreateLipsyncRequest"):
        if name in definitions:
            definitions[name]["properties"]["mode"]["description"] = (
                "Only speed mode is supported by this agent; omitted uses speed."
            )
    hyper = definitions.get("CreateHyperframesRenderRequest", {}).get("properties", {})
    if hyper:
        hyper["quality"].update(
            enum=["draft", "standard"],
            description="Choose draft or standard (default).",
        )
        hyper["resolution"]["description"] = (
            "1080p only, the lowest supported HyperFrames tier. Omitted uses 1080p."
        )
    if "TemplateVideoDimension" in definitions:
        dimension = definitions["TemplateVideoDimension"]
        dimension["description"] = (
            "Explicit dimensions must fit 1280x720 or 720x1280 and retain the template's "
            "aspect ratio. Omitted dimensions use provider-managed template defaults."
        )
        dimension["anyOf"] = [
            {"properties": {"width": {"maximum": width}, "height": {"maximum": height}}}
            for width, height in ((1280, 720), (720, 1280))
        ]
        for axis in ("width", "height"):
            dimension["properties"][axis].update(
                maximum=1280,
                description=f"Output {axis} in even pixels, 128-1280; the shorter side "
                "must be at most 720. Preserve the template's aspect ratio.",
            )
        # The native template schema otherwise accepts undocumented top-level
        # selectors. Keep its typed variable map open, not its fixed request body.
        template = definitions["GenerateFromTemplateV3Request"]
        template["additionalProperties"] = False
        template["properties"]["dimension"]["description"] = dimension["description"]


def _video_defaults(body):
    if body.get("resolution") is None:
        body["resolution"] = "720p"
    if body["type"] == "avatar" and body.get("engine") is None:
        body["engine"] = {"type": "avatar_iv"}
    if body["type"] == "studio":
        for scene in body["scenes"]:
            if scene["type"] == "avatar_video" and scene["input"].get("engine") is None:
                scene["input"]["engine"] = {"type": "avatar_iv"}


def apply_render_defaults(action_id, parameters):
    """Fill only controlled fields in an already validated, copied parameter set."""
    body = parameters.get("body", {})
    if action_id == "create_video":
        _video_defaults(body)
    elif action_id == "create_video_batch":
        for video in body["videos"]:
            _video_defaults(video)
    elif action_id in SPEED_ACTIONS:
        body.setdefault("mode", "speed")
    elif action_id in SPEED_BATCHES:
        for item in body[SPEED_BATCHES[action_id]]:
            item.setdefault("mode", "speed")
    elif action_id == "create_hyperframes_render":
        body.setdefault("resolution", "1080p")
        body.setdefault("quality", "standard")
