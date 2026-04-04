import Redis from "ioredis";

const redis = new Redis({ host: "localhost", port: 6379, maxRetriesPerRequest: 1 });
const INTERVAL_MS = Number(process.env.JOB_GEN_INTERVAL_MS || "333");

let running = true;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

    await sleep(INTERVAL_MS);
  }
};

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
