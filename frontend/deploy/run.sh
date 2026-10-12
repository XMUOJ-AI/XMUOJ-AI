#!/bin/sh
set -eu

base=/OJ_FE

cd "$base"
npm ci --include=dev
npm run build

exec nginx -c /OJ_FE/deploy/nginx.conf
