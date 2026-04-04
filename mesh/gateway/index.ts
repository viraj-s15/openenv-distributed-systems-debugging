import { existsSync } from "node:fs";

import Redis from "ioredis";

type GatewayConfig = {
  auth_timeout_ms: number;
};

type Registry = {
  services: {
    auth: { host: string; port: number; protocol: string };
    redis: { host: string; port: number; protocol: string };
    worker: { host: string; port: number | null; protocol: string };
  };
};

type BlockedRoutes = {
  blocked: string[];
};

const MESH_ROOT = process.env.MESH_ROOT || "/mesh";
const CONFIG_PATH = `${MESH_ROOT}/gateway/config.json`;
const BLOCKED_ROUTES_PATH = `${MESH_ROOT}/gateway/blocked_routes.json`;
const REGISTRY_PATH = `${MESH_ROOT}/registry.json`;
const CURRENT_TASK_PATH = "/tmp/current_task";
const PORT = 3000;

let config: GatewayConfig;
let registry: Registry;
let redisClient: Redis;

const successWindow: number[] = [];
const latencyWindow: number[] = [];
const WINDOW_SIZE = 20;

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
  const payload = {
    ts: new Date().toISOString(),
    level,
    service: "gateway",
    event,
    pattern: await currentPattern(),
    ...details,
  };
  console.log(JSON.stringify(payload));
};

const loadRuntimeState = async () => {
  config = await readJson<GatewayConfig>(CONFIG_PATH, { auth_timeout_ms: 500 });
  registry = await readJson<Registry>(REGISTRY_PATH, {
    services: {
      auth: { host: "localhost", port: 3001, protocol: "http" },
      redis: { host: "localhost", port: 6379, protocol: "tcp" },
      worker: { host: "localhost", port: null, protocol: "internal" },
    },
  });

  if (redisClient) {
    redisClient.disconnect();
  }

  redisClient = new Redis({
    host: registry.services.redis.host,
    port: registry.services.redis.port,
    maxRetriesPerRequest: 1,
    lazyConnect: false,
  });
};

const fetchWithTimeout = async (
  url: string,
  init: RequestInit,
  timeoutMs: number,
 ): Promise<Response> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
};

const percentile99 = (values: number[]): number => {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(0.99 * sorted.length));
  return sorted[idx];
};

const recordOutcome = (success: boolean, elapsedMs: number) => {
  successWindow.push(success ? 1 : 0);
  latencyWindow.push(elapsedMs);

  if (successWindow.length > WINDOW_SIZE) {
    successWindow.shift();
  }
  if (latencyWindow.length > WINDOW_SIZE) {
    latencyWindow.shift();
  }
};

const getSuccessRate = (): number => {
  if (!successWindow.length) return 1;
  const successes = successWindow.reduce((acc, v) => acc + v, 0);
  return successes / successWindow.length;
};

await loadRuntimeState();

process.on("SIGHUP", async () => {
  await loadRuntimeState();
  await log("config_reloaded", "INFO", { config });
});

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return Response.json({
        status: "ok",
        success_rate: getSuccessRate(),
        p99_latency_ms: percentile99(latencyWindow),
      });
    }

    if (req.method === "POST" && url.pathname === "/process") {
      const start = Date.now();

      try {
        const blockedRoutes = await readJson<BlockedRoutes>(BLOCKED_ROUTES_PATH, { blocked: [] });
        if (blockedRoutes.blocked.includes("gateway->redis")) {
          await log("route_blocked", "ERROR", {
            route: "gateway->redis",
            policy_file: BLOCKED_ROUTES_PATH,
          });
          throw new Error("redis_unreachable");
        }

        const authUrl = `http://${registry.services.auth.host}:${registry.services.auth.port}/verify`;
        const authResponse = await fetchWithTimeout(
          authUrl,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ token: "allow" }),
          },
          config.auth_timeout_ms,
        );
        if (!authResponse.ok) {
          throw new Error(`auth_status_${authResponse.status}`);
        }

        const job = JSON.stringify({ id: crypto.randomUUID(), payload: "ok" });
        await redisClient.rpush("job_queue", job);

        const elapsedMs = Date.now() - start;
        recordOutcome(true, elapsedMs);
        await log("request_complete", "INFO", {
          elapsed_ms: elapsedMs,
          upstream: "auth",
          queue_depth_hint: await redisClient.llen("job_queue"),
        });

        return Response.json({ ok: true, elapsed_ms: elapsedMs });
      } catch (error) {
        const elapsedMs = Date.now() - start;
        recordOutcome(false, elapsedMs);

        const reason = error instanceof Error ? error.message : String(error);
        if (reason === "AbortError" || reason.includes("aborted") || reason.includes("timeout")) {
          await log("upstream_timeout", "ERROR", {
            elapsed_ms: elapsedMs,
            upstream: "auth",
            threshold_ms: config.auth_timeout_ms,
          });
        }

        await log("request_failed", "ERROR", {
          path: "/process",
          status: 500,
          reason,
        });

        return new Response(JSON.stringify({ error: reason }), {
          status: 500,
          headers: { "content-type": "application/json" },
        });
      }
    }

    return new Response("not found", { status: 404 });
  },
});
