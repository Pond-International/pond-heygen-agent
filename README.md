# Pond HeyGen Agent

A [Pond Protocol](https://docs.joinpond.ai/update/docs/build-and-publish-an-agent-on-pond)
reference implementation from **Pond-International** for asynchronous video
generation with HeyGen. Use it to learn how to expose an agent through a manifest,
accept authenticated requests, track tasks, deliver files, and report usage.

HeyGen renders the videos. [Modal](https://modal.com/docs/guide) hosts the Python
API, task coordinator, and storage using CPU workers that scale to zero. The
walkthrough below deploys the agent and generates a welcome video from a brief.

## Set up and deploy

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/), a Modal account,
and a HeyGen API key with access to video generation.

```sh
git clone https://github.com/Pond-International/pond-heygen-agent.git
cd pond-heygen-agent
uv sync --python 3.12
uv run modal setup
cp .env.example .env
chmod 600 .env
```

Edit `.env` to set `HEYGEN_API_KEY`, then run:

```sh
uv run python -m pond_heygen_agent.operator setup
uv run modal deploy -m pond_heygen_agent.modal_app
```

Setup initializes the credentials in `.env` and the Modal secret. Copy the HTTPS
base URL printed by Modal into `AGENT_BASE_URL`:

```sh
export AGENT_BASE_URL='https://YOUR-WORKSPACE--pond-heygen-agent-web.modal.run'
uv run python -m pond_heygen_agent.operator configure --base-url "$AGENT_BASE_URL"
curl --fail --silent --show-error "$AGENT_BASE_URL/health"
```

Check for `generation_ready: true`. Initial configuration verifies your HeyGen
credentials and discovers avatar/voice presets through read-only calls. See
[deployment and operations](docs/deployment.md) for custom presets, updates,
and recovery. Rerunning `configure` replaces the configuration record, including
custom sharing settings.

## Submit on Pond and configure the access key

Submit the agent on Pond using the deployed HTTPS **base URL**. Pond reads the
public `GET /manifest` endpoint to discover its actions and schemas.

**After submitting the agent on Pond, configure its Access Key on the agent
server.** Copy the Access Key from the agent's publishing page and set
`POND_AGENT_ACCESS_KEY` in your local `.env` to that exact value. Then update the
Modal secret and redeploy:

```sh
uv run python -m pond_heygen_agent.operator setup
uv run modal deploy -m pond_heygen_agent.modal_app
```

Pond and the server must use the same Access Key for authenticated requests.
Keep the HeyGen and artifact signing keys in the backend; they are separate from
the Pond Access Key.

The example advertises **$0.13 per completed video-second**. Review and save the
pricing plan in Pond before accepting paid requests. Actual durations of distinct
completed videos are summed and rounded up once; a 9.7-second output reports 10
units. See [metering and pricing](docs/action-policy.md#video-second-metering) and
the [Pond publishing guide](https://docs.joinpond.ai/update/docs/build-and-publish-an-agent-on-pond).

## Try a request

Run these commands from the repository root, in the same shell as the setup
above. Load the synchronized Pond access key without printing its value:

```sh
export POND_AGENT_ACCESS_KEY="$(uv run python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["POND_AGENT_ACCESS_KEY"])')"
```

The [welcome-video request](examples/generate-video.json) supplies a brief, a
ten-second target, and the full Pond request envelope. **Submitting it spends
HeyGen credits.** The target is approximate; billing uses actual completed video
duration. For a read-only first request, use the [voice-listing example](examples/README.md).

```sh
curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/runs" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0' \
  -H 'Idempotency-Key: run_example_video_001' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/generate-video.json
```

A new run returns HTTP 202 with a `task_id`, a status such as `queued`, and
`poll_after_ms: 20000`. Copy the returned task ID and poll after 20 seconds:

```sh
export TASK_ID='task_REPLACE_WITH_RETURNED_ID'
curl --fail-with-body --silent --show-error \
  "$AGENT_BASE_URL/tasks/$TASK_ID" \
  -H "Authorization: Bearer $POND_AGENT_ACCESS_KEY" \
  -H 'X-Agent-Protocol-Version: 1.0'
```

Repeat the poll at the requested interval until `status` is `completed`, `failed`,
or `expired`. Polling also drives result collection. On completion, open the
video's `file.url` in the `artifacts` array, or follow the
[download instructions](examples/README.md#download-the-result). Save the video
within seven days; anyone holding its signed URL can access it until expiry.

An unchanged retry with the same `run_id` returns the saved task/result. To start
a separate video, use a new `run_id` and matching `Idempotency-Key`. Check an
uncertain provider submission before starting another run: a timeout does not
cancel HeyGen or reverse charges. The [examples guide](examples/README.md) explains
retries, errors, and both sample requests.

## Available actions

Start with the two convenience actions:

| Action | Input | Result |
| --- | --- | --- |
| `generate_video` | A creative brief with optional reference files | An MP4 planned and rendered by HeyGen |
| `generate_presenter_video` | A final script and an avatar or permitted portrait | An MP4 preserving the supplied script |

Both accept **5–60 seconds**, defaulting to 30 seconds. This is the example agent's
policy; upstream limits vary by HeyGen endpoint.

The manifest also exposes 107 native/wrapper actions for a total of **109**.
These cover video creation, translation, lipsync, templates, clips, assets,
finite batches, and video-producing workflows. Native actions return JSON metadata
and negotiated media. Account and webhook administration are excluded. Some
provider features require additional account access.

Read the [action policy](docs/action-policy.md) for render and media limits, or
the [coverage inventory](docs/heygen-coverage.md) for the full catalog. The
[protocol reference](docs/protocol.md) documents endpoints, envelopes, and errors.

## Understand and customize the code

Start with the [code walkthrough](docs/architecture.md). It follows one request
from the HTTP API through provider submission, task polling, artifact delivery,
and metering, then identifies the files to change for common customizations.

```text
src/pond_heygen_agent/   Agent implementation and pinned HeyGen schema
examples/               Complete requests and submission instructions
docs/                   Protocol, deployment, architecture, and policy guides
.env.example            Environment variable template
pyproject.toml          Dependencies and package configuration
```

The coordinator uses durable state and a single writer, with at most two active
provider slots. Work runs in short steps as clients poll; runs allow up to 30
minutes. See the walkthrough for the deployment boundaries and failure behavior.

## Development

```sh
uv sync --python 3.12
uv run ruff check .
uv run ruff format --check .
uv build
```

These checks do not call HeyGen. Source and wheel builds explicitly select public
files, excluding local secrets, run records, caches, and worktrees.

## License

[MIT](LICENSE), copyright 2026 Pond-International. HeyGen and Modal services
remain subject to their own terms. The bundled HeyGen OpenAPI snapshot is
attributed in the [coverage inventory](docs/heygen-coverage.md).
