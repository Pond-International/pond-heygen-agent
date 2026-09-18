# Run the examples

These files are complete Pond Protocol `1.0` requests. Run the commands from the
repository root after [deploying the agent](../README.md#set-up-and-deploy) and
[synchronizing its Access Key after submission on Pond](../README.md#submit-on-pond-and-configure-the-access-key).

| Request | Action | Output | Usage |
| --- | --- | --- | --- |
| [list-voices.json](list-voices.json) | `list_voices` | `result.json` | Read-only; zero video seconds |
| [generate-video.json](generate-video.json) | `generate_video` | An MP4 from a welcome brief | Paid generation; actual completed video seconds |

Both use the same asynchronous submission and polling interface. Start with the
voice list to exercise that interface without generating a video. The deployment
still needs valid credentials and `generation_ready: true`.

## Prepare the shell

Use the actual HTTPS base URL printed by Modal. Load the Pond access key from the
local `.env` synchronized with Pond and the Modal secret; the commands do not
print the key.

```sh
export AGENT_BASE_URL='https://YOUR-WORKSPACE--pond-heygen-agent-web.modal.run'
export POND_AGENT_ACCESS_KEY="$(uv run python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["POND_AGENT_ACCESS_KEY"])')"
curl --fail --silent --show-error "$AGENT_BASE_URL/health"
```

Do not substitute the HeyGen API key for the Pond access key. The caller uses the
Pond key; the backend uses its own HeyGen secret.

## Submit the selected request

Select one JSON file and read its `run_id` for the matching idempotency header:

```sh
export EXAMPLE_REQUEST='examples/list-voices.json'
export RUN_ID="$(uv run python -c 'import json, sys; print(json.load(open(sys.argv[1]))["run_id"])' "$EXAMPLE_REQUEST")"

curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/runs" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0' \
  -H "Idempotency-Key: $RUN_ID" \
  -H 'Content-Type: application/json' \
  --data-binary "@$EXAMPLE_REQUEST"
```

To generate the welcome video, select `examples/generate-video.json` instead and
rerun this block, including the `RUN_ID` assignment. **That request spends HeyGen
credits.** Its ten-second target is not a duration or cost guarantee.

A new asynchronous run returns HTTP 202. The following response is illustrative;
copy the `task_id` from your actual response:

```json
{
  "task_id": "task_0123456789abcdef0123456789abcdef01234567",
  "run_id": "run_example_voices_001",
  "status": "queued",
  "updated_at": "2026-09-18T12:00:00Z",
  "poll_after_ms": 20000
}
```

If the response contains `error`, resolve it before polling. A terminal retry can
return HTTP 200 with the saved result directly; inspect `status` before deciding
whether there is more work to poll.

## Poll the task

Wait `poll_after_ms` milliseconds, then run:

```sh
export TASK_ID='task_REPLACE_WITH_RETURNED_ID'
curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/tasks/$TASK_ID" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0'
```

Run the polling command again at the returned interval while status is `queued`
or `running`. This implementation requests a 20-second interval. Polling schedules
provider checks and result collection, so continue within the request's 30-minute
deadline.

| Terminal status | Next step |
| --- | --- |
| `completed` | Read `output`, download `artifacts`, and inspect `usage` |
| `failed` | Read `error.code` and `error.message`; inspect uncertain provider jobs before a new run |
| `expired` | The deadline elapsed; HeyGen may still finish and charge |

HTTP 200 from the task endpoint alone does not mean generation succeeded. Terminal
responses omit `poll_after_ms`.

## Download the result

For each item in `artifacts`, the downloadable link is at `file.url`; `file.name`
and `file.media_type` describe it. The voice-listing action returns `result.json`.
The welcome-video action returns an MP4.

Copy the exact signed URL from the completed response. Keep it quoted so the
shell preserves its query parameters:

```sh
umask 077
mkdir -p .local/examples
export ARTIFACT_URL='REPLACE_WITH_EXACT_SIGNED_FILE_URL'
curl --fail --silent --show-error "$ARTIFACT_URL" \
  --output .local/examples/result.json
```

For the video example, use `--output .local/examples/video.mp4` instead. Signed
links do not require the Pond bearer header. They grant access to anyone holding
them until expiry; save files within seven days and keep the links private.
`.local/` is excluded from Git and release packages.

`list_voices` reports zero video seconds. A 9.7-second completed video reports:

```json
{"unit_of_measurement":"other","quantity":10}
```

See the [metering policy](../docs/action-policy.md#video-second-metering) for how
actual duration maps to the example price.

## Retry or customize a request

Keep the same `run_id`, body, and `Idempotency-Key` to retry the same operation.
An unchanged retry returns its saved task/result; changing parameters under the
same ID returns HTTP 409. The example IDs are fixed, so submitting an example a
second time reuses the first run.

For a new operation, copy the request into `.local/examples/`, edit it there, and
assign a new, unique `run_id`. Set `EXAMPLE_REQUEST` to that local path and rerun
the submission block so the header is read from the updated JSON. In your own
integration, supply the actual `agent_id`, `conversation_id`, and `user.id` from
Pond; the examples use illustrative identities.

Read the chosen action's schema from `/manifest` before changing `parameters`.
Convenience actions require `video/mp4` in `accepted_output_modes`. Native actions
require `application/json` plus any desired media types. The voice-listing example
needs no parameters; native mutations may require `confirm` and
`rights_confirmed` where advertised.

A timeout or unknown submission outcome can still incur a provider charge.
Follow the [recovery procedure](../docs/deployment.md#recover-an-uncertain-submission)
before trying that work under a fresh run ID. Consult the
[protocol reference](../docs/protocol.md#retries-and-errors) for status codes.
