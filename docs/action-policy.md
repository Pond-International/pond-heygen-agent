# Action and pricing policy

These are policies of this example agent. They are narrower than the upstream
HeyGen API and may be adapted to a deployment's product and pricing requirements.
The current manifest is the authority for supported parameters.

## Duration and media limits

The two convenience actions, `generate_video` and `generate_presenter_video`,
accept a target of **5–60 seconds**, defaulting to 30. This is an agent policy,
not a claim that HeyGen universally rejects shorter videos. Presenter scripts
are limited to 1,000 characters and are not rewritten. Requested duration is a
target, not a guarantee of output duration or cost.

Briefs accept up to five PNG/JPEG/PDF attachments, 20 MiB combined. Portrait mode
requires one PNG/JPEG and `portrait_permission: true`. Native actions use their
schema's media fields instead of message attachments.

Native transfers support validated images, PDF, MP4/WebM/MOV, WAV/MP3/M4A/Ogg,
JSON, SRT/VTT, and bounded ZIP composition projects. The per-file limit is
100 MiB; an output bundle is limited to 200 MiB and 32 files including JSON.
Upload batches are limited to 100 MiB combined. Container signature validation
does not certify codec quality.

## Render options


The manifest and server validation share the same restricted input schemas.
Cinematic Avatar and Avatar V cannot be selected. Native avatar/image/studio
video creation (including batches and studio scenes) uses 720p and, for avatar
inputs, Avatar III or IV. Omitted/null engines explicitly use IV; omitted/null
video resolutions explicitly use 720p.

Translation and lipsync accept only speed mode, including
batches. HyperFrames accepts draft/standard quality at its minimum supported
1080p resolution; high quality and 4K are unavailable. Explicit template dimensions
must fit 1280x720 or 720x1280 and retain the template's aspect ratio. Disallowed
parameters return HTTP 422 `invalid_input` before a task or provider call is created;
requests are not silently downgraded.

The remaining 109 actions retain these restrictions. Automatic Video Agent, omitted template settings,
podcasts, rendering an existing proofread, and stored workflow execution still use
provider-managed settings. Creative text and workflow inputs are not keyword-filtered.
These restrictions prevent direct premium selections through the controlled native
fields; they are **not a spending cap** or a guarantee of the cheapest provider tier.

## Video-second metering


New runs return `usage: {"unit_of_measurement":"other","quantity":30}` for a
30-second completed video ($3.90). A 60-second video is $7.80. Usage measures actual
completed output, not requested target length. Sum distinct output durations,
then round up once to integer seconds (9.7 seconds becomes 10 units). Decimal
arithmetic avoids float-rounding overcharges.

Batches and translations sum completed videos; clipping sums finished clips, not
source footage. Filler removal uses output duration. Background-removal layers,
captioned copies, previews, and alternative encodings do not add extra units.
Video generation accepting only JSON still meters the newly generated videos.
Read-only catalogs, status reads, downloads, uploads, and resource edits generate
no video seconds. Identical run retries return the same saved quantity.

Use validated provider duration when available. Otherwise the coordinator safely
downloads bounded video and probes it locally with ffprobe (bundled by Modal).
The probe cannot access remote URLs or playlist formats and has a ten-second
timeout. Workflow videos use durable output artifact identities and require media
measurement; arbitrary inline JSON cannot supply trusted video duration. If an
output cannot be identified or measured, the task fails with `usage_unavailable`,
not an estimated charge or a fresh generation attempt.

Failed/expired tasks report zero; partial successful runs meter their completed
outputs only. HeyGen may nevertheless charge for failed tasks, source duration,
minimums, intermediate workflow renders, or non-video work. $0.13/second is a
cost-recovery target, not a guarantee for every action. Premium-render restrictions
are unchanged. Terminal usage is saved with the task; changing the manifest does not rewrite
historical records.

## Disabled standalone non-video actions

Until separately priced, the manifest omits and the server rejects:

- `create_avatar`
- `create_speech`, `generate_model_speech`
- `clone_voice`, `create_model_audio_voice`
- `create_proofread`
- `create_video_quality_comparison`, `create_video_quality_comparison_batch`

These are rejected before any HeyGen request, including direct calls using an old
manifest. Read-only catalogs, semantic voice discovery, existing-resource edits,
uploads, and video generation with ready avatars/voices remain available. Existing
tasks and artifacts remain readable; previously submitted provider jobs can still
be polled without resubmitting generation.

`translate_audio_only` must be false for translation and existing-proofread renders,
including batches. Workflow runs must declare a final video output whose type is
verified against the published graph and provider node catalog before submission.
Graph authoring remains available. Speech and other intermediate work inside a
video-producing task are not separately metered; the provider-managed cost caveat
still applies. These restrictions are not a universal provider spending cap.


## Changing the example price

The default Pond pricing plan is **$0.13 per video-second**, expressed as
`pay_as_you_go`, `amount_minor=13`, `usage_quantity=1`, `usage_unit=other`, and
`custom_usage_unit=video_second`. It is an example deployment policy, not a
universal Pond or HeyGen rate.

Update `PRICING_PLAN` in `src/pond_heygen_agent/video_usage.py` and keep the
pricing descriptions in `protocol.py`, `tool_guides.py`, and this documentation
aligned. Save the new pricing plan in Pond as well: changing the
manifest only prefills/imports a draft and does not update an existing listing.
