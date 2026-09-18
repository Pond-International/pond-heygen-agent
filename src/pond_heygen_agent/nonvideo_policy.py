"""Standalone generation without a video-second price is unavailable."""

DISABLED_ACTIONS = frozenset(
    {
        "create_avatar",
        "create_speech",
        "generate_model_speech",
        "clone_voice",
        "create_model_audio_voice",
        "create_proofread",
        "create_video_quality_comparison",
        "create_video_quality_comparison_batch",
    }
)
DISABLED_REASON = "This standalone non-video action is disabled until separately priced."
POLICY_NOTE = (
    "Video-second pricing only: standalone speech synthesis, avatar creation, voice cloning/"
    "training, proofread preparation, and video-quality scoring are disabled until separately "
    "priced. Use existing ready avatars/voices and catalog lookups. Audio-only translation is "
    "disabled. Workflow execution requires a declared final video output; graph authoring and "
    "reading existing resources remain available. Speech used within a generated video is "
    "part of that video task, not a standalone speech action."
)


def restrict_nonvideo_schemas(definitions):
    for schema in definitions.values():
        option = schema.get("properties", {}).get("translate_audio_only")
        if option:
            option.update(
                const=False,
                default=False,
                description="Must be false: audio-only translation has no video-second price.",
            )
