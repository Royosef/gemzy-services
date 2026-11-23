#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_DIR/../.." && pwd)"

ENV=${1:-dev}

if [ "$ENV" != "prod" ] && [ "$ENV" != "dev" ]; then
  echo "Error: Environment must be 'prod' or 'dev'"
  exit 1
fi

PROJECT_ID="festive-icon-459009-g3"
REGION="us-central1"
REPO_NAME="gemzy-repo"
IMAGE_NAME="gemzy-generation"
REGISTRY_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME"
TAG=$(git -C "$REPO_ROOT" rev-parse --short HEAD)

echo "Configuring Docker for GCP..."
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

echo "Deploying $IMAGE_NAME:$TAG to $REGISTRY_URL for environment: $ENV..."

echo "Build..."
docker build -t "$REGISTRY_URL/$IMAGE_NAME:$TAG" -f "$SERVICE_DIR/Dockerfile" "$REPO_ROOT"

echo "Push..."
docker push "$REGISTRY_URL/$IMAGE_NAME:$TAG"

if [ "$ENV" == "prod" ]; then
  # Keep the image being replaced as :prev so a rollback is one re-tag:
  #   gcloud artifacts docker tags add "$REGISTRY_URL/$IMAGE_NAME:prev" "$REGISTRY_URL/$IMAGE_NAME:latest"
  # Registry-side (no pull). Skipped when there is no :latest yet or it already is this build.
  LATEST_DIGEST=$(gcloud artifacts docker images describe "$REGISTRY_URL/$IMAGE_NAME:latest" --format='value(image_summary.digest)' 2>/dev/null || true)
  NEW_DIGEST=$(gcloud artifacts docker images describe "$REGISTRY_URL/$IMAGE_NAME:$TAG" --format='value(image_summary.digest)')
  if [ -n "$LATEST_DIGEST" ] && [ "$LATEST_DIGEST" != "$NEW_DIGEST" ]; then
    echo "Tagging current latest ($LATEST_DIGEST) as prev..."
    gcloud artifacts docker tags add "$REGISTRY_URL/$IMAGE_NAME@$LATEST_DIGEST" "$REGISTRY_URL/$IMAGE_NAME:prev" --quiet
  else
    echo "No previous latest to keep (or it is this build); leaving :prev unchanged."
  fi

  echo "Tagging as latest for prod deployment..."
  docker tag "$REGISTRY_URL/$IMAGE_NAME:$TAG" "$REGISTRY_URL/$IMAGE_NAME:latest"
  docker push "$REGISTRY_URL/$IMAGE_NAME:latest"
else
  echo "Tagging as dev for dev deployment..."
  docker tag "$REGISTRY_URL/$IMAGE_NAME:$TAG" "$REGISTRY_URL/$IMAGE_NAME:dev"
  docker push "$REGISTRY_URL/$IMAGE_NAME:dev"
fi

echo "Build & Push Complete. Verify deployment in your cloud provider."
