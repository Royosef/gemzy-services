# Prompt Management E2E Verification

This runbook verifies the prompt-management flow end to end across:

- `gemzy-dashboard` prompt admin
- `gemzy-services/services/gemzy-api` prompt registry and runtime catalog
- `gemzy` app runtime consumption

Use it after prompt-management changes, auth changes, schema changes, or shared-dev environment changes.

## What must be true

Acceptance means all of these are true:

- a prompt edit made in the dashboard is returned immediately by the prompt admin API
- the related `prompt_engines`, `prompt_engine_versions`, and `prompt_task_routes` rows match the edit in Supabase
- `GET /generations/ui-config` emits the published prompt state
- the `gemzy` app fetches the updated runtime catalog instead of silently staying on fallback config
- generation requests from the app carry the expected `style.prompt_version` and `originalStyle.prompt_version`

## Environment alignment

Before running any smoke checks, verify all three surfaces point at the same shared-dev environment.

### Dashboard

- `gemzy-dashboard/.env`
- `VITE_PROMPT_ENGINE_API_URL`
- `VITE_SUPABASE_URL`

### API service

- `gemzy-services/services/gemzy-api/.env`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

### Gemzy app

- `gemzy/mobile.dev.json`
- `apiBaseUrl`

Important:

- `VITE_PROMPT_ENGINE_API_URL` and `gemzy/mobile.dev.json.apiBaseUrl` should normally target the same shared `gemzy-api` base URL for shared-dev prompt verification.
- If the dashboard points at `localhost:8000` while the app points at a tunnel or deployed API, do not trust an end-to-end result until the mismatch is resolved.

## Dashboard verification

Use an admin account and verify the current prompt admin routes:

- `/admin/prompts`
- `/admin/prompts/routes`
- `/admin/prompts/:engineRef/versions/:versionId`
- `/admin/prompts/:engineRef/diff`

Run this flow:

1. Load the engine index and confirm the list renders without auth or token-refresh errors.
2. Open an existing engine.
3. Create a draft version or edit the current draft.
4. Save the draft.
5. Run preview.
6. Publish the version.
7. Open the route manager and confirm the intended route is active.
8. Refresh the page and confirm the saved state survives reload.

Capture:

- engine `slug`
- published `versionId`
- published `versionNumber`
- `promptVersion` emitted by the version definition
- any changed route `slug`

## Database verification

Immediately after save/publish, verify these tables in the shared Supabase project:

### `prompt_engines`

Confirm:

- `slug`
- `name`
- `task_type`
- `renderer_key`
- `published_version_id`
- `published_version_number`

### `prompt_engine_versions`

Confirm the target version row matches:

- `engine_id`
- `status`
- `version_number`
- `definition`
- `sample_input`
- `change_note`

### `prompt_task_routes`

Confirm:

- `slug`
- `task_type`
- `priority`
- `is_active`
- `engine_id`
- `pinned_version_id`
- `match_rules`

## Runtime catalog verification

Call:

```txt
GET /generations/ui-config
```

Verify:

- the edited engine is present on the intended surface
- the emitted `promptVersion` matches the published version semantics from the dashboard change
- the surface `defaultEngineId` and route-driven engine behavior match the published routing state
- no fallback-only values are masking the published override

## Gemzy app verification

The app-side prompt consumer path is:

- `src/lib/generation-ui-config.ts`
- `src/lib/generation-ui-adapters.ts`
- `src/app/(app)/on-model.tsx`
- `src/app/(app)/create-pure-jewelry.tsx`

Run this flow:

1. Start the app against the same shared-dev API base.
2. Force a config reload or clear the cached generation UI config if needed.
3. Confirm the updated engine metadata appears in the relevant create surface.
4. Confirm an existing style with only `prompt_version` still resolves to the intended engine.
5. Trigger one on-model request and one pure-jewelry request.
6. Inspect the outgoing payloads.

Expected payload fields:

- `style.prompt_version`
- `originalStyle.prompt_version`

## Reusable smoke checks

### Backend

- authenticated admin can `GET /prompt-engines`
- draft create/update/preview/publish round-trip succeeds
- `GET /prompt-engines/routes` reflects the latest saved route
- `GET /generations/ui-config` returns the published prompt metadata

### Dashboard

- prompt admin pages load using the current Supabase auth session
- save, preview, and publish succeed without token or route errors
- route manager reflects the latest route state after refresh

### Gemzy app

- remote generation UI config loads successfully
- fallback config is not masking a remote change
- engine selection and `prompt_version` still agree after publish

## Failure classification

When the flow fails, capture the first broken seam and classify it as one of:

- dashboard save path
- DB persistence path
- runtime catalog emission path
- app cache or app consumption path

For each failure, record:

- route or action attempted
- expected row or payload field
- actual row or payload field
- whether the mismatch is client, API, DB, or app-cache related
