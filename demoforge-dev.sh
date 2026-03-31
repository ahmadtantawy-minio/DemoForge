#!/usr/bin/env bash
# DemoForge — Dev Mode Entry Point
#
# Sets DEMOFORGE_MODE=dev and delegates all commands to demoforge.sh.
# Dev mode differences vs FA mode:
#   - FA identity check is skipped at startup
#   - "Push to Hub" button is visible in the Templates gallery
#   - /api/templates/push-all-builtin endpoint is enabled
#   - DEV badge shown in the sidebar
#   - Template override & revert enabled
#
# Usage: ./demoforge-dev.sh [command]
# Commands are identical to demoforge.sh (start, stop, restart, status, logs, build, clean, nuke, help)

export DEMOFORGE_MODE=dev

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/demoforge.sh" "${@:-help}"
