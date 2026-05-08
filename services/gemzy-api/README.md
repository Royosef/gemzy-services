# Gemzy API Service

Core FastAPI backend for the main Gemzy app.

## Included

- `server/`: API package.
- `sql/`: Database schema and migration assets.
- `scripts/`: Deploy, reload, rollback, and load-test helpers.
- `docs/`: Backend runbook and prompt-engine notes.

## Local development

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn server.main:app --reload
```

The API uses the shared generation service in `../generation-server` and the
shared prompt package in `../../packages/prompting`.

## Docker

Build from the monorepo root:

```sh
docker build -t gemzy-server -f services/gemzy-api/Dockerfile .
```

## Ops

- Deploy script: `scripts/deploy.sh`
- Reload helper: `scripts/reload_server_dev.sh`
- SQL assets: `sql/`

## Prompt verification

- Runbook: `docs/prompt-management-e2e-verification.md`
- Smoke helper: `python scripts/verify_prompt_management_e2e.py`

The smoke helper verifies local/shared-dev alignment for:

- dashboard prompt-admin API base URL
- gemzy app runtime API base URL
- shared Supabase project wiring
- `/generations/ui-config`

Optional inputs:

- `PROMPT_ENGINE_BEARER_TOKEN` for authenticated admin API checks
- `SUPABASE_SERVICE_KEY` plus `--engine-slug <slug>` for direct prompt-table verification
