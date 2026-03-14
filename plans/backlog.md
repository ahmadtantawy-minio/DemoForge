# DemoForge Backlog

Items to be reviewed and incorporated during each build phase when relevant.

---

## Completed

- [x] Consider using the frontend designer skill to identify a nice looking UI library, while maintaining the same functionality — **Done: shadcn/ui with zinc dark theme, all 13 components migrated**
- [x] In the demo designer, download and use the official logo of each component being used — makes it more indicative — **Done: SVG icons for MinIO, NGINX, Prometheus, Grafana in ComponentIcon.tsx**
- [x] Easy way to remove connectors (edges) once created — **Done: Backspace key deletion + hover X button on edges**
- [x] Docker lifecycle management — per-demo locks, timeouts, force-remove fallback, non-blocking stop, background state reconciliation
- [x] Deploy progress panel — 7 real-time steps via polling
- [x] UI/UX overhaul — demo manager modal, welcome screen, sidebar collapse, toast notifications, theme toggle, shadcn primitives
- [x] Terminal PTY support — interactive shell with echo via `script` wrapper
- [x] Web console proxy — X-Frame-Options stripped, base tag injection, WebSocket proxy for MinIO console
- [x] DemoForge branding — favicon, header logo (#C72C48)

## Upcoming: License Sprint (insert between Pre-Phase bugs and Phase 3)

> **Goal**: Global license/config injection for enterprise components (MinIO AIStore, Grafana Enterprise, etc.)
> **Consolidates**: backlog "MinIO AIStore", Phase 4 item 4.7, license management item

### Decisions Needed Before Implementation
- [ ] **Validate MinIO AIStore license mechanism** — confirm it accepts `MINIO_SUBNET_LICENSE` env var (vs file mount)
- [ ] **AIStore as separate component vs variant** — separate `components/minio-aistore/` (recommended) or variant of existing MinIO
- [ ] **Settings API namespace** — use `/api/settings/licenses` (shared with future Phase 5 settings page) in a single `settings.py` router
- [ ] **License store location** — `data/licenses.yaml` (mounted volume, persists across rebuilds)

### License Sprint Tasks (sequential)
- [ ] **L1**: Add `LicenseRequirement` model to `component.py` (license_id, injection_type, env_var/mount_path, required) — 30 min
- [ ] **L2**: Create `LicenseStore` with YAML persistence at `data/licenses.yaml` — 1-2 hrs
- [ ] **L3**: Create settings API router `/api/settings/licenses` (CRUD, masked values in GET) — 1-2 hrs
- [ ] **L4**: Modify compose generator to inject licenses after secret defaults, before node.config overrides — 1 hr
- [ ] **L5**: Deploy-time validation — block deploy if required license missing (HTTP 400 with clear message) — 30 min
- [ ] **L6**: Rename MinIO CE + create MinIO AIStore manifest with `license_requirements` — 30 min
- [ ] **L7**: Frontend: License settings UI (embeddable section, not standalone page — Phase 5 settings page will wrap it) — 2-3 hrs
- [ ] **L8**: Frontend: Palette warnings for components with unmet license requirements — 1 hr

### Conflict Notes
- **L3 creates `backend/app/api/settings.py`** — Phase 5 item 5.8 (Settings Page) must extend this file, not replace it
- **L6 consolidates** backlog "MinIO AIStore" item + Phase 4 item 4.7 — remove duplicates
- **L7 should be an embeddable component** so Phase 5 settings page can incorporate it
- **L8 depends on toast system** (already done via sonner)
- **Phase 4 new components** (KES, mc-client, traffic-gen) must include `license_requirements` fields if applicable

## Remaining Backlog

- [ ] Add verbose output panel (collapsed by default) to deploy, start & stop modals — show raw Docker/compose output for debugging
- [ ] License management for components — track and display license info per component (Apache 2.0, MIT, AGPL, etc.), show in manifests and UI
- [ ] DemoManager container/image tables need sorting and filtering
- [ ] Keyboard shortcuts (Cmd+N new demo, Cmd+D deploy, Escape deselect)
- [ ] Edge connection type selector (currently all default to "data")
- [ ] Dynamic page title with active demo name
- [ ] Hide React Flow minimap when canvas is empty

## Phase 3 Additions (from UI/UX review)
> These should be folded into Phase 3 Stream 2 (Frontend) alongside existing items

- [ ] Replace TerminalPanel raw tab buttons with shadcn Tabs
- [ ] Make ComponentCard quick actions clickable (currently static spans)
- [ ] Add drag affordance (grip icon) to palette items
- [ ] Log filtering by level in Debug panel
- [ ] Debug error counter should cap/reset when panel is open
