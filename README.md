# DemoForge

Interactive demo orchestration platform for MinIO Field Architects. Design, deploy, and manage Docker-based demo environments from a visual canvas with 27+ pre-built templates covering replication, analytics, AI/ML, lakehouse, event-driven ingestion, and more.

---

## Connectivity Requirements

DemoForge runs **locally** on your laptop. Internet access is only required for the initial setup and periodic updates:

| Operation | Internet required? |
|-----------|-------------------|
| `make fa-setup` (first-time) | Yes — validates FA key, pulls images from GCR |
| `make fa-update` | Yes — pulls latest code + images |
| Template sync (UI) | Yes — syncs from Hub (GCS) |
| License sync | Yes — fetches from Hub (GCS) |
| **Creating / deploying / tearing down demos** | **No — fully offline** |
| **All demo traffic (MinIO, Trino, etc.)** | **No — fully offline** |

Once setup is complete and images are cached, DemoForge can run entirely air-gapped.

---

## Field Architect Setup

### Prerequisites

- **macOS** with [OrbStack](https://orbstack.dev) (recommended) or Docker Desktop — or **Windows** with Docker Desktop / Podman (Compose v2) and **PowerShell** (`demoforge-windows.cmd` falls back to Windows PowerShell 5.1; **`make *-win`** targets call **`pwsh`** if it is on your `PATH`)
- **16GB RAM** minimum (32GB recommended for heavy templates)
- **Docker** running (`docker ps` should work)
- **API key** from your team lead

**Windows (no Bash required):** from the repo root, run `pwsh -File scripts/windows/fa-setup.ps1` (or `powershell -ExecutionPolicy Bypass -File scripts\windows\fa-setup.ps1` if execution policy blocks scripts), then `demoforge-windows.cmd start` (or `make fa-setup-win` / `make start-win` if `make` and `pwsh` are on your `PATH`). Optional: set `DEMO_DOCKER_CLI=podman` when using Podman’s CLI. The `.ps1` files are **ASCII-only** so they parse correctly in **Windows PowerShell 5.1** and **pwsh**. Dev-mode hot reload is not covered by these scripts; use WSL or the existing `demoforge-dev.sh` flow for full dev parity.

### Quick Start

```bash
# 1. Clone
git clone <repo-url> && cd DemoForge

# 2. Connect to Hub — you'll be prompted for your API key only
make fa-setup

# 3. Start
make start

# 4. Open
open http://localhost:3000
```

> **You only need your API key** (provided by your team lead). The Hub URL is already configured.

### What `make fa-setup` does

1. Verifies Docker is running
2. Prompts for your **API key** (one-time, saved to `.env.local`)
3. Verifies Hub gateway connectivity
4. Detects your FA identity (git email → GitHub CLI → prompt)
5. Writes `.env.local` with credentials and FA identity
6. Pulls all custom component images from the registry (pre-built — no local build needed)

After setup, DemoForge automatically syncs templates from the Hub on every start.

### Keeping Up to Date

```bash
make fa-update
```

Pulls the latest scripts, refreshes core images from GCR, and restarts DemoForge. Also self-repairs stale environment configuration. Run this whenever your team lead announces an update.

### Day-to-Day Commands

```bash
make start    # Start DemoForge
make stop     # Stop DemoForge
make restart  # Restart
make logs     # Tail logs
```

> Templates and images can be refreshed from the UI (Templates → Sync).

### Using the UI

1. **Home** — Docker status, cached images, recent demos, quick actions
2. **Templates** — Browse 27+ templates, filter by category/tier, create demos
3. **Designer** — Visual canvas to wire components, configure connections, deploy
4. **Images** — Manage Docker image cache (pull, re-pull, cleanup)
5. **Healthcheck** (sidebar bottom) — Connectivity health check, current vs latest DemoForge version with update available notice

**Workflow:** Templates → Pick a template → Create Demo → Deploy → Double-click nodes to open web UIs

---

## Dev Mode

Dev mode adds FA management, local hub-api, connectivity diagnostics, and hub release tools.

### Prerequisites

Everything in FA mode, plus:

- **Node.js 20+** and **npm**
- **Python 3.11+**
- **gcloud CLI** (for GCP gateway management)

### Setup

```bash
# 1. Clone and install frontend deps
git clone <repo-url> && cd DemoForge
npm install

# 2. Generate a local admin key (writes DEMOFORGE_HUB_API_ADMIN_KEY to .env.local)
make dev-init

# 3. Start the local hub-api on :8000 (in a separate terminal)
make dev-hub-api

# 4. Start DemoForge in dev mode
make dev-start
```

> `DEMOFORGE_MODE=dev` is injected automatically by `demoforge-dev.sh` — do not add it to `.env.local`.

### `dev-start` vs `dev-start-gcp`

| Command | Hub routing | When to use |
|---------|-------------|-------------|
| `make dev-start` | Sets `DEMOFORGE_HUB_LOCAL=1` — backend connects directly to local hub-api on `:8000` | Default dev workflow |
| `make dev-start-gcp` | Routes through GCP Cloud Run gateway | Testing against the real hub |

Both run with `DEMOFORGE_MODE=dev` active.

### What the local hub-api does

The hub-api (FastAPI + SQLite) tracks Field Architects, their permissions, and telemetry events. In dev mode it runs locally on `:8000` and is used directly instead of going through the cloud gateway.

```bash
make dev-hub-api    # Start hub-api with hot-reload on :8000
make dev-init       # Generate DEMOFORGE_HUB_API_ADMIN_KEY → .env.local (idempotent)
```

On first start, the **Healthcheck** page auto-registers your FA identity in the local hub-api. All checks should be green before working in dev mode.

### Healthcheck

The **Healthcheck** page (accessible in all modes, sidebar bottom) runs a full chain trace for every component:

- **Local Hub API** — direct health + DB/admin access (dev mode)
- **Admin Key** — validates admin key against hub-api
- **FA Authentication** — FA API key validated against hub-api

It also shows the current DemoForge version, the hub-latest version, and a banner when an update is available.

In dev mode, all checks route directly to `localhost:8000`.

### FA Management (Dev Only)

The **FA Mgmt** page lets you manage registered Field Architects:

- View stats: total FAs, active FAs, events (7d / 30d)
- Expand any FA to see their permissions and activity feed
- Toggle permissions: Manual Demo Creation, Fork Templates, Publish Templates, Max Concurrent Demos
- Deactivate / Activate an FA
- **Purge** — hard delete (removes all data; FA can be re-registered immediately)

New FAs are provisioned with all permissions **off** by default.

### Simulating an FA

```bash
# Register a simulated FA in the local hub-api
make dev-sim-fa FA=testuser@min.io
# → prints the generated api_key for that FA

# Purge an FA (hard delete — can re-register immediately)
make dev-purge-fa FA=testuser@min.io
```

### Dev Mode Features

- **DEV badge** in the sidebar
- **Readiness** tab — per-template FA-ready validation (mark templates approved for FAs)
- **FA Mgmt** tab — FA management, permissions, telemetry
- **Push to Hub** button in Templates gallery
- Template **Override & Revert** with SHA-256 backup verification
- `make dev-sim-fa` / `make dev-purge-fa` for FA lifecycle testing

### Hot-Reload Development

```bash
make dev-fe         # Vite dev server on :3000 (hot-reload)
make dev-be         # FastAPI with live reload on :9210
make dev-hub-api    # hub-api with live reload on :8000
```

### Hub Release Workflow

`make hub-release` is the full release command. It commits staged changes, tags the version, pushes images and templates, redeploys the hub-api Cloud Run service, and notifies all connected FAs. FAs will see an update available banner on their Healthcheck tab.

```bash
make hub-release                    # Full release: commit, tag, push images+templates, deploy, notify FAs
make hub-release VERSION=v1.0.0     # Explicit version
make hub-release-patch              # Bump patch version (default)
make hub-release-minor              # Bump minor version
make hub-release-major              # Bump major version
make hub-release NO_IMAGES=1        # Skip image push (code-only release)
make hub-release NO_DEPLOY=1        # Skip Cloud Run redeploy
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (localhost:3000)                                       │
│  React 18 + TypeScript + @xyflow/react (canvas) + shadcn/ui    │
└──────────────────────┬──────────────────────────────────────────┘
                       │ REST API
┌──────────────────────▼──────────────────────────────────────────┐
│  Backend (localhost:9210)                                       │
│  FastAPI + Pydantic v2 + Docker SDK                             │
│  Controls Docker via /var/run/docker.sock (Docker-in-Docker)    │
└──────────────────────┬──────────────────────────────────────────┘
                       │ Docker API
┌──────────────────────▼──────────────────────────────────────────┐
│  OrbStack / Docker Desktop                                      │
│  Demo containers: MinIO, Trino, Spark, Kafka, Grafana, etc.    │
│  Isolated networks per demo                                     │
└─────────────────────────────────────────────────────────────────┘
```

| Directory | Purpose |
|-----------|---------|
| `frontend/` | React 18 + Vite 6 + Tailwind + shadcn/ui |
| `backend/` | FastAPI (Python), Docker orchestration engine |
| `hub-api/` | FastAPI + SQLite + Litestream — FA registry and telemetry (dev: local; prod: Cloud Run + GCS) |
| `components/` | 37+ component manifests (image, ports, connections, init scripts) |
| `demo-templates/` | 27 built-in demo templates (YAML) |
| `user-templates/` | Field Architect-saved custom templates |
| `synced-templates/` | Templates synced from Hub (GCS) |
| `scripts/` | Hub management, GCP gateway, FA setup scripts |
| `data/` | Runtime state (template backups, hub-api DB, override manifests) |

## Hub Architecture (GCP)

```
Field Architect Laptop              GCP
┌──────────────┐     HTTPS     ┌────────────────────────────┐
│  DemoForge   │◄─────────────►│  Cloud Run: Gateway (Caddy)│
│  (local)     │               │  API key auth              │
│              │               │                  │          │
│              │               │            HTTPS ▼          │
│              │               │         ┌──────────┐        │
│              │               │         │ Cloud Run│        │
│              │               │         │ hub-api  │        │
│              │               │         │+Litestr. │        │
└──────────────┘               │         └──────────┘        │
                               │               │             │
                               │         GCS bucket          │
                               │      (SQLite replica +      │
                               │       templates + licenses) │
                               └────────────────────────────┘
```

DemoForge connects directly to the Cloud Run gateway using your FA API key. Hub API runs as a Cloud Run service with SQLite replicated to GCS via Litestream. Templates and licenses are stored in GCS.

---

## Hub Management (Dev Only)

### Updating the Hub

#### Publish templates to GCS

Templates are published via the DemoForge UI (publish/promote buttons on the Templates page)
or via the API:
```bash
curl -X POST http://localhost:9210/api/templates/push-all-builtin
```

#### Re-seed licenses
```bash
make seed-licenses
```

#### Redeploy hub-api (code change)
```bash
make hub-deploy-api
```

#### Redeploy gateway (Caddyfile change)
```bash
make hub-deploy-gateway
```

#### Full redeploy (first time or infra change)
```bash
make hub-deploy
```

### All hub commands

```bash
make hub-deploy             # Full GCP deploy: hub-api + gateway Cloud Run + GCS infra
make hub-deploy-gateway     # Rebuild and redeploy gateway Cloud Run only (~1 min)
make hub-deploy-api         # Rebuild and redeploy hub-api Cloud Run only (~2 min)
make hub-update             # Update everything: gateway + images + licenses
make hub-update-gateway     # Rebuild and deploy Cloud Run gateway only
make hub-update-images      # Build and push custom images to GCR only
make hub-status             # Show sync status, Cloud Run health, template counts
make hub-push               # Build and push all custom images
make hub-push-<name>        # Build and push one image (e.g. make hub-push-inference-sim)
make seed-licenses          # Seed license keys to GCS
```

### First-time GCP setup

```bash
make hub-deploy     # Deploy Cloud Run gateway + hub-api + GCS infra
make seed-licenses  # Seed licenses to GCS
# Publish templates via the UI (publish/promote) or: POST /api/templates/push-all-builtin
```

---

## Makefile Reference

### Field Architect

| Command | Description |
|---------|-------------|
| `make fa-setup` | First-time setup: validates FA key with gateway, pulls images |
| `make fa-update` | Pull latest code + images, self-repair env, restart |
| `make start` | Start DemoForge (FA mode) |
| `make stop` | Stop DemoForge |
| `make restart` | Restart DemoForge |
| `make status` | Show running services |
| `make logs` | Tail service logs |
| `make build` | Build images without starting |
| `make clean` | Stop everything, remove volumes |
| `make nuke` | Full clean + remove built images |
| `make check-images` | Show cached vs missing images |
| `make pull-missing` | Pull all missing vendor images |
| `make hub-pull` | Pull custom images from Hub |

### Dev

| Command | Description |
|---------|-------------|
| `make dev-init` | Generate `DEMOFORGE_HUB_API_ADMIN_KEY` → `.env.local` (idempotent) |
| `make dev-hub-api` | Start hub-api locally on `:8000` with hot-reload |
| `make dev-start` | Start DemoForge in dev mode (local hub-api on `:8000`) |
| `make dev-start-gcp` | Start DemoForge in dev mode (GCP hub via gateway) |
| `make dev-stop` | Stop DemoForge (dev mode) |
| `make dev-restart` | Restart DemoForge (dev mode) |
| `make dev-status` | Show running services |
| `make dev-logs` | Tail service logs |
| `make dev-fe` | Frontend dev server with hot-reload |
| `make dev-be` | Backend dev server with hot-reload |
| `make dev-sim-fa FA=user@min.io` | Register a simulated FA in local hub-api |
| `make dev-purge-fa FA=user@min.io` | Hard-delete an FA (can re-register immediately) |
| `make hub-release` | Full release: commit, tag, push images+templates, deploy, notify FAs |
| `make hub-release-patch` | Release with patch version bump |
| `make hub-release-minor` | Release with minor version bump |
| `make hub-release-major` | Release with major version bump |
| `make hub-deploy` | Full GCP deploy: hub-api + gateway Cloud Run + GCS infra |
| `make hub-deploy-gateway` | Rebuild/deploy gateway Cloud Run only (~1 min) |
| `make hub-deploy-api` | Rebuild/deploy hub-api Cloud Run only (~2 min) |
| `make hub-update` | Update GCP hub: gateway + images + licenses |
| `make hub-update-gateway` | Rebuild and redeploy Cloud Run gateway |
| `make hub-update-images` | Push custom images to GCR |
| `make hub-status` | Hub health and sync status |
| `make hub-push` | Build and push all custom images |
| `make seed-licenses` | Seed license keys to GCS |

---

## Cost Estimate (GCP Hub)

| Component | Monthly |
|---|---|
| Cloud Run gateway (1 min instance) | ~$3–5 |
| Cloud Run hub-api (1 min instance) | ~$3–5 |
| GCS bucket (templates + licenses + SQLite replica) | ~$1–2 |
| Egress | ~$1–3 |
| **Total** | **~$8–15** |
