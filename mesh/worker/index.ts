import { existsSync } from "node:fs";

import Redis from "ioredis";
import { Database } from "bun:sqlite";

type WorkerConfig = {
  db_pool_size: number;
  db_write_delay_ms: number;
};

const MESH_ROOT = process.env.MESH_ROOT || "/mesh";
const CONFIG_PATH = `${MESH_ROOT}/worker/config.json`;
const CURRENT_TASK_PATH = "/tmp/current_task";

const LOCK_KEY = "LOCK:job_processor";
const ENQUEUE_RATE_PER_S = Number(process.env.ENQUEUE_RATE_PER_S || "3.0");

let config: WorkerConfig;
let running = true;
let backoffMs = 1000;

const redis = new Redis({ host: "localhost", port: 6379, maxRetriesPerRequest: 1 });
const db = new Database("/tmp/worker_jobs.sqlite");
db.exec(
  "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const readJson = async <T>(path: string, fallback: T): Promise<T> => {
  try {
    return (await Bun.file(path).json()) as T;
  } catch {
    return fallback;
  }
};

const currentPattern = async (): Promise<string> => {
  if (!existsSync(CURRENT_TASK_PATH)) return "unknown";
  try {
    return (await Bun.file(CURRENT_TASK_PATH).text()).trim() || "unknown";
  } catch {
    return "unknown";
  }
};


const incrementCounter = async (path: string): Promise<number> => {
  let current = 0;
  try {
    current = Number(await Bun.file(path).text()) || 0;
  } catch {
    current = 0;
  }

  const next = current + 1;
  await Bun.write(path, String(next));
  return next;
};

const log = async (event: string, level: "INFO" | "WARN" | "ERROR", details: Record<string, unknown> = {}) => {
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      level,
      service: "worker",
      event,
      pattern: await currentPattern(),
      ...details,
    }),
  );
};

const loadConfig = async () => {
  config = await readJson<WorkerConfig>(CONFIG_PATH, {
    db_pool_size: 10,
    db_write_delay_ms: 0,
  });
};

const estimatedProcessingRate = (): number => {
  const unitCostMs = Math.max(50, config.db_write_delay_ms + 120);
  return config.db_pool_size * (1000 / unitCostMs);
};

const processLoop = async () => {
  while (running) {
    try {
      const acquired = await redis.set(LOCK_KEY, String(process.pid), "EX", 30, "NX");
      if (!acquired) {
        const stallCount = await incrementCounter("/tmp/consumer_stall_count");
        await log("lock_acquire_failed", "WARN", {
          lock_key: LOCK_KEY,
          stall_count: stallCount,
        });
        await sleep(120);
        continue;
      }

      const raw = await redis.lpop("job_queue");
      if (!raw) {
        await redis.del(LOCK_KEY);
        await sleep(120);
        continue;
      }

      let parsed: { id?: string; payload?: unknown };
      try {
        parsed = JSON.parse(raw) as { id?: string; payload?: unknown };
      } catch (error) {
        const restartCount = await incrementCounter("/tmp/worker_restart_count");
        await log("job_dequeued", "INFO", { raw });
        await log("parse_failed", "ERROR", {
          error: error instanceof Error ? error.message : String(error),
          raw,
        });
        await log("consumer_backoff", "WARN", {
          restart_count: restartCount,
          backoff_ms: backoffMs,
        });

        await redis.lpush("job_queue", raw);
        await redis.del(LOCK_KEY);
        await sleep(backoffMs);
        backoffMs = Math.min(10000, backoffMs * 2);
        continue;
      }

      const start = Date.now();
      if (config.db_write_delay_ms > 0) {
        await sleep(config.db_write_delay_ms);
      }

      db.query("INSERT OR REPLACE INTO jobs (id, payload) VALUES (?, ?)").run(
        parsed.id || crypto.randomUUID(),
        JSON.stringify(parsed.payload ?? null),
      );

      backoffMs = 1000;
      const elapsedMs = Date.now() - start;
      const queueDepth = Number(await redis.llen("job_queue"));
      await log("db_write_complete", "INFO", {
        elapsed_ms: elapsedMs,
        pool_size: config.db_pool_size,
      });

      const processingRate = estimatedProcessingRate();
      if (processingRate < ENQUEUE_RATE_PER_S || queueDepth > 10) {
        await log("throughput_lag", "WARN", {
          processing_rate_per_s: Number(processingRate.toFixed(2)),
          enqueue_rate_per_s: ENQUEUE_RATE_PER_S,
          queue_depth: queueDepth,
        });
      }

      await log("job_processed", "INFO", {
        job_id: parsed.id || null,
        queue_depth: queueDepth,
      });

      await redis.del(LOCK_KEY);
      await sleep(80);
    } catch (error) {
      await log("loop_error", "ERROR", {
        error: error instanceof Error ? error.message : String(error),
      });
      await sleep(250);
    }
  }
};

if (!existsSync("/tmp/worker_restart_count")) await Bun.write("/tmp/worker_restart_count", "0");
if (!existsSync("/tmp/consumer_stall_count")) await Bun.write("/tmp/consumer_stall_count", "0");
await Bun.write("/tmp/worker.pid", String(process.pid));

await loadConfig();

process.on("SIGHUP", async () => {
  await loadConfig();
  await log("config_reloaded", "INFO", { config });
});

process.on("SIGTERM", () => {
  running = false;
});

process.on("SIGINT", () => {
  running = false;
});

await processLoop();

try {
  await redis.quit();
} catch {
  redis.disconnect();
}
db.close();
