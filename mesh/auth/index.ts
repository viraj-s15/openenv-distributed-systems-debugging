import { existsSync } from "node:fs";

type AuthConfig = {
  delay_ms: number;
};

const MESH_ROOT = process.env.MESH_ROOT || "/mesh";
const CONFIG_PATH = `${MESH_ROOT}/auth/config.json`;
const CURRENT_TASK_PATH = "/tmp/current_task";
const PORT = 3001;

let config: AuthConfig;

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

const log = async (event: string, level: "INFO" | "WARN" | "ERROR", details: Record<string, unknown> = {}) => {
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      level,
      service: "auth",
      event,
      pattern: await currentPattern(),
      ...details,
    }),
  );
};

const loadConfig = async () => {
  config = await readJson<AuthConfig>(CONFIG_PATH, { delay_ms: 200 });
};

await loadConfig();

process.on("SIGHUP", async () => {
  await loadConfig();
  await log("config_reloaded", "INFO", { config });
});

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok", delay_ms: config.delay_ms });
    }

    if (req.method === "POST" && url.pathname === "/verify") {
      const started = Date.now();
      await log("verify_start", "INFO", { delay_ms: config.delay_ms });

      await sleep(Math.max(0, config.delay_ms));

      const elapsed = Date.now() - started;
      await log("verify_complete", "INFO", {
        delay_ms: config.delay_ms,
        elapsed_ms: elapsed,
      });

      return Response.json({ verified: true, elapsed_ms: elapsed });
    }

    return new Response("not found", { status: 404 });
  },
});
