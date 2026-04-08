# DemoForge

Interactive demo orchestration platform for MinIO Field Architects. Design, deploy, and manage Docker-based demo environments from a visual canvas with 27+ pre-built templates covering replication, analytics, AI/ML, lakehouse, event-driven ingestion, and more.

---

## Field Architect Setup

### Prerequisites

- **macOS** with [OrbStack](https://orbstack.dev) (recommended) or Docker Desktop
- **16GB RAM** minimum (32GB recommended for heavy templates)
- **Docker** running (`docker ps` should work)
- **API key** from your team lead

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
3. Starts the **hub-connector** container (Caddy reverse proxy, auto-restarts on reboot)
4. Verifies Hub gateway connectivity
5. Detects your FA identity (git email → GitHub CLI → prompt)
6. Writes `.env.local` with credentials and FA identity
7. Pulls all custom component images from the registry (pre-built — no local build needed)

After setup, DemoForge automatically syncs templates from the Hub on every start.

### Keeping Up to Date

```bash
make fa-update
```

Runs `git pull --ff-only`, refreshes the hub-connector, and restarts DemoForge. Run this whenever your team lead announces an update.

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
5. **Healthcheck** (sidebar bottom) — Connectivity health check, hub-connector status, current vs latest DemoForge version with update available notice

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
| `make dev-start-gcp` | No `DEMOFORGE_HUB_LOCAL=1` — routes through GCP hub-connector on `:8080` | Testing against the real hub |

Both run with `DEMOFORGE_MODE=dev` active.

### What the local hub-api does

The hub-api (FastAPI + SQLite) tracks Field Architects, their permissions, and telemetry events. In dev mode it runs locally on `:8000` and is used directly instead of going through the hub connector.

```bash
make dev-hub-api    # Start hub-api with hot-reload on :8000
make dev-init       # Generate DEMOFORGE_HUB_API_ADMIN_KEY → .env.local (idempotent)
```

On first start, the **Healthcheck** page auto-registers your FA identity in the local hub-api. All checks should be green before working in dev mode.

### Healthcheck

The **Healthcheck** page (accessible in all modes, sidebar bottom) runs a full chain trace for every component:

- **Local Hub API** — direct health + DB/admin access (dev mode)
- **Admin Key** — validates admin key against hub-api
- **Hub Connector** — connector → gateway → hub-api route (skipped if local hub-api is healthy)
- **FA Authentication** — FA API key validated against hub-api

It also shows the current DemoForge version, the hub-latest version, and a banner when an update is available.

In dev mode, all checks route directly to `localhost:8000` bypassing the connector.

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
| `synced-templates/` | Templates synced from Hub (remote MinIO) |
| `scripts/` | Hub management, GCP gateway, FA setup scripts |
| `data/` | Runtime state (template backups, hub-api DB, override manifests) |

## Hub Architecture (GCP)

```
Field Architect Laptop              GCP
┌──────────────┐     HTTPS     ┌────────────────────────────┐
│  DemoForge   │◄─────────────►│  Cloud Run: Gateway (Caddy)│
│  (local)     │               │  API key auth              │
│              │               │       │            │        │
│  hub-        │               │  VPC  ▼     HTTPS  ▼       │
│  connector   │               │  ┌─────────┐ ┌──────────┐  │
│  (Caddy)     │               │  │  GCE VM │ │ Cloud Run│  │
│  :8080       │               │  │  MinIO  │ │ hub-api  │  │
│              │               │  │  +Reg.  │ │+Litestr. │  │
│  localhost:  │               │  └─────────┘ └──────────┘  │
│  9000 (S3)   │               │                  │          │
│  5000 (Reg)  │               │            GCS bucket       │
│  9001 (UI)   │               │         (SQLite replica)    │
└──────────────┘               └────────────────────────────┘
```

The hub-connector (local Docker container) proxies `localhost:9000/5000/9001` through the Cloud Run gateway to the private VM. FAs get the same ports as if MinIO were running locally. Hub API runs as a separate Cloud Run service with SQLite replicated to GCS via Litestream.

---

## Hub Management (Dev Only)

```bash
make hub-setup              # First-time: bucket + IAM + registry + seed templates
make hub-deploy             # Full GCP deploy: VPC + gateway + hub-api Cloud Run + Litestream infra
make hub-deploy-gateway     # Rebuild and redeploy gateway Cloud Run only (~1 min)
make hub-deploy-api         # Rebuild and redeploy hub-api Cloud Run only (~2 min)
make hub-update             # Update everything: gateway + templates + images + licenses
make hub-update-gateway     # Rebuild and deploy Cloud Run gateway only
make hub-update-templates   # Seed built-in templates to MinIO hub only
make hub-update-images      # Build and push custom images to registry only
make hub-update-licenses    # Seed license keys to MinIO bucket only
make hub-seed               # Re-seed templates after local changes
make hub-status             # Show sync status, registry health, template counts
make hub-push               # Build and push all custom images
make hub-push-<name>        # Build and push one image (e.g. make hub-push-inference-sim)
make seed-licenses          # Seed licenses from data/licenses.yaml
```

### First-time GCP setup

```bash
scripts/minio-gcp.sh            # Deploy the VM
scripts/minio-gcp.sh --activate # Activate AIStor license
make hub-deploy                  # Deploy VPC + Cloud Run gateway + hub-api + Litestream
make gateway-test                # Integration test (simulates FA experience)
make update-myip                 # Update firewall with your current IP
```

---

## Makefile Reference

### Field Architect

| Command | Description |
|---------|-------------|
| `make fa-setup` | First-time setup: connector + Hub connectivity + pull images |
| `make fa-update` | Pull latest code, refresh hub-connector, restart |
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
| `make hub-trust` | Trust the private registry (one-time) |

### Dev

| Command | Description |
|---------|-------------|
| `make dev-init` | Generate `DEMOFORGE_HUB_API_ADMIN_KEY` → `.env.local` (idempotent) |
| `make dev-hub-api` | Start hub-api locally on `:8000` with hot-reload |
| `make dev-start` | Start DemoForge in dev mode (local hub-api on `:8000`) |
| `make dev-start-gcp` | Start DemoForge in dev mode (GCP hub via connector) |
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
| `make hub-deploy` | Full GCP deploy: VPC + gateway + hub-api Cloud Run + Litestream |
| `make hub-deploy-gateway` | Rebuild/deploy gateway Cloud Run only (~1 min) |
| `make hub-deploy-api` | Rebuild/deploy hub-api Cloud Run only (~2 min) |
| `make hub-update` | Update GCP hub: gateway + templates + images + licenses |
| `make hub-update-gateway` | Rebuild and redeploy Cloud Run gateway |
| `make hub-update-templates` | Seed templates to MinIO |
| `make hub-update-images` | Push custom images to registry |
| `make hub-setup` | First-time Hub setup |
| `make hub-seed` | Re-seed templates to Hub |
| `make hub-status` | Hub health and sync status |
| `make hub-push` | Build and push all custom images |
| `make seed-licenses` | Seed licenses from data/licenses.yaml |
| `make gateway-test` | Test gateway connectivity |
| `make update-myip` | Update firewall with current IP |

---

## Cost Estimate (GCP Hub)

| Component | Monthly |
|---|---|
| VM (e2-medium, private) | ~$25 |
| Cloud Run gateway (1 min instance) | ~$3–5 |
| Cloud Run hub-api (1 min instance) | ~$3–5 |
| VPC connector (2 instances) | ~$7 |
| Data disk (50GB) | ~$5 |
| Egress | ~$1–3 |
| **Total** | **~$43–48** |
