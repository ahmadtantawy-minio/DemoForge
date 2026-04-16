# Parallel workstreams — Sprints 5–7

Three tracks run in parallel after backlog scope (Sprints 1–4) was parked. Dependencies are called out per track.

| Track | Sprint | Owner focus | Depends on |
|-------|--------|-------------|------------|
| **A — Architecture** | 5 | Design-only: Add Pool impact | None |
| **B — Pool lifecycle** | 6 | Decommission/commission persistence, Cockpit, runtime Add Pool | Track A doc **approved** before **Add Pool** implementation |
| **C — Webhooks** | 7 | Bucket webhook edge + receiver service + UI | None (isolated); MinIO `notify_webhook` compose wiring is **slice 2** |

## Track A — Sprint 5 (doc)

- **Deliverable:** `plans/architect-add-pool.md` (this repo).
- **Exit:** Review/approval so Sprint 6 “Add Pool” can start implementation.

## Track B — Sprint 6 (code)

- **Already in codebase:** Pool decommission HTTP API (`instances.py`), canvas UX (`ClusterNode`, `AddPoolButton` for **design-time** pool rows), `mc admin decommission` wiring.
- **Remaining (typical gaps vs backlog):**
  - Persist per-pool decommission state in saved demo/backend state (survive refresh), not only React + one-shot poll.
  - Cockpit: per-pool badges aligned with backlog wording (`idle | decommissioning | decommissioned`).
  - **Add Pool at runtime:** blocked until Track A; requires compose expansion + state model from architect doc.

## Track C — Sprint 7 (code)

### Slice 1 (this iteration)

- New component `webhook-receiver` (manifest, image, in-memory ring buffer, HTTP UI).
- MinIO manifest: `bucket-webhook` connection type + edge `bucket_name` in properties (via `config_schema`).
- Frontend: `connectionMeta`, optional palette label mapping for `integrations`, edge label from `bucket_name`.

### Slice 2 (follow-up)

- `compose_generator` / init: `mc` (or admin API) `notify_webhook` for the configured bucket → receiver URL.
- Instances panel deep-link uses existing `web_ui` pattern.
- `fa_ready` and hub image push when stable.

## Sync points

1. **Before merging Add Pool (S6):** Architect doc approved (Track A).
2. **Webhook slice 2:** Coordinate with pool networking so receiver DNS name is stable in generated compose.
