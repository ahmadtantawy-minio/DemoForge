# DemoForge Backlog

> Archive of pre-2026-04-09 items: `plans/backlog-backup-2026-04-09.md`

---

## In Progress

- [x] **Proper Health Reporting in Cockpit**: When a cluster is not deployed or unreachable, the Health tab shows "0/0 online" and "0 B / 0 B" instead of a meaningful state.
  - When demo is `not_deployed` or `stopped`: show "Not deployed" / "Stopped" placeholder
  - When `mc admin info` fetch fails or times out: show "Unreachable" with error reason
  - Backend `cluster_health` endpoint returns structured `{status, drives_online, drives_total, capacity_used, capacity_total, error}`
  - Frontend renders state-appropriate UI: `healthy | degraded | unreachable | stopped | not_deployed`

---

## Parked (future phases)

- **Phase 6.5 — Metabase BI Layer**: Metabase component, init script, BI templates (see backup)
- **Phase 7 — Cloud Provider Integration**: AWS S3 / Azure Blob / GCS as ILM tier destinations, credential store (see backup)
- **Phase 8 — Delta Sharing**: AIStor Delta Sharing integration + demo template (see backup)
- **Phase 9 — AI/ML Pipeline**: Ollama, Qdrant, RAG app, connection types, AI demo template (see backup)
- **Template System**: Template Detail View, persistence, seeded templates, metadata schema (see backup)
- **Analytics pipeline bugs**: Metabase timing, AIStor warehouse, SigV4 passthrough, etc. (see backup)
- **Phase 5 — Experience & Sharing**: Export/import, snapshots, walkthrough engine (see backup)
- **Remaining Fixes**: FIX-2 (mc replicate add AIStore syntax), FIX-7 (--sync/--bandwidth AIStore mc) (see backup)
- **Medium Priority**: S3 File Browser Enhancement, Data Generator Web Console, Configuration Panel Rework (see backup)
- **UX / Polish**: Bucket Policy UX, verbose deploy output, DemoManager sorting, keyboard shortcuts, dynamic page title, inline node naming, hide minimap, log filtering (see backup)
