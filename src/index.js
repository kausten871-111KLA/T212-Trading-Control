const T212_DEMO_BASE_URL = "https://demo.trading212.com/api/v0";
const MAX_ABS_QUANTITY = 1;

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

function executionConfigured(env) {
  return Boolean(env.T212_CONTROL_TOKEN && env.T212_ORDER_GUARD);
}

function authorised(request, env) {
  const expected = `Bearer ${env.T212_CONTROL_TOKEN || ""}`;
  return Boolean(env.T212_CONTROL_TOKEN) && request.headers.get("authorization") === expected;
}

async function t212Request(env, path, init = {}) {
  const auth = btoa(`${env.T212_DEMO_API_KEY}:${env.T212_DEMO_API_SECRET}`);
  return fetch(`${T212_DEMO_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Basic ${auth}`,
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
}

async function parseUpstream(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

async function t212Json(env, path, init = {}, label = "request") {
  const response = await t212Request(env, path, init);
  const data = await parseUpstream(response);
  if (!response.ok) {
    return {
      error: json(
        {
          ok: false,
          connected: response.status !== 401 && response.status !== 403,
          environment: "Trading 212 Demo",
          upstreamStatus: response.status,
          error: `Trading 212 Demo rejected ${label}.`,
          details: data,
        },
        response.status >= 500 ? 502 : response.status,
      ),
    };
  }
  return { data, upstreamStatus: response.status };
}

function validateMarketOrder(body) {
  if (!body || body.environment !== "demo") return "environment must be demo";
  if (body.confirmed !== true) return "confirmed must be true";
  if (typeof body.approvalId !== "string" || !/^[A-Za-z0-9_-]{8,80}$/.test(body.approvalId)) {
    return "approvalId must be 8-80 letters, numbers, underscores or hyphens";
  }
  if (typeof body.ticker !== "string" || !/^[A-Za-z0-9._-]{2,80}$/.test(body.ticker)) {
    return "ticker is invalid";
  }
  if (typeof body.quantity !== "number" || !Number.isFinite(body.quantity) || body.quantity <= 0) {
    return "quantity must be a positive number";
  }
  if (body.quantity > MAX_ABS_QUANTITY) return `quantity exceeds smoke-test cap of ${MAX_ABS_QUANTITY}`;
  return null;
}

async function handleRead(request, env, url) {
  if (!credentialsConfigured(env)) {
    return json({ ok: false, connected: false, error: "Trading 212 Demo secrets are not configured." }, 503);
  }

  if (!authorised(request, env)) {
    return json({ ok: false, error: "Unauthorised control request." }, 401);
  }

  const routes = {
    "/t212/test": ["/equity/account/cash", "account cash request"],
    "/t212/cash": ["/equity/account/cash", "account cash request"],
    "/t212/positions": ["/equity/portfolio", "positions request"],
    "/t212/orders": ["/equity/orders", "pending orders request"],
    "/t212/instruments": ["/equity/metadata/instruments", "instruments request"],
    "/t212/exchanges": ["/equity/metadata/exchanges", "exchanges request"],
  };

  if (url.pathname === "/t212/account") {
    const [cash, positions, orders] = await Promise.all([
      t212Json(env, "/equity/account/cash", {}, "account cash request"),
      t212Json(env, "/equity/portfolio", {}, "positions request"),
      t212Json(env, "/equity/orders", {}, "pending orders request"),
    ]);
    if (cash.error) return cash.error;
    if (positions.error) return positions.error;
    if (orders.error) return orders.error;
    return json({
      ok: true,
      connected: true,
      environment: "Trading 212 Demo",
      executionEnabled: executionConfigured(env),
      data: { cash: cash.data, positions: positions.data, orders: orders.data },
    });
  }

  if (url.pathname.startsWith("/t212/orders/") && url.pathname !== "/t212/orders/market") {
    const orderId = url.pathname.slice("/t212/orders/".length);
    if (!/^\d+$/.test(orderId)) return json({ ok: false, error: "Invalid order ID." }, 400);
    const result = await t212Json(env, `/equity/orders/${orderId}`, {}, "order read-back request");
    if (result.error) return result.error;
    return json({ ok: true, connected: true, environment: "Trading 212 Demo", data: result.data });
  }

  const route = routes[url.pathname];
  if (!route) return json({ ok: false, error: "Not found." }, 404);
  const result = await t212Json(env, route[0], {}, route[1]);
  if (result.error) return result.error;
  return json({ ok: true, connected: true, environment: "Trading 212 Demo", data: result.data });
}

async function handleMarketOrder(request, env) {
  if (!credentialsConfigured(env) || !executionConfigured(env)) {
    return json({
      ok: false,
      error: "Execution is locked until Demo credentials, control token and order guard are configured.",
      executionEnabled: false,
    }, 503);
  }
  if (!authorised(request, env)) return json({ ok: false, error: "Unauthorised control request." }, 401);
  if (!request.headers.get("content-type")?.toLowerCase().includes("application/json")) {
    return json({ ok: false, error: "Content-Type must be application/json." }, 415);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "Invalid JSON body." }, 400);
  }
  const validationError = validateMarketOrder(body);
  if (validationError) return json({ ok: false, error: validationError }, 400);

  const guardKey = `approval:${body.approvalId}`;
  const prior = await env.T212_ORDER_GUARD.get(guardKey, { type: "json" });
  if (prior) {
    return json({ ok: false, duplicateBlocked: true, error: "This approvalId has already been used.", prior }, 409);
  }

  // Reserve before submission. Never retry a POST automatically.
  await env.T212_ORDER_GUARD.put(guardKey, JSON.stringify({
    state: "reserved",
    ticker: body.ticker,
    quantity: body.quantity,
    reservedAt: new Date().toISOString(),
  }), { expirationTtl: 60 * 60 * 24 * 90 });

  const result = await t212Json(env, "/equity/orders/market", {
    method: "POST",
    body: JSON.stringify({ ticker: body.ticker, quantity: body.quantity, extendedHours: false }),
  }, "approved Demo market order");

  if (result.error) {
    await env.T212_ORDER_GUARD.put(guardKey, JSON.stringify({
      state: "submission_failed_no_retry",
      ticker: body.ticker,
      quantity: body.quantity,
      failedAt: new Date().toISOString(),
    }), { expirationTtl: 60 * 60 * 24 * 90 });
    return result.error;
  }

  const orderId = result.data?.id ?? result.data?.orderId ?? null;
  await env.T212_ORDER_GUARD.put(guardKey, JSON.stringify({
    state: "submitted",
    ticker: body.ticker,
    quantity: body.quantity,
    orderId,
    submittedAt: new Date().toISOString(),
  }), { expirationTtl: 60 * 60 * 24 * 90 });

  return json({
    ok: true,
    environment: "Trading 212 Demo",
    executionEnabled: true,
    approvalId: body.approvalId,
    orderId,
    data: result.data,
    next: orderId ? `GET /t212/orders/${orderId}` : "GET /t212/orders and GET /t212/positions",
  }, 201);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "T212 Trading Control - Phase 3",
        environment: "Trading 212 Demo",
        credentialsConfigured: credentialsConfigured(env),
        executionConfigured: executionConfigured(env),
        executionEnabled: credentialsConfigured(env) && executionConfigured(env),
        safety: ["Demo base URL hard-coded", "explicit approvalId required", "duplicate approval blocked", "no automatic POST retry", "quantity capped"],
      });
    }

    if (request.method === "GET") return handleRead(request, env, url);
    if (request.method === "POST" && url.pathname === "/t212/orders/market") {
      return handleMarketOrder(request, env);
    }
    return json({ ok: false, error: "Method or route not allowed." }, 405);
  },
};
