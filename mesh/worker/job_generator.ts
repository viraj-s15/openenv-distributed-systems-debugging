import Redis from "ioredis";

type JobGeneratorConfig = {
  interval_ms: number;
};

const redis = new Redis({ host: "localhost", port: 6379, maxRetriesPerRequest: 1 });
const MESH_ROOT = process.env.MESH_ROOT || "/mesh";
const CONFIG_PATH = `${MESH_ROOT}/worker/job_generator_config.json`;

let running = true;
let intervalMs = 333;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const readJson = async <T>(path: string, fallback: T): Promise<T> => {
  try {
    return (await Bun.file(path).json()) as T;
  } catch {
    return fallback;
  }
};

const loadConfig = async () => {
  const config = await readJson<JobGeneratorConfig>(CONFIG_PATH, { interval_ms: 333 });
  intervalMs = Math.max(10, Number(config.interval_ms) || 333);
};

const loop = async () => {
  while (running) {
    const job = JSON.stringify({
      id: crypto.randomUUID(),
      payload: {
        kind: "normal",
        ts: new Date().toISOString(),
      },
    });

    try {
      await redis.rpush("job_queue", job);
      console.log(
        JSON.stringify({
          ts: new Date().toISOString(),
          level: "INFO",
          service: "job_generator",
          event: "job_enqueued",
        }),
      );
    } catch (error) {
      console.log(
        JSON.stringify({
          ts: new Date().toISOString(),
          level: "ERROR",
          service: "job_generator",
          event: "enqueue_failed",
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    }

    await sleep(intervalMs);
  }
};

await loadConfig();

process.on("SIGHUP", async () => {
  await loadConfig();
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      level: "INFO",
      service: "job_generator",
      event: "config_reloaded",
      interval_ms: intervalMs,
    }),
  );
});

process.on("SIGTERM", () => {
  running = false;
});

process.on("SIGINT", () => {
  running = false;
});

await loop();

try {
  await redis.quit();
} catch {
  redis.disconnect();
}
