# Gemzy Moments API Service

> **Archived legacy service.** This code documents the retired Moments mobile
> backend. Do not deploy it against the Gemzy production database after the
> legacy `people` and `moments` schemas are removed. Read `ARCHIVED.md` first.

FastAPI backend retained for legacy Moments mobile reference.

## Included

- `server/`: API package.
- `sql/`: Database schema and migration assets.

## Local development

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn server.main:app --reload
```

This service uses the shared generation service in `../generation-server` via
`GENERATION_SERVER_URL`.

## Docker

Build from the monorepo root:

```sh
docker build -t gemzy-moments-server -f services/gemzy-moments-api/Dockerfile .
```
