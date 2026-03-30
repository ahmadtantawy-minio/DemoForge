#!/usr/bin/env bash
set -euo pipefail

REGISTRY_HOST="${1:-34.18.90.197:5000}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}Configure Docker to trust insecure registry: ${REGISTRY_HOST}${NC}\n"

if command -v orb &>/dev/null; then
    ORBSTACK_CONFIG="${HOME}/.orbstack/config/docker.json"
    echo -e "${GREEN}Detected: OrbStack${NC}"
    echo -e "  Config: ${CYAN}${ORBSTACK_CONFIG}${NC}\n"
    read -rp "Add ${REGISTRY_HOST} to insecure-registries? (y/N) " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        # Merge with existing config to avoid overwriting other settings
        mkdir -p "$(dirname "${ORBSTACK_CONFIG}")"
        python3 -c "
import json, os
config_path = '${ORBSTACK_CONFIG}'
cfg = {}
if os.path.exists(config_path):
    with open(config_path) as f:
        content = f.read().strip()
        if content:
            cfg = json.loads(content)
regs = cfg.get('insecure-registries', [])
if '${REGISTRY_HOST}' not in regs:
    regs.append('${REGISTRY_HOST}')
    cfg['insecure-registries'] = regs
    with open(config_path, 'w') as f:
        json.dump(cfg, f, indent=2)
    print('Updated')
else:
    print('Already configured')
"
        echo "Restarting Docker..."
        orb restart docker; sleep 3
        echo -e "${GREEN}✓ Done${NC}"
        curl -sf --connect-timeout 5 "http://${REGISTRY_HOST}/v2/" &>/dev/null && echo -e "${GREEN}✓ Registry accessible${NC}"
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
    echo -e "${GREEN}Detected: Docker Desktop (macOS)${NC}\n"
    echo "Open Docker Desktop → Settings → Docker Engine → add:"
    echo -e "  ${CYAN}\"insecure-registries\": [\"${REGISTRY_HOST}\"]${NC}"
    echo "Then click 'Apply & Restart'."
elif [[ -f "/etc/docker/daemon.json" ]] || command -v dockerd &>/dev/null; then
    echo -e "${GREEN}Detected: Docker Engine (Linux)${NC}"
    DAEMON_JSON="/etc/docker/daemon.json"
    echo -e "Add to ${DAEMON_JSON}:"
    echo -e "  ${CYAN}{\"insecure-registries\": [\"${REGISTRY_HOST}\"]}${NC}\n"
    read -rp "Run automatically? (y/N) " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        if [[ -f "$DAEMON_JSON" ]]; then
            python3 -c "
import json
with open('$DAEMON_JSON') as f: cfg = json.load(f)
regs = cfg.get('insecure-registries', [])
if '$REGISTRY_HOST' not in regs:
    regs.append('$REGISTRY_HOST'); cfg['insecure-registries'] = regs
    with open('$DAEMON_JSON', 'w') as f: json.dump(cfg, f, indent=2)
    print('Updated')
else: print('Already configured')
"
        else
            echo "{\"insecure-registries\": [\"${REGISTRY_HOST}\"]}" | sudo tee "$DAEMON_JSON"
        fi
        sudo systemctl restart docker
        echo -e "${GREEN}✓ Docker restarted${NC}"
    fi
else
    echo -e "${YELLOW}Could not detect Docker runtime.${NC}"
    echo "Manually add: ${CYAN}\"insecure-registries\": [\"${REGISTRY_HOST}\"]${NC}"
fi
