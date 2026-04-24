#!/bin/bash
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

docker stop gemzy-server
docker rm -f gemzy-server

docker pull us-central1-docker.pkg.dev/festive-icon-459009-g3/gemzy-repo/gemzy-server:dev

docker run -d \
  --env-file "$SERVICE_DIR/.env" \
  -p 5050:5050 \
  --restart unless-stopped \
  --name gemzy-server \
  -v "/c/Users/Royosef/AppData/Roaming/gcloud/application_default_credentials.json:/tmp/adc.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS= \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json \
  -e GOOGLE_CLOUD_QUOTA_PROJECT=festive-icon-459009-g3 \
  us-central1-docker.pkg.dev/festive-icon-459009-g3/gemzy-repo/gemzy-server:dev

docker logs gemzy-server -f
