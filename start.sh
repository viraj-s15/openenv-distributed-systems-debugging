#!/usr/bin/env bash
set -euo pipefail

export APP_ROOT="${APP_ROOT:-/home/user/app}"
export MESH_ROOT="${MESH_ROOT:-/mesh}"

mkdir -p /tmp

redis-server --daemonize yes --logfile /tmp/redis.log --port 6379
until redis-cli ping >/dev/null; do sleep 0.2; done

rm -f /tmp/*.pid /tmp/*.log /tmp/worker_restart_count /tmp/consumer_stall_count /tmp/current_task
printf '0' > /tmp/worker_restart_count
printf '0' > /tmp/consumer_stall_count

cat > "${MESH_ROOT}/registry.json" <<'EOF'
{
  "services": {
    "auth": {"host": "localhost", "port": 3001, "protocol": "http"},
    "redis": {"host": "localhost", "port": 6379, "protocol": "tcp"},
    "worker": {"host": "localhost", "port": null, "protocol": "internal"}
  }
}
EOF

: > /tmp/gateway.log
: > /tmp/auth.log
: > /tmp/worker.log
: > /tmp/job_gen.log

bun run "${APP_ROOT}/mesh/gateway/index.ts" >> /tmp/gateway.log &
echo $! > /tmp/gateway.pid

bun run "${APP_ROOT}/mesh/auth/index.ts" >> /tmp/auth.log &
echo $! > /tmp/auth.pid

bun run "${APP_ROOT}/mesh/worker/index.ts" >> /tmp/worker.log &
echo $! > /tmp/worker.pid

bun run "${APP_ROOT}/mesh/worker/job_generator.ts" >> /tmp/job_gen.log &
echo $! > /tmp/job_generator.pid

for _ in $(seq 1 45); do
  if curl -sf http://localhost:3000/health >/dev/null && curl -sf http://localhost:3001/health >/dev/null; then
    break
  fi
  sleep 1
done

exec uvicorn app:app --host 0.0.0.0 --port 8000
