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

## Backend Contract

### Core resources

- `prompt_engines`
  - stable identity and metadata
  - `slug`, `name`, `taskType`, `rendererKey`
  - `inputSchema`, `outputSchema`, `labels`
  - `publishedVersionId`

- `prompt_engine_versions`
  - immutable published history
  - editable only while `status = draft`
  - stores `definition`, `sampleInput`, `changeNote`

- `prompt_task_routes`
  - runtime selection rules
  - ordered by `priority`
  - match request payloads using JSON path rules
  - can pin a specific version or follow the engine's published version

### Admin endpoints

- `GET /prompt-engines`
- `POST /prompt-engines`
- `GET /prompt-engines/{engineRef}`
- `PATCH /prompt-engines/{engineRef}`
- `POST /prompt-engines/{engineRef}/versions`
- `PATCH /prompt-engines/{engineRef}/versions/{versionId}`
- `POST /prompt-engines/{engineRef}/versions/{versionId}/publish`
- `POST /prompt-engines/{engineRef}/versions/{versionId}/preview`
- `GET /prompt-engines/routes`
- `POST /prompt-engines/routes`
- `PATCH /prompt-engines/routes/{routeId}`
- `DELETE /prompt-engines/routes/{routeId}`

## Suggested IA

### 1. Engines index

Table columns:

- name
- slug
- task type
- renderer
- published version
- updated at

Primary actions:

- `New engine`
- task type filter
- renderer filter
- search by slug/name

### 2. Engine detail

Top area:

- engine metadata card
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
- status chip
- change note

Center:

- definition editor
- JSON editor first, with room for custom form builders later per renderer

Right:

- sample input editor
- live preview panel
- validation / render errors

Actions:

- `Save draft`
- `Preview`
- `Publish`
- `Duplicate as new draft`

### 4. Route manager

Route table columns:

- route name
- task type
- priority
- active
- engine
- pinned version

Inline actions:

- enable / disable
- reorder priority
- edit match rules

## UX Notes

- Draft editing must autosave or at least warn on unsaved JSON changes.
- Publishing should show a diff summary: definition changed, schema changed, routes affected.
- Preview should support pasting raw JSON input and optionally loading the version's `sampleInput`.
- Route changes should show "first match wins" clearly in the UI.
- Published versions should be read-only.

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
