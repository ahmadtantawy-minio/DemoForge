# DemoForge Backlog

**Status:** Open items below. Historical entries (pre-2026-04-09 and full sprint text) remain in **`plans/backlog-backup-2026-04-09.md`**.

**Implementation decisions** from recent refactors (instances package, compose generator package, properties panel split) are summarized in **`plans/implementation-decisions.md`**.

When new work is planned, add items below with `- [ ]` and link any specs under `plans/` as needed.

---

## Backlog

- [ ] **DemoPresentation component** — Per-demo **intro** and **outro** slide sequences with hand-drawn slide content (e.g. embedded Excalidraw scenes), stored on the demo instance. Deliver as an **isolated component** (not folded into the React Flow diagram save path or template walkthrough):
  - **Frontend**: dedicated module (e.g. `frontend/src/components/demo-presentation/`) — authoring UI, lazy-loaded editor, fullscreen read-only presenter; integrates with the app shell only via props/callbacks (`demoId`, open/close).
  - **Backend**: dedicated presentation slice on `DemoDefinition` and/or `GET/PUT /api/demos/{id}/presentation` (avoid overloading `PUT /diagram`).
  - **Persistence**: optional YAML-inline scenes vs sidecar JSON per slide (trade size vs diffability); demo export/import must include presentation data.
  - **Out of scope for this component**: extending template metadata walkthrough text; topology/canvas nodes.
