# HeyGen operation coverage

Pinned official OpenAPI snapshot: September 7, 2026.
Source: https://developers.heygen.com/openapi/external-api.json

148 upstream operations are inventoried below, plus one complete batch-upload wrapper.
107 public native/wrapper actions are advertised alongside the two convenience actions.
`public` means implemented, not paid live-tested. `preview` denotes upstream `x-excluded`
operations whose provider/account availability is not confirmed. Administration stays operator-only.

Since 0.2.1, public coverage is subject to the [explicit render-option policy](action-policy.md#render-options):
no Cinematic Avatar/Avatar V, native creation at 720p, speed-only translation/lipsync,
and draft/standard HyperFrames at 1080p. Explicit template dimensions are bounded.
Automatic/provider-managed paths remain enabled without a guaranteed cost tier.
The pinned source is unchanged; local schema overlays narrow the accepted options.

Since 0.3.0, eight standalone non-video generation/analysis actions are `disabled`
until separately priced. Audio-only translation is disallowed and workflow runs
must declare a final video output. Existing catalogs/resources and video generation
remain available; see the [billing policy](action-policy.md#disabled-standalone-non-video-actions).

| Action | Method and path | Classification | Availability |
| --- | --- | --- | --- |
| `create_video_agent` | `POST /v1/video_agent/generate` | legacy | preview / account-gated |
| `create_video_agent` | `POST /v3/video-agents` | public | pinned contract |
| `list_video_agent_sessions` | `GET /v3/video-agents` | public | pinned contract |
| `list_video_agent_styles` | `GET /v3/video-agents/styles` | public | pinned contract |
| `list_brand_glossaries` | `GET /v3/brand-glossaries` | public | pinned contract |
| `create_brand_glossary` | `POST /v3/brand-glossaries` | public | pinned contract |
| `create_brand_kit` | `POST /v3/brand-kits` | public | pinned contract |
| `list_brand_kits` | `GET /v3/brand-kits` | public | pinned contract |
| `get_brand_kit` | `GET /v3/brand-kits/{brand_kit_id}` | public | pinned contract |
| `update_brand_kit` | `PATCH /v3/brand-kits/{brand_kit_id}` | public | pinned contract |
| `delete_brand_kit` | `DELETE /v3/brand-kits/{brand_kit_id}` | public | pinned contract |
| `get_brand_glossary` | `GET /v3/brand-glossaries/{brand_glossary_id}` | public | pinned contract |
| `update_brand_glossary` | `PATCH /v3/brand-glossaries/{brand_glossary_id}` | public | pinned contract |
| `delete_brand_glossary` | `DELETE /v3/brand-glossaries/{brand_glossary_id}` | public | pinned contract |
| `create_avatar` | `POST /v3/avatars` | disabled | needs separate pricing |
| `list_avatar_groups` | `GET /v3/avatars` | public | pinned contract |
| `create_avatar_realtime_session` | `POST /v3/avatar-realtime` | excluded | preview / account-gated |
| `get_avatar_realtime_session` | `GET /v3/avatar-realtime/{stream_id}` | excluded | preview / account-gated |
| `stream_avatar_realtime_words` | `GET /v3/avatar-realtime/{stream_id}/words` | excluded | preview / account-gated |
| `append_avatar_realtime_text` | `POST /v3/avatar-realtime/{stream_id}/text` | excluded | preview / account-gated |
| `cancel_avatar_realtime_session` | `POST /v3/avatar-realtime/{stream_id}/cancel` | excluded | preview / account-gated |
| `text_to_speech` | `POST /v1/audio/text_to_speech` | legacy | preview / account-gated |
| `list_audio_voices` | `GET /v1/audio/voices` | legacy | preview / account-gated |
| `search_audio_sounds` | `GET /v3/audio/sounds` | public | pinned contract |
| `create_speech` | `POST /v3/voices/speech` | disabled | needs separate pricing |
| `design_voice` | `POST /v3/voices` | public | pinned contract |
| `list_voices` | `GET /v3/voices` | public | pinned contract |
| `clone_voice` | `POST /v3/voices/clone` | disabled | needs separate pricing |
| `create_model_audio_voice` | `POST /v3/models/audio/voices` | disabled | needs separate pricing; preview |
| `list_model_audio_voices` | `GET /v3/models/audio/voices` | public | preview / account-gated |
| `generate_model_speech` | `POST /v3/models/audio/tts` | disabled | needs separate pricing; preview |
| `stream_model_speech` | `POST /v3/models/audio/tts/stream` | covered | preview / account-gated |
| `get_model_audio_voice` | `GET /v3/models/audio/voices/{voice_id}` | public | preview / account-gated |
| `delete_model_audio_voice` | `DELETE /v3/models/audio/voices/{voice_id}` | public | preview / account-gated |
| `get_voice` | `GET /v3/voices/{voice_id}` | public | pinned contract |
| `delete_voice` | `DELETE /v3/voices/{voice_id}` | public | pinned contract |
| `create_avatar_video` | `POST /v2/videos` | legacy | preview / account-gated |
| `list_videos` | `GET /v2/videos` | legacy | preview / account-gated |
| `get_video` | `GET /v2/videos/{video_id}` | legacy | preview / account-gated |
| `delete_video` | `DELETE /v2/videos/{video_id}` | legacy | preview / account-gated |
| `create_video` | `POST /v3/videos` | public | pinned contract |
| `list_videos` | `GET /v3/videos` | public | pinned contract |
| `get_video` | `GET /v3/videos/{video_id}` | public | pinned contract |
| `delete_video` | `DELETE /v3/videos/{video_id}` | public | pinned contract |
| `get_video_scenes` | `GET /v3/videos/{video_id}/scenes` | public | pinned contract |
| `list_templates` | `GET /v3/templates` | public | pinned contract |
| `get_template` | `GET /v3/templates/{template_id}` | public | pinned contract |
| `generate_from_template` | `POST /v3/templates/{template_id}` | public | pinned contract |
| `create_background_removal` | `POST /v3/background-removals` | public | preview / account-gated |
| `list_background_removals` | `GET /v3/background-removals` | public | preview / account-gated |
| `get_background_removal` | `GET /v3/background-removals/{job_id}` | public | preview / account-gated |
| `delete_background_removal` | `DELETE /v3/background-removals/{job_id}` | public | preview / account-gated |
| `create_video_translate` | `POST /v2/video_translate` | legacy | preview / account-gated |
| `list_video_translate_languages` | `GET /v2/video_translate/target_languages` | legacy | preview / account-gated |
| `get_video_translate_caption` | `GET /v2/video_translate/caption` | legacy | preview / account-gated |
| `create_video_translation` | `POST /v3/video-translations` | public | pinned contract |
| `list_video_translations` | `GET /v3/video-translations` | public | pinned contract |
| `get_video_translation` | `GET /v3/video-translations/{video_translation_id}` | public | pinned contract |
| `update_video_translation` | `PATCH /v3/video-translations/{video_translation_id}` | public | pinned contract |
| `delete_video_translation` | `DELETE /v3/video-translations/{video_translation_id}` | public | pinned contract |
| `list_video_translation_languages` | `GET /v3/video-translations/languages` | public | pinned contract |
| `create_proofread` | `POST /v3/video-translations/proofreads` | disabled | needs separate pricing |
| `get_proofread` | `GET /v3/video-translations/proofreads/{proofread_id}` | public | pinned contract |
| `download_proofread_srt` | `GET /v3/video-translations/proofreads/{proofread_id}/srt` | public | pinned contract |
| `upload_proofread_srt` | `PUT /v3/video-translations/proofreads/{proofread_id}/srt` | public | pinned contract |
| `generate_from_proofread` | `POST /v3/video-translations/proofreads/{proofread_id}/generate` | public | pinned contract |
| `create_lipsync` | `POST /v3/lipsyncs` | public | pinned contract |
| `list_lipsyncs` | `GET /v3/lipsyncs` | public | pinned contract |
| `get_lipsync` | `GET /v3/lipsyncs/{lipsync_id}` | public | pinned contract |
| `update_lipsync` | `PATCH /v3/lipsyncs/{lipsync_id}` | public | pinned contract |
| `delete_lipsync` | `DELETE /v3/lipsyncs/{lipsync_id}` | public | pinned contract |
| `create_hyperframes_render` | `POST /v3/hyperframes/renders` | public | pinned contract |
| `list_hyperframes_renders` | `GET /v3/hyperframes/renders` | public | pinned contract |
| `get_hyperframes_render` | `GET /v3/hyperframes/renders/{render_id}` | public | pinned contract |
| `delete_hyperframes_render` | `DELETE /v3/hyperframes/renders/{render_id}` | public | pinned contract |
| `get_user_me` | `GET /v1/user/me` | legacy | preview / account-gated |
| `get_current_user` | `GET /v3/users/me` | operator | pinned contract |
| `create_workflow_execution` | `POST /v1/workflows/executions` | legacy | preview / account-gated |
| `create_graph_execution` | `POST /v1/workflows/graph-executions` | legacy | preview / account-gated |
| `get_workflow_execution` | `GET /v1/workflows/executions/{execution_id}` | legacy | preview / account-gated |
| `list_workflows` | `GET /v1/workflows` | legacy | preview / account-gated |
| `get_avatar_group` | `GET /v3/avatars/{group_id}` | public | pinned contract |
| `update_avatar_group` | `PATCH /v3/avatars/{group_id}` | public | pinned contract |
| `delete_avatar_group` | `DELETE /v3/avatars/{group_id}` | public | pinned contract |
| `create_avatar_consent` | `POST /v3/avatars/{group_id}/consent` | excluded | pinned contract |
| `list_avatar_looks` | `GET /v3/avatars/looks` | public | pinned contract |
| `get_avatar_look` | `GET /v3/avatars/looks/{look_id}` | public | pinned contract |
| `update_avatar_look` | `PATCH /v3/avatars/looks/{look_id}` | public | pinned contract |
| `delete_avatar_look` | `DELETE /v3/avatars/looks/{look_id}` | public | pinned contract |
| `list_webhook_event_types` | `GET /v3/webhooks/event-types` | operator | pinned contract |
| `list_webhook_endpoints` | `GET /v3/webhooks/endpoints` | operator | pinned contract |
| `create_webhook_endpoint` | `POST /v3/webhooks/endpoints` | operator | pinned contract |
| `update_webhook_endpoint` | `PATCH /v3/webhooks/endpoints/{endpoint_id}` | operator | pinned contract |
| `delete_webhook_endpoint` | `DELETE /v3/webhooks/endpoints/{endpoint_id}` | operator | pinned contract |
| `rotate_webhook_endpoint_secret` | `POST /v3/webhooks/endpoints/{endpoint_id}/rotate-secret` | operator | pinned contract |
| `list_webhook_events` | `GET /v3/webhooks/events` | operator | pinned contract |
| `search_assets` | `GET /v3/assets/search` | public | preview / account-gated |
| `upload_asset` | `POST /v3/assets` | public | pinned contract |
| `list_assets` | `GET /v3/assets` | public | preview / account-gated |
| `get_asset` | `GET /v3/assets/{asset_id}` | public | pinned contract |
| `delete_asset` | `DELETE /v3/assets/{asset_id}` | public | pinned contract |
| `create_asset_upload` | `POST /v3/assets/direct-uploads` | internal | pinned contract |
| `complete_asset_upload` | `POST /v3/assets/{asset_id}/complete` | internal | pinned contract |
| `get_video_agent_session` | `GET /v3/video-agents/{session_id}` | public | pinned contract |
| `send_video_agent_message` | `POST /v3/video-agents/{session_id}` | public | pinned contract |
| `get_video_agent_resource` | `GET /v3/video-agents/{session_id}/resources/{resource_id}` | public | pinned contract |
| `list_video_agent_session_videos` | `GET /v3/video-agents/{session_id}/videos` | public | pinned contract |
| `stop_video_agent_session` | `POST /v3/video-agents/{session_id}/stop` | public | pinned contract |
| `get_ai_clipping` | `GET /v3/ai-clipping/{job_id}` | public | pinned contract |
| `delete_ai_clipping` | `DELETE /v3/ai-clipping/{job_id}` | public | pinned contract |
| `list_ai_clipping` | `GET /v3/ai-clipping` | public | pinned contract |
| `create_ai_clipping` | `POST /v3/ai-clipping` | public | pinned contract |
| `create_filler_word_removal` | `POST /v3/filler-word-removals` | public | pinned contract |
| `get_filler_word_removal` | `GET /v3/filler-word-removals/{filler_word_removal_id}` | public | pinned contract |
| `create_video_batch` | `POST /v3/videos/batches` | public | pinned contract |
| `get_video_batch` | `GET /v3/videos/batches/{batch_id}` | public | pinned contract |
| `bulk_video_statuses` | `GET /v3/videos/statuses` | public | pinned contract |
| `create_video_translation_batch` | `POST /v3/video-translations/batches` | public | pinned contract |
| `get_video_translation_batch` | `GET /v3/video-translations/batches/{batch_id}` | public | pinned contract |
| `bulk_video_translation_statuses` | `GET /v3/video-translations/statuses` | public | pinned contract |
| `create_lipsync_batch` | `POST /v3/lipsyncs/batches` | public | pinned contract |
| `get_lipsync_batch` | `GET /v3/lipsyncs/batches/{batch_id}` | public | pinned contract |
| `bulk_lipsync_statuses` | `GET /v3/lipsyncs/statuses` | public | pinned contract |
| `create_asset_upload_batch` | `POST /v3/assets/direct-uploads/batches` | internal | pinned contract |
| `complete_asset_batch` | `POST /v3/assets/complete/batches` | internal | pinned contract |
| `get_asset_batch` | `GET /v3/assets/batches/{batch_id}` | public | pinned contract |
| `bulk_asset_statuses` | `GET /v3/assets/statuses` | public | pinned contract |
| `create_podcast` | `POST /v3/podcasts` | public | preview / account-gated |
| `list_podcasts` | `GET /v3/podcasts` | public | preview / account-gated |
| `get_podcast` | `GET /v3/podcasts/{podcast_id}` | public | preview / account-gated |
| `delete_podcast` | `DELETE /v3/podcasts/{podcast_id}` | public | preview / account-gated |
| `create_workflow` | `POST /v3/workflows` | public | preview / account-gated |
| `list_workflow_definitions` | `GET /v3/workflows` | public | preview / account-gated |
| `get_workflow` | `GET /v3/workflows/{workflow_id}` | public | preview / account-gated |
| `update_workflow_draft` | `PATCH /v3/workflows/{workflow_id}` | public | preview / account-gated |
| `publish_workflow_version` | `POST /v3/workflows/{workflow_id}/versions` | public | preview / account-gated |
| `list_workflow_versions` | `GET /v3/workflows/{workflow_id}/versions` | public | preview / account-gated |
| `get_workflow_version` | `GET /v3/workflows/{workflow_id}/versions/{version_number}` | public | preview / account-gated |
| `get_workflow_node_types` | `GET /v3/workflows/node-types` | public | preview / account-gated |
| `create_workflow_run` | `POST /v3/workflow-runs` | public | preview / account-gated |
| `list_workflow_runs` | `GET /v3/workflow-runs` | public | preview / account-gated |
| `get_workflow_run` | `GET /v3/workflow-runs/{run_id}` | public | preview / account-gated |
| `cancel_workflow_run` | `POST /v3/workflow-runs/{run_id}/cancel` | public | preview / account-gated |
| `list_workflow_run_nodes` | `GET /v3/workflow-runs/{run_id}/nodes` | public | preview / account-gated |
| `create_video_quality_comparison` | `POST /v3/video-quality/comparisons` | disabled | needs separate pricing; preview |
| `get_video_quality_comparison` | `GET /v3/video-quality/comparisons/{comparison_id}` | public | preview / account-gated |
| `create_video_quality_comparison_batch` | `POST /v3/video-quality/comparisons/batches` | disabled | needs separate pricing; preview |
| `get_video_quality_comparison_batch` | `GET /v3/video-quality/comparisons/batches/{batch_id}` | public | preview / account-gated |
| `upload_assets_batch` | `POST /v3/assets/direct-uploads/batches` | synthetic | pinned contract |
