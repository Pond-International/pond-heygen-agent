# Finite HeyGen toolset

The registry is compiled offline from the checked-in official OpenAPI 3.1 snapshot
at `src/pond_heygen_agent/data/heygen-v3.json`. It contains all 148 native operations
and 337 source schemas, including legacy routes for auditability. No registry or
manifest call performs networking. Snapshot SHA-256:
`ad0dfee515c74f645da1e2f085f5d95bef6a78dfe12e22e769ec0333ceee45c0`.

| Classification | Native operations | Treatment |
| --- | ---: | --- |
| Public finite v3 | 114 | Public actions with explicit completion families |
| Operator only | 8 | Account profile and webhook administration; omitted from public manifest |
| Live/consent excluded | 6 | Five live-avatar operations and one consent-link operation |
| Internal upload steps | 4 | Covered by completed single/batch upload workflows |
| Completed speech alternative | 1 | Streaming model speech covered by `generate_model_speech` |
| Legacy | 15 | v1/v2 classified separately, never silently substituted |

One synthetic `upload_assets_batch` action completes the native batch upload
workflow, giving 115 registry candidates before the runtime pricing policy. Eight
standalone non-video actions are disabled under the current
[pricing policy](action-policy.md#disabled-standalone-non-video-actions), leaving
107 enabled native/wrapper actions. The two convenience actions bring the
manifest total to 109. The classifications above describe the underlying
registry; the [coverage inventory](heygen-coverage.md) shows current enablement. `coverage()` returns an entry for every native operation
plus the synthetic workflow; each entry includes its classification and reason.

Operations marked `x-excluded` in the official snapshot remain identifiable by
both `provider_preview` and `x-excluded` in registry and coverage records. The
manifest explains that their account availability has not been live verified.
Schema presence does not establish account entitlement or production availability.

## Runtime interface

`operations()` returns isolated rows keyed by snake_case operation IDs, removing
a terminal `V3`. Supported public and operator-only operations are included.
Each row has `method`, `path`, `input_schema`, `access`, `completion`, `transport`,
`mutation`, `requires_confirm`, `rights_required`, `supports_idempotency`, and
`requires_idempotency`. Idempotency flags come from declared native header
parameters, including referenced parameters; they do not authorize retries.

`action_manifest()` returns the enabled public Pond actions after policy filtering. Each standalone schema retains
native descriptions, enums, required fields, unions, and reachable local `$defs`.
Each action includes an operation-specific guide and schema-valid example covering
selection, essential inputs, quality choices, preparation, ID discovery, cost,
and actual completion. Example IDs, URLs, workflow node types/ports, and template
variable names are structural illustrations and must be replaced with real values.

`validate_action(id, parameters)` validates JSON without coercion and returns a
copy. Errors identify safe field paths and constraints without returning input
values or unknown field names. User-supplied headers, credentials, and callbacks
are rejected recursively, including common casing/hyphen aliases. Arbitrary
wrapper keys are rejected. `create_video_agent` permits only `mode=generate` and
inserts that mode if omitted. A revision has the native `message` schema and must
be bounded by the runtime: an old video or human-input pause is not success.

Path/query/body remain separate named objects. Mutation confirmation and source
rights confirmation are wrapper fields, never forwarded as native body fields.
The runtime must separately enforce public/operator access, per-user ownership,
safe media fetching, resource limits, one-shot session behavior, and output
handling. Schema validity does not grant permission to access a resource.

`list_assets` omits the native required `query.username` from public inputs and
declares `operator_parameters=["query.username"]`. The runtime binds that value
to the configured/authenticated operator account and filters records by user
ownership. Public callers must not supply account usernames or credentials.

## Completed uploads

`upload_asset` uses `transport=multipart_file` and `completion=asset`.
Its `body.file` is `{url, name, media_type}`. The runtime downloads validated bytes,
sends a real multipart upload, and verifies the asset is usable.

`upload_assets_batch` uses `transport=upload_batch` and `completion=asset_batch`.
Its body is `{files: [{url, name, media_type}], title?: string}`, with one to 100
entries. The runtime obtains bytes and exact lengths, creates native direct-upload
slots, PUTs each file, finalizes the batch, and polls all pages/items to completion.
Per-file and aggregate transfer limits belong to runtime configuration and must
be checked before spending on uploads. A presigned URL or allocated asset ID is
not a completed upload. Native half-upload operations are not public actions.

## Completion semantics

Reads/searches intentionally complete with a `snapshot`, even when the underlying
resource remains in progress. Synchronous metadata mutations return `mutation`.
Paid/creative submissions have explicit families: video, session, avatar, voice,
professional_voice, speech, brand_kit, translation, proofread, lipsync, hyperframes,
clipping, background_removal, filler_removal, podcast, workflow, comparison,
asset, and their supported batch forms. Submission IDs alone never satisfy
asynchronous creation. Multi-language jobs and batches must account for every
child and page, including individual failures.

The underlying completion handler for proofread creation finishes when editable
proofreads are ready (new proofread creation is currently disabled); uploading an
edited SRT and generating final translated video are separate finite actions.
Workflow authoring/publishing completes its metadata change without executing the
graph. A workflow run completes only when its execution and outputs settle.

Professional retraining retains the existing voice ID. If the provider offers no
distinct training receipt or other evidence that the requested new training has
finished, an already-ACTIVE voice cannot establish completion. The runtime must
report that outcome as unverifiable, not reuse the old active voice as proof.
