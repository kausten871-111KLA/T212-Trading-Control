const T212_DEMO_BASE_URL = "https://demo.trading212.com/api/v0";

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function credentialsConfigured(env) {
  return Boolean(env.T212_DEMO_API_KEY && env.T212_DEMO_API_SECRET);
}

async function t212Get(env, path) {
  const auth = btoa(`${env.T212_DEMO_API_KEY}:${env.T212_DEMO_API_SECRET}`);
  return fetch(`${T212_DEMO_BASE_URL}${path}`, {
    method: "GET",
    headers: { Authorization: `Basic ${auth}`, Accept: "application/json" },
  });
}

async function upstreamJson(env, path, label) {
  const response = await t212Get(env, path);
  if (!response.ok) {
    return {
      error: json({ ok: false, connected: false, upstreamStatus: response.status, error: `Trading 212 Demo rejected the read-only ${label} request.` }, response.status >= 500 ? 502 : response.status),
    };
  }
  return { data: await response.json() };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Phase 2 remains deliberately read-only at the HTTP boundary.
    if (request.method !== "GET") {
      return json({ ok: false, error: "Read-only Worker: GET requests only." }, 405);
    }

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "T212 Trading Control - Phase 2",
        environment: "Trading 212 Demo",
        mode: "read-only",
        credentialsConfigured: credentialsConfigured(env),
        capabilities: ["account cash", "open positions", "account summary"],
        executionEnabled: false,
      });
    }

    if (!credentialsConfigured(env)) {
      return json({ ok: false, error: "Trading 212 Demo secrets are not configured." }, 503);
    }

    if (url.pathname === "/t212/test" || url.pathname === "/t212/cash") {
      const result = await upstreamJson(env, "/equity/account/cash", "account cash");
      if (result.error) return result.error;
      return json({ ok: true, connected: true, environment: "Trading 212 Demo", mode: "read-only", test: "account cash", data: result.data });
    }

    if (url.pathname === "/t212/positions") {
      const result = await upstreamJson(env, "/equity/portfolio", "open positions");
      if (result.error) return result.error;
      return json({ ok: true, connected: true, environment: "Trading 212 Demo", mode: "read-only", test: "open positions", count: Array.isArray(result.data) ? result.data.length : null, data: result.data });
    }

    if (url.pathname === "/t212/account") {
      const [cashResult, positionsResult] = await Promise.all([
        upstreamJson(env, "/equity/account/cash", "account cash"),
        upstreamJson(env, "/equity/portfolio", "open positions"),
      ]);
      if (cashResult.error) return cashResult.error;
      if (positionsResult.error) return positionsResult.error;
      return json({
        ok: true,
        connected: true,
        environment: "Trading 212 Demo",
        mode: "read-only",
        executionEnabled: false,
        data: {
          cash: cashResult.data,
          positions: positionsResult.data,
          positionCount: Array.isArray(positionsResult.data) ? positionsResult.data.length : null,
        },
      });
    }

    return json({ ok: false, error: "Not found." }, 404);
  },
};
