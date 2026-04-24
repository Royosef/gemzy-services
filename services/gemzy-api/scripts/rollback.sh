#!/bin/bash
# Gemzy Rollback Script
set -e

# Configuration
IMAGE_NAME="gemzy-server"
REGISTRY_URL="${REGISTRY_URL:-registry.digitalocean.com/gemzy}"

if [ -z "$1" ]; then
    echo "Usage: ./scripts/rollback.sh <TAG_TO_RESTORE>"
    echo "Example: ./scripts/rollback.sh a1b2c3d"
    exit 1
fi

TARGET_TAG=$1

echo "⏪ Rolling back 'latest' to tag: $TARGET_TAG..."

# Pull the specific tag (to ensure we have it locally, though retagging remote would be better if possible without pull)
# Docker doesn't support remote retag directly without manifest manipulation.
# Simplest way: Pull -> Tag -> Push

echo "Pulling $REGISTRY_URL/$IMAGE_NAME:$TARGET_TAG..."
docker pull $REGISTRY_URL/$IMAGE_NAME:$TARGET_TAG

echo "Retagging as latest..."
docker tag $REGISTRY_URL/$IMAGE_NAME:$TARGET_TAG $REGISTRY_URL/$IMAGE_NAME:latest

echo "Pushing latest..."
docker push $REGISTRY_URL/$IMAGE_NAME:latest

echo "✅ Rollback complete. 'latest' now points to $TARGET_TAG."
echo "You may need to restart your service to pick up the change."
