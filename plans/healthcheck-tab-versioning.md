# Plan: Healthcheck Tab + Version Tracking

**Status: IMPLEMENTED**

## Goal

1. Rename the "Network" nav tab → **"Healthcheck"** — update all label references.
2. Track the **DemoForge app version** — when a dev pushes updates to the hub, all FAs immediately see if they're on the latest version or not.
3. Add a **Versions section** to the Healthcheck page showing:
   - DemoForge current vs latest (from hub) — prominent banner
   - Each component's local image tag vs hub-recommended tag — table

---

## Version Source: Git Tags

DemoForge is git-deployed. The version is `git describe --tags --always` — no separate VERSION file.

- `v0.5.0` — on a release tag
- `v0.5.0-3-gabcdef` — 3 commits ahead of the tag
- `v0.5.0-dirty` — uncommitted changes

Backend reads it at startup via subprocess, exposed at `GET /api/version`.

---

## Version Increment Workflow

```
Developer makes changes, commits to main
         ↓
git tag v0.5.1 && git push origin v0.5.1
         ↓
Developer runs: make hub-release
  (or: scripts/hub-release.sh)
         ↓
hub-release.sh reads git describe → "v0.5.1"
POSTs to hub-api: POST /api/hub/admin/set-latest-version
  { "demoforge": "v0.5.1", "released_at": "..." }
         ↓
All FAs' Healthcheck pages immediately show:
  🟡 Update available: v0.5.1
     Running v0.5.0 → v0.5.1 available — run make fa-update
         ↓
FA runs: make fa-update
  → git pull --ff-only   (new step added to fa-update.sh)
  → docker pull connector image
  → demoforge.sh restart
         ↓
Healthcheck shows: ✅ Up to date (v0.5.1)
```

The version check is **always `ok: true, optional: true`** — never degrades overall Healthcheck status. Outdated = amber warning only, never red failure.

---

## Component Version Tracking

- `component-readiness.yaml` gains an optional `image_tag` per component (hub-admin sets when a new version is validated)
- Local tag: read from component manifest `image` field
- When both are `latest` → status = "floating" (expected, not a problem)
- When hub_tag is pinned and local differs → amber "update" indicator

```yaml
# component-readiness.yaml (hub-controlled, synced to FAs)
components:
  minio:
    fa_ready: true
    image_tag: "minio/minio:RELEASE.2025-01-20T14-49-07Z"  # ← hub admin sets this
  grafana:
    fa_ready: true
    # no image_tag → hub hasn't pinned this one → shows "—"
```

---

## Hub-api Contract (implement in hub-api repo)

```
GET  /api/hub/version/latest
  → { "demoforge": { "version": "v0.5.1", "released_at": "2026-04-08" } }
  → Connector passes through transparently (existing pattern)
  → No extra auth needed beyond connector key

POST /api/hub/admin/set-latest-version   (admin-key protected)
  body: { "demoforge": "v0.5.1", "released_at": "2026-04-08T..." }
  → { "ok": true }
```

DemoForge-side degrades gracefully when these endpoints don't exist yet (`skipped: true`, no error shown).

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/api/version.py` | **NEW** — `GET /api/version`, reads `git describe` |
| `backend/app/main.py` | Register `version_router` |
| `backend/app/api/connectivity.py` | Add `_read_local_version()`, `_check_version()`, extend `_check_components()` with `component_versions`, wire both into `check_connectivity()` |
| `frontend/src/components/nav/AppNav.tsx` | Label: `"Network"` → `"Healthcheck"` |
| `frontend/src/pages/ConnectivityPage.tsx` | h1 rename, VersionBanner, ComponentVersions table, extended interfaces |
| `frontend/src/components/templates/TemplateGallery.tsx` | `"Network tab"` → `"Healthcheck tab"` |
| `scripts/fa-update.sh` | Add `git pull --ff-only` step before bootstrap |
| `scripts/hub-release.sh` | **NEW** — dev release script: git describe → POST to hub-api |
