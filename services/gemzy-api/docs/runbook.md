# Gemzy Operations Runbook 📚

## Deployment

1. **Build & Push**: Run the deployment script to build the Docker image and push it to the registry.
   ```bash
   ./scripts/deploy.sh
   ```
2. **Rollout**: The script handles image tagging. Ensure your orchestration service (e.g., DigitalOcean App Platform, Kubernetes, or Portainer) is configured to pull the `latest` tag or listen for webhooks.

## Rollback

If a deployment fails, revert to the previous stable version:

1. **Execute Rollback**:
   ```bash
   ./scripts/rollback.sh
   ```
   *Note: This script requires specific configuration based on your hosting provider.*

## Monitoring & Observability

- **Health Check**:
  - Endpoint: `GET /`
  - Response: `{"status": "ok", "database": "ok"}`
  - Use this for load balancer health probes.

- **Logs**:
  - Logs are output to `stdout`.
  - Set `LOG_FORMAT=json` environment variable for structured JSON logs (recommended for production).

- **Error Tracking**:
  - Errors are reported to **Sentry**. Ensure `SENTRY_DSN` is set.

## load Testing

To test system performance under load:

1. **Install k6**: [Installation Guide](https://k6.io/docs/get-started/installation/)
2. **Run Test**:
   ```bash
   k6 run scripts/load-test.js
   ```
   *Default target: 20 VUs for 1 minute.*
