const T212_DEMO_BASE_URL = "https://demo.trading212.com/api/v0";

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function configured(env) {
  return Boolean(env.T212_DEMO_API_KEY && env.T212_DEMO_API_SECRET);
}

async function t212Get(env, path) {
  const auth = btoa(`${env.T212_DEMO_API_KEY}:${env.T212_DEMO_API_SECRET}`);
  return fetch(`${T212_DEMO_BASE_URL}${path}`, {
    method: "GET",
    headers: { Authorization: `Basic ${auth}`, Accept: "application/json" },
  });
}

async function readOnly(env, path, label) {
  const response = await t212Get(env, path);
  if (!response.ok) {
    return { error: json({ ok: false, connected: false, upstreamStatus: response.status, error: `Trading 212 Demo rejected read-only ${label}.` }, response.status >= 500 ? 502 : response.status) };
  }
  return { data: await response.json() };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Hard safety boundary: no non-GET request can reach Trading 212.
    if (request.method !== "GET") {
      return json({ ok: false, error: "Read-only Worker: GET only.", executionEnabled: false }, 405);
    }

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "T212 Trading Control - Phase 2",
        environment: "Trading 212 Demo",
        mode: "read-only",
        credentialsConfigured: configured(env),
        capabilities: ["account cash", "open positions", "account summary"],
        executionEnabled: false,
      });
    }

    if (!configured(env)) {
      return json({ ok: false, connected: false, error: "Cloudflare secrets are not configured." }, 503);
    }

    if (url.pathname === "/t212/test" || url.pathname === "/t212/cash") {
      const result = await readOnly(env, "/equity/account/cash", "account cash request");
      if (result.error) return result.error;
      return json({ ok: true, connected: true, environment: "Trading 212 Demo", mode: "read-only", executionEnabled: false, data: result.data });
    }

    if (url.pathname === "/t212/positions") {
      const result = await readOnly(env, "/equity/portfolio", "positions request");
      if (result.error) return result.error;
      return json({ ok: true, connected: true, environment: "Trading 212 Demo", mode: "read-only", executionEnabled: false, count: Array.isArray(result.data) ? result.data.length : null, data: result.data });
    }

    if (url.pathname === "/t212/account") {
      const [cash, positions] = await Promise.all([
        readOnly(env, "/equity/account/cash", "account cash request"),
        readOnly(env, "/equity/portfolio", "positions request"),
      ]);
      if (cash.error) return cash.error;
      if (positions.error) return positions.error;
      return json({
        ok: true,
        connected: true,
        environment: "Trading 212 Demo",
        mode: "read-only",
        executionEnabled: false,
        data: { cash: cash.data, positions: positions.data, positionCount: Array.isArray(positions.data) ? positions.data.length : null },
      });
    }

    return json({ ok: false, error: "Not found." }, 404);
  },
};
