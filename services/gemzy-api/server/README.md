# Gemzy API server

This FastAPI service stores user-generated collection images in Google Cloud
Storage (GCS). The current media-delivery model uses two tiers:

- `GCS_COLLECTIONS_APP_BUCKET` stores private originals.
- `GCS_COLLECTIONS_PUBLIC_BUCKET` stores derived browse/viewer assets such as
  `thumb`, `preview`, and `viewer-full`.

Signed URLs remain part of upload and original-access flows, but normal
collection browsing is intended to resolve against stable public derived URLs.
The steps below describe how to provision the buckets, service account, and
environment variables expected by the API.

## 1. Create a storage bucket

1. Choose or create a Google Cloud project.
2. Create a private storage bucket dedicated to Gemzy collection originals.
   - Enable uniform bucket-level access so IAM policies control access.
   - Pick a region close to your users, for example `us-central1`.
   - Optionally add lifecycle rules to delete soft-deleted objects or move
     older assets to cheaper storage tiers.
3. Create a second public bucket for derived collection assets and avatars.
   - This bucket serves optimized image variants used by browse and viewer
     flows.
   - It can sit behind Cloud CDN or another edge cache.
4. Optionally attach Cloud CDN or another CDN. If you do, provide the hostname
   to the app via `GCS_PUBLIC_HOST`.

## 2. Service account and permissions

1. Create a dedicated service account for uploads and metadata updates.
2. Grant the account these IAM roles on the buckets:
   - `Storage Object Creator` for signed-upload writes.
   - `Storage Object Viewer` for metadata finalization.
   - `Storage Object Admin` if the backend should patch cache headers or
     metadata after upload and publish derived assets.
3. Create a JSON key for the service account and provide its contents to the
   server through `GCS_CREDENTIALS`.
4. If the backend signs URLs through IAM SignBlob instead of a JSON key, set
   `GCS_SIGNING_SERVICE_ACCOUNT` to the service account email that should sign
   upload or original-read URLs.

## 3. Environment variables

Add these variables to the API environment, for example in `../.env`:

| Variable                        | Required | Description |
| ------------------------------- | -------- | ----------- |
| `GCS_CREDENTIALS`               | Yes      | JSON for the service account created above. When omitted the backend tries default credentials from the environment. |
| `GCS_SIGNING_SERVICE_ACCOUNT`   | Optional | Service account email used for GCS signed URL generation when the runtime credentials are not themselves a service account. |
| `GCS_COLLECTIONS_APP_BUCKET`    | Yes      | Private bucket that stores user collection images, for example `app.gemzy.co`. |
| `GCS_COLLECTIONS_PUBLIC_BUCKET` | Yes      | Public bucket used for derived collection variants, avatars, and model artwork, for example `public.gemzy.co`. |
| `GCS_AVATARS_BUCKET`            | Optional | Dedicated bucket for profile avatars. Falls back to `GCS_COLLECTIONS_PUBLIC_BUCKET` when omitted. |
| `GCS_PUBLIC_HOST`               | Optional | Fully qualified host used to serve collection images. If not set, the backend falls back to `https://storage.googleapis.com/<bucket>/...`. |
| `GCS_AVATARS_PUBLIC_HOST`       | Optional | Public host used for avatar URLs. Defaults to `GCS_PUBLIC_HOST` when not provided. |
| `GCS_UPLOAD_URL_TTL`            | Optional | Signed upload URL lifetime in seconds. Default `900`. |
| `GCS_VIEW_URL_TTL`              | Optional | Signed original-read URL lifetime in seconds for edit/download/share-source flows. Default `900`. |
| `GCS_UPLOAD_MAX_BYTES`          | Optional | Maximum allowed collection upload size in bytes. Default `26214400` (25 MB). |
| `GCS_AVATARS_MAX_BYTES`         | Optional | Maximum allowed avatar upload size in bytes. Default `2097152` (2 MB). |
| `GCS_COLLECTIONS_CACHE_CONTROL` | Optional | Cache-Control header applied when the backend finalizes collection uploads. |
| `GCS_COLLECTIONS_THUMB_MAX_DIMENSION` | Optional | Maximum pixel dimension for public `thumb` variants. Default `512`. |
| `GCS_COLLECTIONS_PREVIEW_MAX_DIMENSION` | Optional | Maximum pixel dimension for public `preview` variants. Default `1600`. |
| `GCS_COLLECTIONS_VIEWER_FULL_MAX_DIMENSION` | Optional | Maximum pixel dimension for public `viewer-full` variants. Default `2560`. |
| `GCS_AVATARS_CACHE_CONTROL`     | Optional | Cache-Control header applied to uploaded avatars. |
| `GCS_OWNER_METADATA_KEY`        | Optional | Metadata key that should mirror the owning Gemzy user ID. Defaults to `appUserId`. |
| `USER_DELETION_GRACE_DAYS`      | Optional | Number of days to wait before permanently deleting a user after a delete request. Default `30`. |
| `USER_DELETION_TABLE`           | Optional | Supabase table name that stores scheduled user deletions. Default `user_deletion_queue`. |
| `USER_DELETION_POLL_SECONDS`    | Optional | How often the API should drain the deletion queue. Set `0` to disable the in-process worker. Default `3600`. |
| `COLLECTIONS_VARIANT_BACKFILL_POLL_SECONDS` | Optional | How often the API should run a small in-process batch to create missing public collection variants for older assets. Leave unset or `0` to disable. |
| `COLLECTIONS_VARIANT_BACKFILL_BATCH_SIZE` | Optional | Number of collection items to inspect per backfill iteration. Default `25`. |

Users who trigger the delete-account flow are enqueued in
`user_deletion_queue` for a grace period. When the API starts it schedules a
background task that calls `server.user_admin.process_due_user_deletions()` on
the configured interval to permanently remove the auth user, profile rows, and
any GCS assets once `scheduled_for` has passed. Deployments that prefer an
external cron can set `USER_DELETION_POLL_SECONDS=0` and run the helper from
their own scheduler instead.

The optional migration `../sql/010_add_user_deletion_cancelled_at.sql` adds a
`cancelled_at` timestamp to the queue. The server still marks returning users
as `status="cancelled"` when that column is missing, so older schemas remain
compatible.

The mobile app already reads signed upload details and streams files directly
to GCS, so the FastAPI server never proxies image bytes. After each collection
create or update, the backend stamps object metadata with the authenticated
Gemzy user ID so ownership is tracked separately from any Google identity.
During finalization, the backend also generates public derived variants in the
public bucket for standard browse/viewer traffic. Profile avatars follow the
same pattern through `/auth/avatar`.

## 4. Delivery model

Gemzy collection reads now split into two categories:

- Browse/view traffic uses derived public assets from
  `GCS_COLLECTIONS_PUBLIC_BUCKET`.
- Edit/download/share-source traffic requests a short-lived signed URL for the
  private original in `GCS_COLLECTIONS_APP_BUCKET`.

This keeps originals private while removing signed-read generation from the
normal collection browsing path.

## 5. Variant backfill for older assets

Older `collection_items` rows may still point at originals that never had
public variants generated. To backfill them gradually without a one-shot
migration, set `COLLECTIONS_VARIANT_BACKFILL_POLL_SECONDS` to a positive value.
On each interval the API will inspect a small batch and generate missing public
variants only for items that still need them.

This worker is intentionally best-effort and low-throughput so it can run in
the app process without disturbing request latency. If you prefer an external
job, leave the setting unset and call the same helper from a dedicated worker
or cron-style runner.

## 6. Optional signed delivery URLs

If you want public asset URLs to resolve through a CDN or edge hostname, set
`GCS_PUBLIC_HOST`. For the private originals bucket, the recommended pattern is
still short-lived signed access on demand rather than public delivery URLs.

## 7. Testing locally

1. Export the environment variables above before starting the API with
   `uvicorn server.main:app --reload`.
2. Use the mobile app to upload a collection. The backend should:
   - Issue a signed `PUT` upload URL under `gs://<bucket>/<appUserId>/...`.
   - Finalize metadata on the object with both `appUserId` and
     `GCS_OWNER_METADATA_KEY` when configured.
   - Generate `thumb`, `preview`, and `viewer-full` assets in the public
     bucket.
   - Persist the canonical original storage path, metadata, and ownership in
     Supabase.
3. Verify the uploaded original remains private in the app bucket and the
   derived assets are reachable through the chosen public host.

## Supabase schema expectations

The API persists collection metadata in Supabase. Each row in
`collection_items` now stores the owning Gemzy profile ID in `user_id` in
addition to the parent `collection_id`. Existing databases should run the
migrations in `../sql`. `004_add_collection_item_user.sql` backfills the column
and aligns constraints so writes succeed once the mobile app sends the new
payloads.

Profile avatars, notification preferences, and administrator flags are
persisted directly on the `profiles` table. Run
`../sql/006_add_profile_preferences.sql` followed by
`../sql/007_add_plan_settings_and_admin_flag.sql` to add the new columns, seed
avatar and notification defaults, and expose `is_admin` on each profile.

Prompt engine administration and the server-driven generation UI catalog rely
on the prompt registry tables. Existing databases should run
`../sql/018_add_prompt_registry.sql` before using `/prompt-engines` or
`/generations/ui-config`.

The prompt-admin dashboard client talks to this FastAPI service directly with a
Supabase bearer token. For local development that means:

- Run the dashboard frontend separately from this API service.
- Point `VITE_GEMZY_API_URL` in `gemzy-dashboard` at this service, typically
  `http://localhost:8000`.
- Set `CORS_ORIGINS` here to include the dashboard origin, typically
  `http://localhost:5173`.

Monthly credit allocations are configured through `plan_settings`. By default
the migration seeds the Free, Starter, Pro, and Designer plans with 40, 120,
600, and 1400 credits respectively. Update those rows to change allocations
without deploying new code; the FastAPI process caches the values for a few
minutes and will pick up changes automatically.

Collections currently only surface metadata stored directly on the
`collections` and `collection_items` tables. Older schemas included auxiliary
`members` tables for avatar stacks, but those structures have been removed in
favor of simpler per-user ownership records.

## Docker commands

Create the shared network if you want the API and generation service to talk
locally by container name:

```sh
docker network create gemzy-net
```

Build from `services/gemzy-api/server`:

```sh
docker build -t gemzy-server -f ../Dockerfile ../..
```

Run detached:

```sh
docker run -d \
  --env-file ../.env \
  -p 5050:5050 \
  --name gemzy-server \
  --network gemzy-net \
  gemzy-server
```

Run with auto-restart:

```sh
docker run -d \
  --env-file ../.env \
  -p 5050:5050 \
  --restart unless-stopped \
  --name gemzy-server \
  --network gemzy-net \
  gemzy-server
```

Logs:

```sh
docker logs -f gemzy-server
```

Lifecycle:

```sh
docker stop gemzy-server
docker start gemzy-server
docker restart gemzy-server
docker rm gemzy-server
docker rmi gemzy-server
docker exec -it gemzy-server bash
docker ps
docker ps -a
```
