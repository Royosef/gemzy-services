# Gemzy Moments API Service

FastAPI backend for Gemzy Moments.

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
