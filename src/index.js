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

function configured(env) {
  return Boolean(env.T212_DEMO_API_KEY && env.T212_DEMO_API_SECRET);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Phase 1 safety boundary: this Worker accepts GET only.
    if (request.method !== "GET") {
      return json({ ok: false, error: "Phase 1 is read-only: GET only." }, 405);
    }

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "T212 Trading Control - Phase 1",
        environment: "Trading 212 Demo",
        mode: "read-only connection test",
        credentialsConfigured: configured(env),
        executionEnabled: false,
      });
    }

    if (url.pathname !== "/t212/test") {
      return json({ ok: false, error: "Not found." }, 404);
    }

    if (!configured(env)) {
      return json({ ok: false, connected: false, error: "Cloudflare secrets are not configured." }, 503);
    }

    const auth = btoa(`${env.T212_DEMO_API_KEY}:${env.T212_DEMO_API_SECRET}`);
    const response = await fetch(`${T212_DEMO_BASE_URL}/equity/account/cash`, {
      method: "GET",
      headers: {
        Authorization: `Basic ${auth}`,
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      return json({
        ok: false,
        connected: false,
        upstreamStatus: response.status,
        error: "Trading 212 Demo rejected the read-only connection test.",
      }, response.status >= 500 ? 502 : response.status);
    }

    return json({
      ok: true,
      connected: true,
      environment: "Trading 212 Demo",
      mode: "read-only",
      test: "account cash",
      executionEnabled: false,
      data: await response.json(),
    });
  },
};
