# homebox-mcp

Read-only [MCP](https://modelcontextprotocol.io) server for [Homebox](https://homebox.software) **v0.26+**
(the entity-merge API: `/api/v1/entities`, `/api/v1/tags`). Homebox is the source of truth:
this server only issues HTTP `GET` requests (plus the login `POST`). It never creates, changes or deletes anything.

Transport: Streamable HTTP at `http://<host>:8031/mcp`.

## Configuration (environment variables)

| Variable | Required | Default |
|---|---|---|
| `HOMEBOX_URL` | no | `http://localhost:7745` |
| `HOMEBOX_EMAIL` | yes | |
| `HOMEBOX_PASSWORD` | yes (use a secret) | |
| `SERVER_HOST` | no | `0.0.0.0` |
| `SERVER_PORT` | no | `8031` |

## Tools (19, all read-only)

| Tool | Homebox endpoint |
|---|---|
| `search_homebox_items(query, include_archived=false)` | `GET /v1/entities?q=` |
| `get_homebox_item_details(item_id)` | `GET /v1/entities/{id}` (includes warranty, purchase, serial, attachments) |
| `get_item_attachments(item_id)` | `GET /v1/entities/{id}` (attachments only; link attachments show their URL) |
| `get_item_by_asset_id(asset_id)` | `GET /v1/assets/{id}` |
| `get_item_location_path(item_id)` | `GET /v1/entities/{id}/path` |
| `get_item_maintenance(item_id, status)` | `GET /v1/entities/{id}/maintenance` |
| `list_recent_items(limit, sort)` | `GET /v1/entities?orderBy=createdAt` or `updatedAt` |
| `list_homebox_locations()` | `GET /v1/entities?isLocation=true` |
| `get_homebox_location_details(location_id)` | `GET /v1/entities/{id}` |
| `get_items_in_location(location_id)` | `GET /v1/entities?parentIds=` |
| `get_location_tree(include_items=false)` | `GET /v1/entities/tree` |
| `list_homebox_labels()` | `GET /v1/tags` |
| `get_homebox_label_details(label_id)` | `GET /v1/tags/{id}` |
| `get_items_with_label(label_id)` | `GET /v1/entities?tags=` |
| `list_custom_fields(field="")` | `GET /v1/entities/fields`, `/v1/entities/fields/values` |
| `find_items_by_custom_field(field, value)` | `GET /v1/entities?fields=name=value` |
| `list_maintenance(status)` | `GET /v1/maintenance` |
| `get_inventory_statistics()` | `GET /v1/currency`, `/v1/groups/statistics`, `/statistics/locations`, `/statistics/tags` |
| `get_purchase_value_over_time(start, end)` | `GET /v1/groups/statistics/purchase-price` |

List outputs are compact summaries to keep local-model context small.

## Linking documents (e.g. Paperless-ngx)

Homebox v0.26 supports URL attachments: on an item's Edit page, drag a document URL onto the
Manuals / Warranty / Receipts drop zone. `get_item_attachments` returns that URL.

## Image

Built by GitHub Actions (`.github/workflows/publish.yml`) and published to
`ghcr.io/<owner>/homebox-mcp` with tags `latest` and `sha-<commit>`.
