# Deployment and operations

This guide uses your own HeyGen and Modal accounts. Keep credentials and live
request ledgers out of source control and release artifacts.

## Initial deployment

Install Python 3.12 or later and [uv](https://docs.astral.sh/uv/), then run from
the repository root:

```sh
uv sync --python 3.12
uv run modal setup
cp .env.example .env
chmod 600 .env
```

Edit `.env` privately to set `HEYGEN_API_KEY`. The remaining credential fields
can be left blank for setup to generate:

```sh
uv run python -m pond_heygen_agent.operator setup
uv run modal deploy -m pond_heygen_agent.modal_app
```

| Resource | Default name | Purpose |
| --- | --- | --- |
| Modal app | `pond-heygen-agent` | HTTP API and coordinator |
| Modal secret | `pond-heygen-agent-secrets` | Provider, Pond access, and signing keys |
| Modal Dict | `pond-heygen-agent-state` | Configuration, task state, ownership, and idempotency |
| Modal Volume | `pond-heygen-agent-artifacts` | Completed output files |

Setup writes `.env` with mode `0600` and updates the named Modal secret.
It generates an initial `POND_AGENT_ACCESS_KEY` if one is missing so the server
can start. After submitting the agent on Pond, configure the server with the
Access Key from the agent's publishing page as described below.
`ARTIFACT_SIGNING_KEY` signs download links and should remain stable across
redeployments; rotating it invalidates previously issued artifact links.

Set the base URL to the exact HTTPS URL printed by Modal, without a path:

```sh
export AGENT_BASE_URL='https://YOUR-WORKSPACE--pond-heygen-agent-web.modal.run'
uv run python -m pond_heygen_agent.operator configure --base-url "$AGENT_BASE_URL"
curl --fail --silent --show-error "$AGENT_BASE_URL/health"
curl --fail --silent --show-error "$AGENT_BASE_URL/manifest" > /tmp/heygen-manifest.json
```

`configure` verifies the API key with read-only HeyGen requests and discovers
public avatar/voice presets. It prints readiness and preset counts, without
printing credentials or account data. `generation_ready: true` establishes
configuration readiness; it does not prove paid acceptance for every action.

The `configure` command initializes the entire configuration record. Do not
rerun it over custom sharing or access settings without preserving those settings.
A code-only redeployment keeps the current Dict configuration.

## Configure Pond

Submit the agent on Pond using the deployed HTTPS base URL. Public `/manifest`
discovery does not require the runtime Access Key.

After submitting the agent, copy the Access Key from its Pond publishing page
and configure it on the agent server. Edit your local `.env` so
`POND_AGENT_ACCESS_KEY` is exactly that value, then update Modal:

```sh
uv run python -m pond_heygen_agent.operator setup
uv run modal deploy -m pond_heygen_agent.modal_app
```

These commands sync the key to the Modal secret and start the deployment with
it. Repeat them when the Pond Access Key changes, preserving
`ARTIFACT_SIGNING_KEY`. There is no need to rerun `configure` for a key update.

Pond and the server must have matching keys before authenticated runtime checks
or requests can succeed. `/health` readiness does not verify that match.

Review the imported actions and pricing before publishing the listing. The
default plan is:

| Field | Value |
| --- | --- |
| Type | `pay_as_you_go` |
| `amount_minor` | `13` |
| `usage_quantity` | `1` |
| `usage_unit` | `other` |
| `custom_usage_unit` | `video_second` |

This represents $0.13 per completed video-second. The manifest prefills/imports a
draft; redeploying does not change a previously saved Pond price. Save any pricing
change in Pond as well. See [action and pricing policy](action-policy.md).

Only the Pond access key belongs in the listing. Keep the HeyGen API key and
artifact signing key in the operator environment and Modal secret.

## Deploy before obtaining a HeyGen key

Use `setup --allow-unconfigured`, then deploy and configure the base URL as above.
Public discovery works, but `/health` reports `generation_ready: false` and new
`/runs` requests return HTTP 503. Once a key is available, run setup, deploy, and
configure again. Preserve any custom configuration before rerunning configure.

## Presets and shared resources

By default, configure discovers public avatar and voice presets. To opt
account-owned presets into the public agent, set `HEYGEN_PRESETS_JSON` in `.env`
before initial configuration:

```json
{"avatars":[{"id":"YOUR_LOOK_ID"}],"voices":[{"id":"YOUR_VOICE_ID"}]}
```

Configure verifies the IDs and derives display names/language from HeyGen.
Configured presets appear in the public manifest and are available to callers.
Select only assets intended for that use. Video Agent session memory is disabled;
HeyGen's own account and retention policies still apply.

Additional read-only resources can be explicitly shared through the Modal Dict's
`config.shared_resources` mapping, keyed by resource kind such as `template`,
`asset`, `brand_kit`, `brand_glossary`, or `professional_voice`. Shared IDs cannot
be updated or deleted by callers. `config.consent_approved_groups` should contain
only groups whose unattended consent prerequisite the operator has verified.
Normal ownership checks still apply. Preserve existing `config` fields when
updating these settings.

Private provider resources are scoped by `(agent_id, user.id)`. The shared access
key authenticates a trusted Pond caller, which supplies those identities. This
backend is not an end-user authentication service; do not distribute the access
key to untrusted clients that could claim another user's identity.

## Update a deployment

Run the local checks in the README, then deploy the updated source:

```sh
uv run modal deploy -m pond_heygen_agent.modal_app
```

Run setup again only when the Modal secret needs updating. Keep signing/access
keys stable unless rotation is intentional. Use a dedicated Modal environment or
coordinate app, Dict, Volume, and secret names in `modal_app.py` and `operator.py`
when operating multiple isolated deployments.

The web API requests 0.25 CPU/256 MiB, and the coordinator requests 0.5 CPU/512 MiB.
Both use zero minimum containers and a two-second idle window. At most two
provider slots are active. Polling drives collection, at most once per task every
20 seconds; there is no recurring cron or render-wait worker. Modal compute,
storage, and transfer costs and HeyGen charges still apply.

## Recover an uncertain submission

A timeout does not guarantee HeyGen cancellation or a refund. If submission may
have succeeded but its result is unknown, the agent does not resubmit it and
retains the provider slot. Inspect the task and your HeyGen dashboard before
using a new run ID.

Only after confirming the provider job finished or never started, release its
uncertain slot:

```sh
uv run python -m pond_heygen_agent.operator release-slot \
  --task-id task_REPLACE_WITH_ACTUAL_ID --confirmed-provider-finished
```

## Retention and cleanup

Save returned artifacts within seven days. Signed URLs grant access to anyone
holding them until expiry. Polling must continue within the original deadline to
collect the provider result; a provider job can finish even if the client stops
polling.

Task/artifact cleanup is opportunistic during activity. To invoke it explicitly:

```sh
uv run python -m pond_heygen_agent.operator cleanup
```

Cleanup removes expired local artifacts and task details. Small idempotency
tombstones prevent late retries from generating again. Uncertain active jobs
remain available for operator recovery. Cleanup does not delete HeyGen account
videos, and physical file removal is not guaranteed at the exact expiry time.

## Verify a real request

After checking `/health` and `/manifest`, follow the [protocol walkthrough](protocol.md)
to submit a request and poll it to completion. Video-generation requests spend
HeyGen credits. Confirm the returned media and usage before opening the agent
to callers. Inspect uncertain jobs before retrying them under a new run ID.

Keep live request/result records private. Never attach credential files, signed
links, or unredacted records to public issues.
