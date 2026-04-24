# Generation Server Service

Shared generation and planning backend used by both the main Gemzy API and the
Gemzy Moments API.

## Included

- `generation_server/`: FastAPI worker package.
- `scripts/`: Deployment helper for the generation image.

## Local development

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn generation_server.app:app --host 0.0.0.0 --port 8100 --reload
```

The service depends on the shared prompt package in `../../packages/prompting`.

## Docker

Build from the monorepo root:

```sh
docker build -t gemzy-generation -f services/generation-server/Dockerfile .
```

## Ops

- Deploy script: `scripts/deploy-gen.sh`
