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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method !== "GET") {
      return json({ ok: false, error: "Read-only Worker: GET requests only." }, 405);
    }

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "T212 Trading Control - Phase 1",
        environment: "Trading 212 Demo",
        mode: "read-only",
        credentialsConfigured: Boolean(env.T212_DEMO_API_KEY && env.T212_DEMO_API_SECRET),
      });
    }

    if (url.pathname === "/t212/test") {
      if (!env.T212_DEMO_API_KEY || !env.T212_DEMO_API_SECRET) {
        return json({ ok: false, error: "Trading 212 Demo secrets are not configured." }, 503);
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

      const cash = await response.json();
      return json({
        ok: true,
        connected: true,
        environment: "Trading 212 Demo",
        mode: "read-only",
        test: "account cash",
        data: cash,
      });
    }

    return json({ ok: false, error: "Not found." }, 404);
  },
};
