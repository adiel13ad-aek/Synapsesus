#!/bin/sh
set -eu
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" --no-access-log --limit-concurrency 100
