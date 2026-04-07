#!/bin/bash
set -e

echo "Waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until nc -z "${POSTGRES_HOST}" "${POSTGRES_PORT}"; do
  echo "Postgres is unavailable - retrying in 1s"
  sleep 1
done

echo "Postgres is up - running migrations"
alembic upgrade head
