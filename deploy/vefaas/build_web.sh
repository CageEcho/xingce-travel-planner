#!/usr/bin/env bash
set -euo pipefail
npm ci --legacy-peer-deps
VEFAAS_DEPLOYMENT=true NEXT_PUBLIC_PUBLIC_DEMO=true npm run build
cp -R public .next/standalone/public
cp -R .next/static .next/standalone/.next/static
