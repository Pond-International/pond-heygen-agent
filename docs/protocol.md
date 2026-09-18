# Pond Protocol walkthrough

The public manifest declares protocol `marketplace-agent`, version `1.0`.
It advertises asynchronous tasks and attachments. Streaming, cancellation, and
feedback endpoints are not implemented.

For commands that submit, poll, and download the included requests, start with
the [examples guide](../examples/README.md). After submitting the agent on Pond,
[configure its Access Key on the server](deployment.md#configure-pond) before
sending authenticated requests. For implementation details, see the
[code walkthrough](architecture.md).

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /manifest` | Public | Action schemas, examples, capabilities, and pricing |
| `GET /health` | Public | Configuration readiness without calling HeyGen |
| `POST /runs` | Bearer key + protocol headers | Validate and submit an idempotent run |
| `GET /tasks/{task_id}` | Bearer key + protocol version | Poll a task and advance collection |
| `GET` / `HEAD /artifacts/{artifact_id}` | Signed URL | Download an output until its expiry |

## Discover actions

```sh
curl --fail --silent --show-error "$AGENT_BASE_URL/manifest"
curl --fail --silent --show-error "$AGENT_BASE_URL/health"
```

Neither endpoint needs authentication. Read the manifest's action schema and
examples before constructing a request. The health check reports configuration
readiness without contacting HeyGen.

## Submit a run

[generate-video.json](../examples/generate-video.json) includes all required Pond
envelope fields: run, agent, conversation, user, messages, action, parameters, and
execution settings. Use a unique `run_id` for each new operation. Reuse the same
ID and body when retrying that operation.

The following command submits a paid generation request. Set `AGENT_BASE_URL` to
your deployment and load `POND_AGENT_ACCESS_KEY` into your shell from your private
credentials. Do not put a literal key in a checked-in script.

```sh
curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/runs" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0' \
  -H 'Idempotency-Key: run_example_video_001' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/generate-video.json
```

`Idempotency-Key` must equal the JSON `run_id`. A new asynchronous task returns
HTTP 202 with a body shaped like:

```json
{
  "task_id": "task_0123456789abcdef0123456789abcdef01234567",
  "run_id": "run_example_video_001",
  "status": "queued",
  "updated_at": "2026-09-18T12:00:00Z",
  "poll_after_ms": 20000
}
```

The identifiers and timestamp above are illustrative. Save the returned task ID.
Task status may already be `running` when the response arrives.

## Poll to completion

```sh
export TASK_ID='task_REPLACE_WITH_RETURNED_ID'
curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/tasks/$TASK_ID" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0'
```

Wait the returned `poll_after_ms` between requests. Polling dispatches due
coordinator work, including provider status checks and artifact collection. The
maximum run deadline is `1800000` milliseconds (30 minutes).

Terminal statuses are `completed`, `failed`, or `expired`. Completed responses
include `output`, `artifacts`, and `usage`; failures include `error` and zero
reported usage. Terminal responses omit `poll_after_ms`. Download the signed
URLs in `artifacts` before expiry. An actual 9.7-second completed video reports:

```json
{"unit_of_measurement":"other","quantity":10}
```

The `other` unit corresponds to `custom_usage_unit: video_second` in the pricing
plan. See [metering details](action-policy.md#video-second-metering) for batches,
partial results, duplicate encodings, and provider charges.

## Native actions

[list-voices.json](../examples/list-voices.json) demonstrates a read-only native
request. Submit it to `/runs` with `Idempotency-Key: run_example_voices_001`.
Native parameters separate `path`, `query`, and `body`, including only the
sections relevant to the action. Mutations require `confirm: true`; likeness,
voice, and source-material actions require `rights_confirmed: true` where
advertised. These flags are wrapper fields and are not forwarded to HeyGen.

Native actions return a `result.json` artifact plus negotiated completed media.
Include `application/json` and any desired media types in
`execution.accepted_output_modes`. Use schema-defined media fields for native
uploads; message attachments belong to the convenience actions. Caller-selected
HTTP endpoints, headers, and credentials are not accepted.

Asynchronous creation waits for completion; an accepted HeyGen job ID is not a
finished render. Batches and multilingual outputs account for child outcomes.
Read-only status actions return a snapshot, which can describe a provider job
that is still running.

## Retries and errors

| Outcome | HTTP status | Behavior |
| --- | --- | --- |
| Same run ID and matching request | 202 or 200 | Returns saved task/result; no new generation |
| Same run ID with changed request | 409 | Idempotency conflict |
| Missing or invalid access key | 401 | No task accepted |
| Invalid envelope/protocol/idempotency header | 400 | No task accepted |
| Invalid action parameters | 422 | No task accepted |
| Unsupported request content type | 415 | Send `application/json` |
| Generation not configured | 503 | New run not accepted |
| Missing or expired task | 404 | Task unavailable |
| Retired run ID | 410 | Idempotency tombstone prevents regeneration |

A terminal `POST /runs` retry returns HTTP 200 with the saved run result, omitting
`task_id` and `updated_at`. An expired task is represented as `failed` in that
run response. Task polling retains its `expired` status. Clients must inspect the
JSON status; HTTP 200 alone does not establish successful generation.

A provider failure may still incur provider charges. An ambiguous submission is
not automatically repeated. Follow the [operator recovery guide](deployment.md#recover-an-uncertain-submission)
before creating a new run for an uncertain request.
