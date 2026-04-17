#!/usr/bin/env bash
# Reset the throwaway demo database. Run from the repo root.
#
# Usage:
#   ./demos/reset-db.sh
#
# Default DB: postgresql://localhost/luplo_demos
# Override with DEMO_DB_URL.

set -euo pipefail

DB_URL="${DEMO_DB_URL:-postgresql://localhost/luplo_demos}"
DB_NAME="$(echo "$DB_URL" | awk -F/ '{print $NF}')"
ADMIN_URL="${DEMO_ADMIN_URL:-postgresql://localhost/postgres}"

echo "Resetting $DB_NAME via $ADMIN_URL..."
psql "$ADMIN_URL" -c "DROP DATABASE IF EXISTS \"$DB_NAME\";"
psql "$ADMIN_URL" -c "CREATE DATABASE \"$DB_NAME\";"

echo "Applying migrations..."
LUPLO_DB_URL="$DB_URL" uv run alembic upgrade head

echo "Seeding fixtures..."
psql "$DB_URL" < "$(dirname "$0")/fixtures/seed.sql"

echo "Demo DB ready: $DB_URL"
