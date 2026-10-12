#!/usr/bin/env bash
set -euo pipefail

# Explicit legacy container deployment; use npm run build for a build only.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

npm ci --include=dev
npm run build
sudo docker cp "$SCRIPT_DIR/dist" oj-backend:/app/
sudo docker exec -it oj-backend /bin/sh
