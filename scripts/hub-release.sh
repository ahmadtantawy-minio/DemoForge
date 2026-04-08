#!/usr/bin/env bash
# hub-release.sh — Full DemoForge release: commit → tag → push → images → templates → deploy → notify
#
# Usage:
#   scripts/hub-release.sh                     # auto-bump patch (v0.5.0 → v0.5.1)
#   scripts/hub-release.sh --version v1.0.0    # explicit version
#   scripts/hub-release.sh --minor             # bump minor (v0.5.0 → v0.6.0)
#   scripts/hub-release.sh --major             # bump major (v0.5.0 → v1.0.0)
#   scripts/hub-release.sh --no-images         # skip image build+push (code-only release)
#   scripts/hub-release.sh --no-deploy         # skip Cloud Run redeploy
#   scripts/hub-release.sh --no-templates      # skip template seed
#   VERSION=v1.0.0 scripts/hub-release.sh      # version via env var
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()     { echo -e "${GREEN}▶${NC} $*"; }
ok()      { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
fail()    { echo -e "${RED}✗${NC} $*" >&2; exit 1; }
section() { echo -e "\n${CYAN}${BOLD}── $* ──────────────────────────────────────────${NC}"; }

cd "$PROJECT_ROOT"

# ── Parse flags ────────────────────────────────────────────────────────────
BUMP_TYPE="patch"
EXPLICIT_VERSION="${VERSION:-}"
SKIP_IMAGES=0
SKIP_DEPLOY=0
SKIP_TEMPLATES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)   EXPLICIT_VERSION="$2"; shift 2 ;;
    --version=*) EXPLICIT_VERSION="${1#*=}"; shift ;;
    --major)     BUMP_TYPE="major"; shift ;;
    --minor)     BUMP_TYPE="minor"; shift ;;
    --patch)     BUMP_TYPE="patch"; shift ;;
    --no-images)    SKIP_IMAGES=1; shift ;;
    --no-deploy)    SKIP_DEPLOY=1; shift ;;
    --no-templates) SKIP_TEMPLATES=1; shift ;;
    *) fail "Unknown flag: $1. See script header for usage." ;;
  esac
done

# ── Pre-flight ─────────────────────────────────────────────────────────────
section "Pre-flight"

command -v git >/dev/null || fail "git not found"
command -v docker >/dev/null || fail "docker not found"

# Local dev hub-api admin key (for local hub-api on :8000)
LOCAL_ADMIN_KEY=$(grep "^DEMOFORGE_HUB_API_ADMIN_KEY=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- | head -1 || echo "")
# GCP hub: gateway URL + admin key from .env.hub (first entry = GCP hub-api key)
GCP_HUB_URL=$(grep "^DEMOFORGE_HUB_URL=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2- | head -1 || echo "")
GCP_ADMIN_KEY=$(grep "^DEMOFORGE_HUB_API_ADMIN_KEY=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2- | head -1 || echo "")

[[ -z "$LOCAL_ADMIN_KEY" && -z "$GCP_ADMIN_KEY" ]] && fail "No DEMOFORGE_HUB_API_ADMIN_KEY found in .env.local or .env.hub — run 'make dev-init' or 'make fa-setup' first."

# Use whichever key is available for the pre-flight summary
ADMIN_KEY="${LOCAL_ADMIN_KEY:-$GCP_ADMIN_KEY}"

# Verify we're in a git repo with remotes
git remote get-url origin &>/dev/null || fail "No 'origin' remote configured."

# Check for untracked/unstaged changes (warn, don't block)
UNSTAGED=$(git status --porcelain 2>/dev/null | grep -c "^.[^ ]" || true)
STAGED=$(git status --porcelain 2>/dev/null | grep -c "^[MADRCU]" || true)
UNTRACKED=$(git status --porcelain 2>/dev/null | grep -c "^??" || true)

ok "Git repo OK"

# ── Determine version ──────────────────────────────────────────────────────
section "Version"

LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
ok "Last release: ${LAST_TAG}"

if [[ -n "$EXPLICIT_VERSION" ]]; then
  NEW_VERSION="$EXPLICIT_VERSION"
  [[ "$NEW_VERSION" != v* ]] && NEW_VERSION="v${NEW_VERSION}"
else
  # Parse semver from last tag
  _ver="${LAST_TAG#v}"
  MAJOR="${_ver%%.*}"; _rest="${_ver#*.}"
  MINOR="${_rest%%.*}"; PATCH="${_rest#*.}"; PATCH="${PATCH%%[-+]*}"

  case "$BUMP_TYPE" in
    major) NEW_VERSION="v$((MAJOR+1)).0.0" ;;
    minor) NEW_VERSION="v${MAJOR}.$((MINOR+1)).0" ;;
    patch) NEW_VERSION="v${MAJOR}.${MINOR}.$((PATCH+1))" ;;
  esac
fi

# Check tag doesn't already exist
if git tag | grep -qx "$NEW_VERSION"; then
  fail "Tag $NEW_VERSION already exists. Use --version to specify a different one."
fi

ok "New version:  ${NEW_VERSION}"

# ── Show release plan ──────────────────────────────────────────────────────
section "Release plan"

echo ""
echo -e "  ${BOLD}${NEW_VERSION}${NC}  (from ${LAST_TAG})"
echo ""
echo -e "  Steps:"
echo -e "    1. Commit any staged changes"
echo -e "    2. Create and push git tag ${NEW_VERSION}"
[[ $SKIP_IMAGES    -eq 0 ]] && echo -e "    3. Build + push custom images to GCR" || echo -e "    3. ${YELLOW}skip${NC} image push (--no-images)"
[[ $SKIP_TEMPLATES -eq 0 ]] && echo -e "    4. Seed templates to hub MinIO" || echo -e "    4. ${YELLOW}skip${NC} template seed (--no-templates)"
[[ $SKIP_DEPLOY    -eq 0 ]] && echo -e "    5. Redeploy hub-api Cloud Run" || echo -e "    5. ${YELLOW}skip${NC} Cloud Run redeploy (--no-deploy)"
echo -e "    6. Notify hub-api → all FAs see update banner"
echo ""

if [[ $STAGED -gt 0 ]]; then
  echo -e "  ${CYAN}Staged changes (will be committed):${NC}"
  git status --short | grep "^[MADRCU]" | sed 's/^/    /'
  echo ""
fi
if [[ $UNSTAGED -gt 0 ]]; then
  warn "Unstaged changes will NOT be included in this release:"
  git status --short | grep "^.[^ ]" | sed 's/^/    /'
  echo ""
fi
if [[ $UNTRACKED -gt 0 ]]; then
  echo -e "  ${YELLOW}Untracked files (ignored):${NC}"
  git status --short | grep "^??" | head -5 | sed 's/^/    /'
  echo ""
fi

read -rp "  Proceed with release ${NEW_VERSION}? [y/N] " CONFIRM
[[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && fail "Aborted."

# ── Step 1: Commit staged changes ─────────────────────────────────────────
section "Step 1/6 — Commit"

if [[ $STAGED -gt 0 ]]; then
  log "Committing staged changes..."
  git commit -m "release: ${NEW_VERSION}"
  ok "Committed release: ${NEW_VERSION}"
else
  ok "Nothing staged to commit"
fi

# ── Step 2: Tag + push ─────────────────────────────────────────────────────
section "Step 2/6 — Tag + push"

log "Creating tag ${NEW_VERSION}..."
git tag -a "${NEW_VERSION}" -m "Release ${NEW_VERSION}"
ok "Tagged ${NEW_VERSION}"

log "Pushing commits + tag to origin..."
git push origin HEAD
git push origin "${NEW_VERSION}"
ok "Pushed to origin"

# ── Step 3: Build + push images ───────────────────────────────────────────
if [[ $SKIP_IMAGES -eq 0 ]]; then
  section "Step 3/6 — Images"
  log "Building and pushing custom images to GCR..."
  "$SCRIPT_DIR/hub-push.sh" || warn "Some images failed to push — check output above"
  ok "Images pushed"
else
  section "Step 3/6 — Images (skipped)"
fi

# ── Step 4: Seed templates ────────────────────────────────────────────────
if [[ $SKIP_TEMPLATES -eq 0 ]]; then
  section "Step 4/6 — Templates"
  log "Seeding templates to hub MinIO..."
  "$SCRIPT_DIR/hub-seed.sh" || warn "Template seed failed — check output above"
  ok "Templates seeded"
else
  section "Step 4/6 — Templates (skipped)"
fi

# ── Step 5: Redeploy hub-api ──────────────────────────────────────────────
if [[ $SKIP_DEPLOY -eq 0 ]]; then
  section "Step 5/6 — Deploy hub-api"
  if [[ -f "$PROJECT_ROOT/scripts/minio-gcp.sh" ]]; then
    log "Redeploying hub-api Cloud Run..."
    "$PROJECT_ROOT/scripts/minio-gcp.sh" --deploy-api || warn "Cloud Run redeploy failed — FAs may not see the new version endpoint yet"
    ok "hub-api redeployed"
  else
    warn "minio-gcp.sh not found — skipping Cloud Run redeploy"
  fi
else
  section "Step 5/6 — Deploy hub-api (skipped)"
fi

# ── Step 6: Notify hub-api ────────────────────────────────────────────────
section "Step 6/6 — Notify hub"

RELEASED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NOTIFIED=0

_notify_hub() {
  local url="$1" key="$2" label="$3"
  local RESP
  RESP=$(curl -sf -X POST "${url}/api/hub/admin/set-latest-version" \
    -H "Content-Type: application/json" \
    -H "X-Hub-Admin-Key: ${key}" \
    -d "{\"demoforge\": \"${NEW_VERSION}\", \"released_at\": \"${RELEASED_AT}\"}" \
    --connect-timeout 5 2>/dev/null || echo "")
  if echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok')" 2>/dev/null; then
    ok "Hub notified via ${label} — FAs will see update banner for versions older than ${NEW_VERSION}"
    return 0
  fi
  return 1
}

# 1. GCP gateway (preferred — direct to deployed hub-api)
if [[ -n "$GCP_HUB_URL" && -n "$GCP_ADMIN_KEY" ]]; then
  if _notify_hub "$GCP_HUB_URL" "$GCP_ADMIN_KEY" "GCP gateway"; then
    NOTIFIED=1
  else
    warn "GCP gateway notification failed (${GCP_HUB_URL})"
  fi
fi

# 2. Local hub-api (fallback for dev-start mode)
if [[ $NOTIFIED -eq 0 && -n "$LOCAL_ADMIN_KEY" ]]; then
  for URL in "http://localhost:8000" "http://host.docker.internal:8000"; do
    if _notify_hub "$URL" "$LOCAL_ADMIN_KEY" "local hub-api ($URL)"; then
      NOTIFIED=1
      break
    fi
  done
fi

if [[ $NOTIFIED -eq 0 ]]; then
  warn "Could not notify hub-api."
  warn "FAs won't see the update banner until you run:"
  [[ -n "$GCP_HUB_URL" && -n "$GCP_ADMIN_KEY" ]] && \
    warn "  curl -X POST ${GCP_HUB_URL}/api/hub/admin/set-latest-version -H 'X-Api-Key: ${GCP_ADMIN_KEY}' -d '{\"demoforge\": \"${NEW_VERSION}\"}'"
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  Released ${NEW_VERSION}$(printf '%*s' $((48 - ${#NEW_VERSION})) '')║${NC}"
echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}${BOLD}║  Tag:     ${NEW_VERSION} (pushed to origin)$(printf '%*s' $((31 - ${#NEW_VERSION})) '')║${NC}"
[[ $SKIP_IMAGES    -eq 0 ]] && echo -e "${GREEN}${BOLD}║  Images:  pushed to GCR                                  ║${NC}"
[[ $SKIP_TEMPLATES -eq 0 ]] && echo -e "${GREEN}${BOLD}║  Templates: seeded to hub MinIO                          ║${NC}"
[[ $NOTIFIED       -eq 1 ]] && echo -e "${GREEN}${BOLD}║  FAs:     update banner active                           ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  FAs update with: ${CYAN}make fa-update${NC}"
echo ""
