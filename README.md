# gemzy-server

Shared backend monorepo for Gemzy services.

## Layout

- `services/gemzy-api`: Core Gemzy API, backend docs, deploy scripts, and SQL assets.
- `services/gemzy-moments-api`: Gemzy Moments API and SQL assets.
- `services/generation-server`: Shared image-generation and planner service used by both APIs.
- `packages/prompting`: Shared prompt registry helpers and prompt-definition data.

## Local development

### Gemzy API

```sh
cd services/gemzy-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn server.main:app --reload
```

### Generation server

```sh
cd services/generation-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn generation_server.app:app --host 0.0.0.0 --port 8100 --reload
```

### Gemzy Moments API

```sh
cd services/gemzy-moments-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
uvicorn server.main:app --reload
```

## Notes

- `GENERATION_SERVER_URL` should point both API services at `services/generation-server`.
- Secrets are intentionally not committed here. Copy the service-level `.env.example` files and fill values locally.
- Docker builds now run from the repo root with service-specific Dockerfiles.
