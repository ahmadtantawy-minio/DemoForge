# DemoForge

Interactive demo orchestration platform for MinIO Field Architects. Design, deploy, and manage Docker-based demo environments from a visual canvas with 26+ pre-built templates covering replication, analytics, AI/ML, lakehouse, and more.

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

**Key components:**

| Directory | Purpose |
|-----------|---------|
| `frontend/` | React 18 + Vite 6 + Tailwind + shadcn/ui |
| `backend/` | FastAPI (Python), Docker orchestration engine |
| `components/` | 25+ component manifests (image, ports, connections, init scripts) |
| `demo-templates/` | 26 built-in demo templates (YAML) |
| `user-templates/` | Field Architect-saved custom templates |
| `synced-templates/` | Templates synced from Hub (remote MinIO) |
| `scripts/` | Hub management, GCP gateway, FA setup scripts |
| `data/` | Runtime state (template backups, override manifests) |

## Hub Architecture (GCP Gateway)

For team deployments, DemoForge uses a centralized Hub running on GCP:

```
Field Architect Laptop              GCP
┌──────────────┐     HTTPS     ┌───────────────────┐
│  DemoForge   │◄─────────────►│  Cloud Run        │
│  (local)     │               │  Gateway (Caddy)  │
│              │               │  API key auth     │
│  hub-        │               │       │            │
│  connector   │               │       ▼ VPC        │
│  (Caddy)     │               │  ┌────────────┐   │
│              │               │  │ GCE VM     │   │
│  localhost:  │               │  │ MinIO      │   │
│  9000 (S3)   │               │  │ Registry   │   │
│  5000 (Reg)  │               │  │ (private)  │   │
│  9001 (UI)   │               │  └────────────┘   │
└──────────────┘               └───────────────────┘
```

The hub-connector runs as a local Docker container that proxies `localhost:9000/5000/9001` through the Cloud Run gateway (with API key injection) to the private VM. Field Architects get the same ports as if MinIO were running locally.

---

## Field Architect Mode

### Prerequisites

- **macOS** with [OrbStack](https://orbstack.dev) (recommended) or Docker Desktop
- **16GB RAM** minimum (32GB recommended for heavy templates)
- **Docker** running and accessible (`docker ps` should work)
- **Hub URL + API key** from your team lead (for template sync and custom images)

### Quick Start

```bash
# 1. Clone the repo
git clone <repo-url> && cd DemoForge

# 2. Run Field Architect setup (connects to Hub, pulls images)
make fa-setup

# 3. Start DemoForge
make start

# 4. Open the UI
open http://localhost:3000
```

### What `make fa-setup` Does

1. Verifies Docker is running
2. Starts the **hub-connector** container (auto-restarts on reboot)
3. Verifies Hub gateway connectivity
4. Writes `.env.local` with sync credentials
5. Pulls all custom component images from the private registry

After setup, DemoForge automatically syncs templates from the Hub on every start.

### Day-to-Day Usage

```bash
make start          # Start DemoForge (frontend + backend)
make stop           # Stop DemoForge
make restart        # Restart DemoForge
make status         # Show running services
make logs           # Tail logs

make check-images   # Check which Docker images are cached vs missing
make pull-missing   # Pull all missing vendor images
make hub-pull       # Pull custom images from Hub registry
```

### Using the UI

1. **Home page** — Docker status, cached images, recent demos, quick actions
2. **Templates** — Browse 26+ templates, filter by category/tier, create demos
3. **Designer** — Visual canvas to wire components, configure connections, deploy
4. **Images** — Manage Docker image cache (pull, re-pull, cleanup dangling)

**Workflow:** Templates > Pick a template > Create Demo > Deploy > Double-click nodes to open web UIs

### Trust the Private Registry (One-time)

If Docker pull fails with TLS errors:

```bash
make hub-trust      # Configures Docker to trust the Hub registry
```

---

## Dev Mode

### Prerequisites

Everything from Field Architect mode, plus:

- **Node.js 20+** and **npm**
- **Python 3.11+** (for backend development)
- **gcloud CLI** (for GCP gateway management)
- **Playwright** (for template validation): `npx playwright install`

### Setup

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd DemoForge
npm install                           # Frontend deps (for Playwright tests)

# 2. Start with Docker Compose (full stack)
make start

# 3. Or run frontend/backend separately for hot-reload
make dev-fe         # Vite dev server on :3000
make dev-be         # FastAPI with live reload on :9210
```

### Dev Environment Variables

Create `.env.local` in the project root for Hub connectivity:

```bash
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=http://localhost:9000
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=<from-hub-setup>
DEMOFORGE_REGISTRY_HOST=localhost:5000
```

Or run `make se-setup` to generate this automatically.

### Hub Management (Dev Only)

```bash
make hub-setup      # First-time: create bucket, IAM, registry, seed templates
make hub-seed       # Re-seed templates to Hub after local changes
make hub-status     # Show sync status, registry health, template counts
make hub-push       # Build all custom images and push to Hub registry
make hub-push-<name>  # Build and push one image (e.g., make hub-push-inference-sim)
```

### GCP Gateway Management

```bash
make gateway        # Deploy/update Cloud Run gateway + VPC
make gateway-test   # Run integration tests (simulates FA experience)
make update-myip    # Update firewall with your current IP
```

**First-time gateway setup:**

```bash
# 1. Deploy the VM (if not already running)
scripts/minio-gcp.sh

# 2. Activate AIStor license
scripts/minio-gcp.sh --activate

# 3. Deploy the gateway stack (VPC + Cloud Run + hub-connector image)
scripts/minio-gcp.sh --gateway

# 4. Test the gateway locally
make gateway-test
```

The `--gateway` mode:
- Creates a VPC with private subnet
- Migrates the VM off the public network (preserves all data)
- Sets up firewall rules (VPC connector + your dev IP + IAP SSH)
- Builds and deploys a Caddy-based Cloud Run gateway (HTTPS + API key auth)
- Builds the hub-connector image for Field Architects
- Generates `.env.hub` with all connection details

### Template Override & Backup

Dev mode enables template override with automatic backup:

1. Create a demo from any template
2. Modify it in the designer
3. **Save as Template > Override Existing** — the original is backed up
4. Templates with overrides show an amber "Customized" badge
5. In dev mode, you can **Revert** to the original

Backups are stored in `data/template-backups/` with SHA-256 hash verification.

### Template Validation

Run automated validation of all templates:

```bash
python3 tests/validate-templates-fast.py    # API-based validation
npx playwright test                          # Browser-based validation
```

### Project Structure (Dev Reference)

```
DemoForge/
├── frontend/src/
│   ├── App.tsx                    # Main app, page routing, polling
│   ├── api/client.ts              # API client (apiFetch, all endpoints)
│   ├── stores/
│   │   ├── demoStore.ts           # Demos, navigation, page state
│   │   └── diagramStore.ts        # React Flow nodes/edges, connections
│   ├── components/
│   │   ├── canvas/                # DiagramCanvas, nodes, edges, picker
│   │   ├── templates/             # TemplateGallery, SaveAsTemplateDialog
│   │   ├── toolbar/               # Toolbar (deploy, stop, save, settings)
│   │   └── nav/                   # AppNav (left sidebar)
│   └── pages/                     # HomePage, ImagesPage, TemplatesPage
├── backend/app/
│   ├── api/                       # FastAPI routers (demos, templates, images, deploy)
│   ├── engine/                    # Docker manager, template sync/backup
│   ├── models/                    # Pydantic models
│   └── registry/                  # Component manifest loader
├── components/*/manifest.yaml     # Component definitions
├── demo-templates/*.yaml          # Built-in templates
├── scripts/
│   ├── minio-gcp.sh              # GCP VM + gateway management
│   ├── hub-setup.sh              # Hub first-time setup
│   ├── hub-push.sh               # Push images to registry
│   ├── hub-pull.sh               # Pull images from registry
│   ├── local-hub-test.sh         # Gateway integration test
│   └── fa-setup.sh               # Field Architect onboarding script
└── docker-compose.yml             # DemoForge itself (backend + frontend)
```

### Cost Estimate (GCP Hub)

| Component | Monthly |
|---|---|
| VM (e2-medium, private) | ~$25 |
| Cloud Run (1 min instance) | ~$5-8 |
| VPC connector (2 instances) | ~$7 |
| Data disk (50GB) | ~$5 |
| Egress | ~$1-3 |
| **Total** | **~$43-48** |

---

## Makefile Reference

| Command | Description |
|---------|-------------|
| `make start` | Build and start DemoForge |
| `make stop` | Stop DemoForge |
| `make restart` | Restart DemoForge |
| `make status` | Show running services |
| `make logs` | Tail service logs |
| `make build` | Build images without starting |
| `make clean` | Stop everything, remove volumes |
| `make nuke` | Full clean + remove built images |
| `make dev-fe` | Frontend dev server (hot-reload) |
| `make dev-be` | Backend dev server (hot-reload) |
| `make check-images` | Show cached vs missing images |
| `make pull-missing` | Pull all missing vendor images |
| `make hub-setup` | First-time Hub setup |
| `make hub-seed` | Re-seed templates to Hub |
| `make hub-status` | Hub health and sync status |
| `make hub-push` | Build and push all custom images |
| `make hub-pull` | Pull custom images from Hub |
| `make hub-trust` | Trust the private registry |
| `make gateway` | Deploy Cloud Run gateway |
| `make gateway-test` | Test gateway connectivity |
| `make fa-setup` | Field Architect first-time setup |
| `make update-myip` | Update firewall with current IP |
