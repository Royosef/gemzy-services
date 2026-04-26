# Prompt Engine Admin Design

## Goal

Create a future web admin client for managing prompt engines without code deploys.

The admin should let an internal operator:

- browse prompt engines by task type
- inspect version history
- create a draft from scratch or from an existing version
- edit prompt definitions and input schemas
- preview rendered output against sample input
- publish a version
- manage task routing rules

## Authentication

The dashboard authenticates as a real Supabase user who has `is_admin = true` in the `profiles` table. There are no API keys or service-role tokens — the web client goes through the same auth flow the mobile app uses.

### Login flow (magic link)

1. `POST /auth/send` with `{ "email": "<admin email>" }` — sends an OTP code.
2. `POST /auth/verify` with `{ "email": "...", "token": "<code>" }` — returns:

```json
{
  "token": { "access": "<JWT>", "refresh": "<refresh_token>" },
  "user": { "id": "...", "isAdmin": true, ... },
  "is_new": false
}
```

Alternatively, `POST /auth/oauth` with a Google-linked admin account works the same way.

### Token lifecycle

- Attach the access token to every request: `Authorization: Bearer <access_token>`.
- When the access token expires, call `POST /auth/refresh` with `{ "refresh": "<refresh_token>" }` to get a new token pair.
- The dashboard should handle refresh transparently (e.g. via an Axios/fetch interceptor).

### Access control

Every admin endpoint calls `_ensure_admin`, which checks `UserState.isAdmin`. The `is_admin` flag is set manually in the `profiles` table in Supabase — there is no self-service way to become admin.

| Caller | Result |
|--------|--------|
| Unauthenticated | `401 Unauthorized` |
| Registered user (`isAdmin: false`) | `403 Forbidden` |
| Admin user (`isAdmin: true`) | Allowed |

## Backend Contract

### Core resources

- `prompt_engines`
  - stable identity and metadata
  - `slug`, `name`, `description`, `taskType`, `rendererKey`
  - `inputSchema`, `outputSchema`, `labels`
  - `publishedVersionId`, `publishedVersionNumber`

- `prompt_engine_versions`
  - immutable published history
  - editable only while `status = draft`
  - stores `definition`, `sampleInput`, `changeNote`
  - status values: `draft`, `published`, `archived`

- `prompt_task_routes`
  - runtime selection rules
  - ordered by `priority`
  - match request payloads using JSON path rules
  - can pin a specific version or follow the engine's published version
  - has `slug`, `notes`, and links back to its engine via `engineId` / `engineSlug`

### Engine ref resolution

All endpoints using `{engineRef}` accept **either** a UUID (`id`) **or** a `slug`. The backend tries an `id` lookup first, then falls back to `slug`.

### Admin endpoints

- `GET    /prompt-engines`
- `POST   /prompt-engines`
- `GET    /prompt-engines/{engineRef}`
- `PATCH  /prompt-engines/{engineRef}`
- `POST   /prompt-engines/{engineRef}/versions`
- `PATCH  /prompt-engines/{engineRef}/versions/{versionId}`
- `POST   /prompt-engines/{engineRef}/versions/{versionId}/publish`
- `POST   /prompt-engines/{engineRef}/versions/{versionId}/preview`
- `GET    /prompt-engines/routes`
- `POST   /prompt-engines/routes`
- `PATCH  /prompt-engines/routes/{routeId}`
- `DELETE /prompt-engines/routes/{routeId}`

### Error handling

All errors are returned as JSON with a `detail` string:

```json
{ "detail": "Prompt engine not found" }
```

Common status codes:

| Code | Meaning |
|------|---------|
| `400` | Validation error (e.g. editing a non-draft version, preview render failure) |
| `403` | Non-admin user |
| `404` | Engine, version, or route not found |
| `409` | Slug already exists (engine or route) |
| `500` | Internal creation failure |

---

## Request / Response Schemas

### Prompt Engine

#### `GET /prompt-engines` → `PromptEngineResponse[]`

Returns a flat list (no version bodies). Versions are batch-fetched to resolve `publishedVersionNumber`.

```ts
interface PromptEngineResponse {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  taskType: string;
  rendererKey: string;
  inputSchema: Record<string, any>;   // default {}
  outputSchema: Record<string, any>;  // default {}
  labels: Record<string, any>;        // default {}
  publishedVersionId: string | null;
  publishedVersionNumber: number | null;
  createdAt: string | null;
  updatedAt: string | null;
}
```

#### `GET /prompt-engines/{engineRef}` → `PromptEngineDetailResponse`

Same as above, plus all versions for this engine:

```ts
interface PromptEngineDetailResponse extends PromptEngineResponse {
  versions: PromptEngineVersionResponse[];  // ordered by versionNumber desc
}
```

#### `POST /prompt-engines` → `PromptEngineDetailResponse` (201)

```ts
interface CreatePromptEnginePayload {
  slug: string;
  name: string;
  description?: string | null;
  taskType: string;
  rendererKey: string;
  inputSchema?: Record<string, any>;
  outputSchema?: Record<string, any>;
  labels?: Record<string, any>;
  initialVersion?: {               // optional — seeds version 1 as draft
    changeNote?: string | null;
    definition?: Record<string, any>;
    sampleInput?: Record<string, any>;
  } | null;
}
```

- Slug must be unique → `409` if taken.
- An initial draft version (v1) is always created (uses `initialVersion` fields if provided, otherwise empty).

#### `PATCH /prompt-engines/{engineRef}` → `PromptEngineDetailResponse`

```ts
interface UpdatePromptEnginePayload {
  slug?: string | null;
  name?: string | null;
  description?: string | null;
  taskType?: string | null;
  rendererKey?: string | null;
  inputSchema?: Record<string, any> | null;
  outputSchema?: Record<string, any> | null;
  labels?: Record<string, any> | null;
  publishedVersionId?: string | null;   // manually set published version
}
```

- Only non-null fields are applied.
- Slug uniqueness is enforced → `409` if another engine already uses it.
- Setting `publishedVersionId` validates the version belongs to this engine.

---

### Prompt Engine Versions

#### Version response shape

```ts
interface PromptEngineVersionResponse {
  id: string;
  engineId: string;
  versionNumber: number;
  status: "draft" | "published" | "archived";
  changeNote: string | null;
  definition: Record<string, any>;   // default {}
  sampleInput: Record<string, any>;  // default {}
  createdAt: string | null;
}
```

#### `POST /prompt-engines/{engineRef}/versions` → `PromptEngineVersionResponse` (201)

```ts
interface CreatePromptEngineVersionPayload {
  changeNote?: string | null;
  definition?: Record<string, any>;
  sampleInput?: Record<string, any>;
}
```

- `versionNumber` is auto-assigned (max existing + 1).
- Always created with `status = "draft"`.

#### `PATCH /prompt-engines/{engineRef}/versions/{versionId}` → `PromptEngineVersionResponse`

```ts
interface UpdatePromptEngineVersionPayload {
  changeNote?: string | null;
  definition?: Record<string, any> | null;
  sampleInput?: Record<string, any> | null;
}
```

- Only `draft` versions can be edited → `400` if version is `published` or `archived`.

#### `POST /prompt-engines/{engineRef}/versions/{versionId}/publish` → `PromptEngineDetailResponse`

No request body.

Side effects:
1. All currently `published` versions for this engine are set to `archived`.
2. The target version's status is set to `published`.
3. The engine's `publishedVersionId` is updated to point to this version.

#### `POST /prompt-engines/{engineRef}/versions/{versionId}/preview` → `PromptEnginePreviewResponse`

```ts
interface PromptEnginePreviewPayload {
  input?: Record<string, any>;   // default {}
}

interface PromptEnginePreviewResponse {
  output: Record<string, any>;   // rendered result — shape depends on rendererKey
}
```

- Calls `render_engine_version(engine, version, input)` from the prompting package.
- Returns `400` if rendering fails, with the error message in `detail`.

---

### Prompt Task Routes

#### `GET /prompt-engines/routes` → `PromptTaskRouteResponse[]`

Ordered by `task_type` then `priority`. Each route is enriched with its `engineSlug`.

```ts
interface PromptTaskRouteResponse {
  id: string;
  slug: string;
  name: string;
  taskType: string;
  priority: number;         // default 100, lower = higher priority
  isActive: boolean;        // default true
  matchRules: Record<string, any>;  // JSON path match rules
  engineId: string;
  engineSlug: string | null;
  pinnedVersionId: string | null;
  notes: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}
```

#### `POST /prompt-engines/routes` → `PromptTaskRouteResponse` (201)

```ts
interface CreatePromptTaskRoutePayload {
  slug: string;
  name: string;
  taskType: string;
  priority?: number;                    // default 100
  isActive?: boolean;                   // default true
  matchRules?: Record<string, any>;
  engineId: string;                     // required — must reference an existing engine
  pinnedVersionId?: string | null;      // if set, must belong to the referenced engine
  notes?: string | null;
}
```

- Slug must be unique → `409` if taken.
- `engineId` and `pinnedVersionId` are validated against existing records.

#### `PATCH /prompt-engines/routes/{routeId}` → `PromptTaskRouteResponse`

```ts
interface UpdatePromptTaskRoutePayload {
  slug?: string | null;
  name?: string | null;
  taskType?: string | null;
  priority?: number | null;
  isActive?: boolean | null;
  matchRules?: Record<string, any> | null;
  engineId?: string | null;
  pinnedVersionId?: string | null;
  notes?: string | null;
}
```

- Slug uniqueness is enforced if changed → `409`.
- If `engineId` changes, `pinnedVersionId` is validated against the new engine.

#### `DELETE /prompt-engines/routes/{routeId}` → `204 No Content`

**Soft-delete**: sets `is_active = false` rather than removing the row.

---

## Suggested IA

### 1. Engines index

Table columns:

- name
- slug
- task type
- renderer
- published version (number)
- updated at

Primary actions:

- `New engine`
- task type filter
- renderer filter
- search by slug/name

### 2. Engine detail

Top area:

- engine metadata card (name, slug, description, task type, renderer)
- publish target badge
- quick actions: `New draft`, `Edit metadata`

Tabs:

- `Versions`
- `Routes`
- `Schema`

### 3. Version editor

Three-column layout works best.

Left:

- version selector
- status chip (`draft` / `published` / `archived`)
- change note

Center:

- definition editor
- JSON editor first, with room for custom form builders later per renderer

Right:

- sample input editor
- live preview panel
- validation / render errors

Actions:

- `Save draft` (only for draft versions)
- `Preview`
- `Publish` (triggers archival of previous published version)
- `Duplicate as new draft`

### 4. Route manager

Route table columns:

- route name
- slug
- task type
- priority
- active
- engine (slug)
- pinned version
- notes

Inline actions:

- enable / disable (toggle `isActive`)
- reorder priority
- edit match rules
- soft-delete (sets inactive, returns 204)

## UX Notes

- Draft editing must autosave or at least warn on unsaved JSON changes.
- Publishing should show a diff summary: definition changed, schema changed, routes affected.
- Publishing archives all previously published versions for the engine — the UI should communicate this clearly.
- Preview should support pasting raw JSON input and optionally loading the version's `sampleInput`.
- Route changes should show "first match wins" clearly in the UI (lower priority number = higher precedence).
- Published and archived versions should be read-only — show a clear "read-only" indicator and disable save.
- Slug fields should validate uniqueness on blur or before submit and show the 409 error inline.

## Renderer-Aware UI

For the first admin release, keep the editor generic and JSON-first.

Later, add specialized editors by `rendererKey`:

- `on_model_sections_v1`
- `pure_jewelry_sections_v1`
- `planner_enrich_v1`
- `planner_rank_v1`

That lets the first release ship quickly while leaving a path to richer domain-aware editing.

## Recommended Frontend Stack

- React + TanStack Query
- Monaco or CodeMirror for JSON editing
- Zod for client-side payload validation
- diff viewer for version compare

## MVP Build Order

1. Engines index + detail fetch
2. Draft creation/editing
3. Preview panel
4. Publish flow
5. Route manager
6. Version diff view

## API Discovery

The backend is built with FastAPI and auto-generates an OpenAPI spec. When the server is running you can access:

- **Swagger UI**: `GET /docs`
- **OpenAPI JSON**: `GET /openapi.json`

These are the canonical source of truth for types and can be used to auto-generate TypeScript clients.
