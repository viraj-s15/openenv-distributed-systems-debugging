# Distributed Systems Debug Environment

## Overview
This project provides an OpenEnv-compatible RL environment for debugging distributed systems failures.

The environment simulates a production-style pipeline:

- Gateway service (sync HTTP orchestration)
- Auth service (sync dependency)
- Redis queue (message bus)
- Worker service (async consumer + lock handling)
- SQLite sink (persistence simulation)

An agent interacts only through shell commands and must diagnose/fix injected faults.

## Why this environment
Most RL environments focus on games or synthetic workflows. This one targets operational debugging skills used in real systems engineering:

- reading logs under uncertainty
- triaging latency and queue symptoms
- fixing misconfigurations safely
- validating recovery from metrics

## Architecture
```
Agent command -> /step (FastAPI)
                  |
                  +-> executes shell command (sandboxed, 10s timeout)
                  +-> polls metrics
                  +-> grades progress

Services (same container):
  gateway:3000 -> auth:3001 -> redis:6379 -> worker -> sqlite
```

## Observation Space
| Field | Type | Description |
|---|---|---|
| `command_output` | string | stdout+stderr of last command |
| `metrics.gateway_success_rate` | float [0,1] | rolling gateway success rate |
| `metrics.gateway_p99_latency_ms` | float | rolling p99 latency |
| `metrics.queue_depth` | int | Redis queue depth |
| `metrics.worker_restart_count` | int | simulated crash-loop count |
| `metrics.consumer_stall_count` | int | lock-starvation stall count |
| `process_status` | object | runtime status by service |

## Action Space
Single command action:

```json
{ "command": "<bash command>" }
```

Examples:
- `tail -20 /tmp/worker.log`
- `redis-cli DEL LOCK:job_processor`
- `cat /mesh/gateway/blocked_routes.json`
- `kill -HUP $(cat /tmp/worker.pid)`

## Tasks
| Task | Difficulty | Goal |
|---|---|---|
| `cascading-timeout` | easy | restore successful sync flow (auth delay vs gateway timeout) |
| `byzantine-queue-fault` | medium | remove poison message and stabilize worker |
| `distributed-lock-starvation` | hard | clear stale lock and resume consumption |
| `backpressure-cascade` | hard | recover throughput and reduce queue growth |
| `route-partition` | hard | unblock gateway->redis route policy |
| `registry-corruption` | medium | repair corrupted auth registry entry and restore request flow |
| `job-generator-runaway` | hard | reduce enqueue pressure so the queue drains sustainably |

## Reward Function
- Terminal reward: `1.0` when grader score >= `0.95`
- Dense shaping from grader progress + investigation command bonus + metric improvements
- Penalties for blocked/damaging actions and repeated non-productive behavior
- Reward clamped to `[0.0, 1.0]`

## Baseline Inference policy (3 of 7 by default)
All seven tasks are implemented in the environment.

`inference.py` runs these default tasks for runtime reliability:

1. `cascading-timeout` (easy)
2. `byzantine-queue-fault` (medium)
3. `distributed-lock-starvation` (hard)

Override with:

```bash
TASKS_CSV=cascading-timeout,route-partition python inference.py
```

## Setup
### Local
```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

bun install --cwd mesh/gateway
bun install --cwd mesh/auth
bun install --cwd mesh/worker

APP_ROOT=$(pwd) MESH_ROOT=$(pwd)/mesh ./start.sh
```

### Docker
```bash
docker build -t dist-debug-env .
docker run -p 8000:8000 dist-debug-env
```

### API smoke check
```bash
curl http://localhost:8000/health
curl -X POST "http://localhost:8000/reset?task_name=cascading-timeout"
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"command":"ls /tmp"}'
```

## Inference script contract
`inference.py` emits strict logs:

```text
[START] task=<task_name> env=<benchmark> model=<model_name>
[STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
[END]   success=<true|false> steps=<n> rewards=<r1,r2,...,rn>
```

## Logging
Service logs (JSON-lines):
- `/tmp/gateway.log`
- `/tmp/auth.log`
- `/tmp/worker.log`

Common fields:
- `ts`, `level`, `service`, `event`, `pattern`

Example investigation commands:
```bash
tail -30 /tmp/worker.log
jq 'select(.level=="ERROR")' /tmp/worker.log
redis-cli LLEN job_queue
```

## Baseline scores
Baseline scores depend on endpoint/model latency and quality. Reproduce with:

```bash
HF_TOKEN=<token> API_BASE_URL=<endpoint> MODEL_NAME=<model> python inference.py
```


## Run this locally
Use this checklist when running the full baseline end-to-end on your machine.

1. Install dependencies and validate project setup:
```bash
./setup-dev.sh
```

2. Activate the project virtual environment (required so `uvicorn` and Python deps are on PATH):
```bash
source .venv/bin/activate
```

3. Start the environment API (leave this terminal running):
```bash
APP_ROOT=$(pwd) MESH_ROOT=$(pwd)/mesh ./start.sh
```

4. In another terminal, activate venv again and export required inference variables:
```bash
source .venv/bin/activate
export API_BASE_URL="https://openrouter.ai/api/v1"
export MODEL_NAME="<your-model>"
export HF_TOKEN="<your-api-key>"

# Optional override; default already runs 3 baseline tasks
export TASKS_CSV="cascading-timeout,byzantine-queue-fault,distributed-lock-starvation"
```

If you have a .env file you can set the variables from the file via this command 

```bash
set -a
source .env
set +a
```

5. Run inference with a 20 minute cap and capture output:
```bash
# macOS (coreutils): gtimeout ; Linux: timeout
gtimeout 1200 python inference.py | tee inference.out
```

6. Validate structured stdout format quickly:
```bash
python - <<'PY'
import re, sys
from pathlib import Path

lines = Path("inference.out").read_text(encoding="utf-8").splitlines()
if not lines:
    print("FAIL: no output")
    raise SystemExit(1)

start_re = re.compile(r'^\[START\] task=\S+ env=\S+ model=.+$')
step_re = re.compile(r'^\[STEP\]\s{2}step=\d+ action=.* reward=\d+\.\d{2} done=(true|false) error=.*$')
end_re = re.compile(r'^\[END\]\s{3}success=(true|false) steps=\d+ rewards=.*$')

for i, line in enumerate(lines, 1):
    if line.startswith("[START]") and not start_re.match(line):
        print(f"FAIL: bad START line {i}: {line}")
        raise SystemExit(1)
    if line.startswith("[STEP]") and not step_re.match(line):
        print(f"FAIL: bad STEP line {i}: {line}")
        raise SystemExit(1)
    if line.startswith("[END]") and not end_re.match(line):
        print(f"FAIL: bad END line {i}: {line}")
        raise SystemExit(1)

print("PASS: stdout format valid")
PY
```

7. Re-run required submission gates:
```bash
openenv validate .
docker build -t dist-debug-env:local .
```
