# Gemzy generation server

This FastAPI package receives generation jobs from the Gemzy APIs, queues them,
resolves reference assets, and drives the configured generation workflow. The
worker emits streaming updates back to the calling API for progress tracking
and incremental result delivery.

## Running locally

1. Configure the required environment variables in `../.env`:
   - `GENERATION_APP_URL`: Public base URL of the calling application server.
   - `GENERATION_SHARED_SECRET`: Shared secret used to authenticate requests
     between the API and generation server.
   - `GENERATION_MODEL_SERVICE_URL`: Optional. Used to fetch model metadata
     when the client does not send a reference image.
   - `GCS_CREDENTIALS` and `GENERATION_MODEL_BUCKET`: Optional. Needed when the
     worker must download assets directly from Google Cloud Storage.
   - `GENERATION_PROVIDER`: Optional. Set to `google_gemini` to delegate
     generations to Google Gemini instead of the bundled ComfyUI workflow.
   - `GOOGLE_GEMINI_API_KEY`: Required when using the Google provider with the
     Gemini Developer API.
   - `GOOGLE_GEMINI_USE_VERTEX_AI`: Optional. Set to `true` to use Vertex AI
     instead of direct Gemini API key auth. `GOOGLE_GENAI_USE_VERTEXAI` is also
     honored.
   - `GOOGLE_CLOUD_PROJECT`: Required when Vertex AI is enabled.
   - `GOOGLE_CLOUD_LOCATION`: Optional when Vertex AI is enabled. Defaults to
     `global`.
   - `GOOGLE_GEMINI_MODEL` and `GOOGLE_GEMINI_TIMEOUT`: Optional tuning knobs.
2. Install dependencies and start the service:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.dev.txt
uvicorn generation_server.app:app --host 0.0.0.0 --port 8100 --reload
```

3. Point the calling API at this instance through `GENERATION_SERVER_URL`.

## Architecture

- `GenerationQueue` manages an in-memory FIFO queue with configurable
  concurrency.
- `process_generation_job` orchestrates prompt building, asset resolution,
  workflow execution, and callback dispatch.
- Each result triggers a signed `POST` back to the API so the app can surface
  real-time progress.
- `ComfyWorkflowRunner` loads the exported ComfyUI workflow, custom nodes, and
  model weights, and falls back to a stub only when the environment lacks the
  required GPU stack.

## Docker commands

Create the shared network:

```sh
docker network create gemzy-net
```

Build and push using the helper from `services/generation-server`:

```sh
../scripts/deploy-gen.sh
```

Pull and run from GCP Artifact Registry:

```sh
docker pull us-central1-docker.pkg.dev/festive-icon-459009-g3/gemzy-repo/gemzy-generation:latest

docker stop gemzy-generation
docker rm gemzy-generation

docker run -d \
  --env-file ../.env \
  -p 8100:8100 \
  --name gemzy-generation \
  --network gemzy-net \
  us-central1-docker.pkg.dev/festive-icon-459009-g3/gemzy-repo/gemzy-generation:latest

docker run -d \
  --env-file ../.env \
  -p 8100:8100 \
  --restart unless-stopped \
  --name gemzy-generation \
  --network gemzy-net \
  us-central1-docker.pkg.dev/festive-icon-459009-g3/gemzy-repo/gemzy-generation:latest
```

Lifecycle:

```sh
docker logs -f gemzy-generation
docker stop gemzy-generation
docker start gemzy-generation
docker restart gemzy-generation
docker rm gemzy-generation
docker rmi gemzy-generation
docker exec -it gemzy-generation bash
docker ps
docker ps -a
```
