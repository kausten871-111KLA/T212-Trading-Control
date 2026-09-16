const T212_DEMO_BASE_URL = "https://demo.trading212.com/api/v0";
const MAX_ABS_QUANTITY = 1;

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

function credentialsConfigured(env) { return Boolean(env.T212_DEMO_API_KEY && env.T212_DEMO_API_SECRET); }
function readConfigured(env) { return Boolean(env.T212_AGENT_TOKEN); }
function executionConfigured(env) { return Boolean(env.T212_AGENT_TOKEN && env.T212_APPROVER_TOKEN && env.T212_DB); }
function bearer(request) { const value = request.headers.get("authorization") || ""; return value.startsWith("Bearer ") ? value.slice(7) : ""; }
function authorised(request, env, role) { const token = role === "approver" ? env.T212_APPROVER_TOKEN : env.T212_AGENT_TOKEN; return Boolean(token) && bearer(request) === token; }

async function t212Request(env, path, init = {}) {
  const auth = btoa(`${env.T212_DEMO_API_KEY}:${env.T212_DEMO_API_SECRET}`);
  return fetch(`${T212_DEMO_BASE_URL}${path}`, { ...init, headers: { Authorization: `Basic ${auth}`, Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...(init.headers || {}) } });
}

async function parseUpstream(response) {
  const text = await response.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return { raw: text.slice(0, 1000) }; }
}

async function t212Json(env, path, init = {}, label = "request") {
  try {
    const response = await t212Request(env, path, init);
    const data = await parseUpstream(response);
    if (!response.ok) return { status: response.status, data, error: json({ ok: false, connected: response.status !== 401 && response.status !== 403, environment: "Trading 212 Demo", upstreamStatus: response.status, error: `Trading 212 Demo rejected ${label}.`, details: data }, response.status >= 500 ? 502 : response.status) };
    return { data, status: response.status };
  } catch (error) {
    return { networkError: true, message: error instanceof Error ? error.message : "Network error" };
  }
}

function validateProposal(body) {
  if (!body || body.environment !== "demo") return "environment must be demo";
  if (typeof body.ticker !== "string" || !/^[A-Za-z0-9._-]{2,80}$/.test(body.ticker)) return "ticker is invalid";
  if (typeof body.quantity !== "number" || !Number.isFinite(body.quantity) || body.quantity <= 0) return "quantity must be positive";
  if (body.quantity > MAX_ABS_QUANTITY) return `quantity exceeds smoke-test cap of ${MAX_ABS_QUANTITY}`;
  return null;
}

async function readJson(request) {
  if (!request.headers.get("content-type")?.toLowerCase().includes("application/json")) return { error: json({ ok: false, error: "Content-Type must be application/json." }, 415) };
  try { return { body: await request.json() }; } catch { return { error: json({ ok: false, error: "Invalid JSON body." }, 400) }; }
}

function proposalView(row) {
  if (!row) return null;
  return { id: row.id, environment: "demo", ticker: row.ticker, quantity: row.quantity, state: row.state, preparedAt: row.prepared_at, expiresAt: row.expires_at, approvedAt: row.approved_at, submittedAt: row.submitted_at, orderId: row.order_id };
}
async function getProposal(env, id) { return env.T212_DB.prepare("SELECT * FROM proposals WHERE id = ?").bind(id).first(); }

async function handlePrepare(request, env) {
  if (!authorised(request, env, "agent")) return json({ ok: false, error: "Unauthorised agent request." }, 401);
  const parsed = await readJson(request); if (parsed.error) return parsed.error;
  const validationError = validateProposal(parsed.body); if (validationError) return json({ ok: false, error: validationError }, 400);
  const id = `PAPER-${crypto.randomUUID()}`;
  const preparedAt = new Date();
  const ttl = Math.min(Math.max(Number(parsed.body.ttlSeconds) || 900, 60), 900);
  const expiresAt = new Date(preparedAt.getTime() + ttl * 1000);
  await env.T212_DB.prepare("INSERT INTO proposals (id,ticker,quantity,state,prepared_at,expires_at) VALUES (?,?,?,?,?,?)").bind(id, parsed.body.ticker, parsed.body.quantity, "PREPARED", preparedAt.toISOString(), expiresAt.toISOString()).run();
  return json({ ok: true, proposal: proposalView(await getProposal(env, id)), next: `POST /t212/proposals/${id}/approve` }, 201);
}

async function handleApprove(request, env, id) {
  if (!authorised(request, env, "approver")) return json({ ok: false, error: "Unauthorised human-approval request." }, 401);
  const parsed = await readJson(request); if (parsed.error) return parsed.error;
  if (parsed.body?.confirm !== `APPROVE PAPER ${id} AS WRITTEN`) return json({ ok: false, error: "Exact approval phrase is required." }, 400);
  const now = new Date().toISOString();
  const result = await env.T212_DB.prepare("UPDATE proposals SET state='APPROVED', approved_at=? WHERE id=? AND state='PREPARED' AND expires_at>?").bind(now, id, now).run();
  if (result.meta?.changes !== 1) return json({ ok: false, error: "Proposal not found, expired, or not awaiting approval." }, 409);
  return json({ ok: true, proposal: proposalView(await getProposal(env, id)), next: `POST /t212/proposals/${id}/execute` });
}

async function handleExecute(request, env, id) {
  if (!authorised(request, env, "agent")) return json({ ok: false, error: "Unauthorised agent request." }, 401);
  const now = new Date().toISOString();
  const claim = await env.T212_DB.prepare("UPDATE proposals SET state='SUBMITTING' WHERE id=? AND state='APPROVED' AND expires_at>?").bind(id, now).run();
  if (claim.meta?.changes !== 1) return json({ ok: false, duplicateBlocked: true, error: "Approval is unavailable, expired, or already consumed.", proposal: proposalView(await getProposal(env, id)) }, 409);
  const proposal = await getProposal(env, id);
  const result = await t212Json(env, "/equity/orders/market", { method: "POST", body: JSON.stringify({ ticker: proposal.ticker, quantity: proposal.quantity, extendedHours: false }) }, "approved Demo market order");
  if (result.networkError) {
    await env.T212_DB.prepare("UPDATE proposals SET state='UNKNOWN', error_code='NETWORK_UNKNOWN' WHERE id=? AND state='SUBMITTING'").bind(id).run();
    return json({ ok: false, noRetry: true, error: "Order response was uncertain. Do not retry; reconcile pending/history orders first.", proposal: proposalView(await getProposal(env, id)) }, 502);
  }
  if (result.error) {
    await env.T212_DB.prepare("UPDATE proposals SET state='UPSTREAM_REJECTED', error_code=? WHERE id=? AND state='SUBMITTING'").bind(String(result.status), id).run();
    return result.error;
  }
  const orderId = result.data?.id ?? result.data?.orderId ?? null;
  await env.T212_DB.prepare("UPDATE proposals SET state='SUBMITTED', submitted_at=?, order_id=? WHERE id=? AND state='SUBMITTING'").bind(new Date().toISOString(), orderId === null ? null : String(orderId), id).run();
  return json({ ok: true, environment: "Trading 212 Demo", proposal: proposalView(await getProposal(env, id)), upstream: result.data, next: `GET /t212/proposals/${id}/verify` }, 201);
}

async function handleVerify(request, env, id) {
  if (!authorised(request, env, "agent")) return json({ ok: false, error: "Unauthorised agent request." }, 401);
  const proposal = await getProposal(env, id); if (!proposal) return json({ ok: false, error: "Proposal not found." }, 404);
  const [orders, positions, cash, history] = await Promise.all([
    t212Json(env, "/equity/orders", {}, "pending orders request"),
    t212Json(env, "/equity/portfolio", {}, "positions request"),
    t212Json(env, "/equity/account/cash", {}, "account cash request"),
    t212Json(env, "/equity/history/orders?limit=50", {}, "order history request"),
  ]);
  for (const result of [orders, positions, cash, history]) { if (result.networkError) return json({ ok: false, error: "Verification network failure.", noRetryOrder: true }, 502); if (result.error) return result.error; }
  return json({ ok: true, environment: "Trading 212 Demo", proposal: proposalView(proposal), verification: { pendingOrders: orders.data, history: history.data, positions: positions.data, cash: cash.data }, instruction: "Match ticker, quantity and order ID; then confirm the same order in the Trading 212 Practice UI." });
}

async function handleRead(request, env, url) {
  if (!authorised(request, env, "agent")) return json({ ok: false, error: "Unauthorised agent request." }, 401);
  const routes = {
    "/t212/test": ["/equity/account/cash", "account cash request"],
    "/t212/cash": ["/equity/account/cash", "account cash request"],
    "/t212/summary": ["/equity/account/summary", "account summary request"],
    "/t212/positions": ["/equity/portfolio", "positions request"],
    "/t212/orders": ["/equity/orders", "pending orders request"],
    "/t212/history/orders": ["/equity/history/orders?limit=50", "order history request"],
    "/t212/instruments": ["/equity/metadata/instruments", "instruments request"],
    "/t212/exchanges": ["/equity/metadata/exchanges", "exchanges request"],
  };
  const route = routes[url.pathname]; if (!route) return json({ ok: false, error: "Not found." }, 404);
  const result = await t212Json(env, route[0], {}, route[1]);
  if (result.networkError) return json({ ok: false, error: "Trading 212 network failure." }, 502);
  if (result.error) return result.error;
  return json({ ok: true, connected: true, environment: "Trading 212 Demo", data: result.data });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") return json({ ok: true, service: "T212 Trading Control - Phase 3", environment: "Trading 212 Demo", credentialsConfigured: credentialsConfigured(env), readConfigured: readConfigured(env), executionConfigured: executionConfigured(env), executionEnabled: credentialsConfigured(env) && executionConfigured(env) });
    if (!credentialsConfigured(env) || !readConfigured(env)) return json({ ok: false, error: "Demo credentials or read controls are not configured.", executionEnabled: false }, 503);
    if (request.method === "GET") { const match = url.pathname.match(/^\/t212\/proposals\/([^/]+)\/verify$/); if (match) { if (!executionConfigured(env)) return json({ ok: false, error: "Execution controls are not configured.", executionEnabled: false }, 503); return handleVerify(request, env, match[1]); } return handleRead(request, env, url); }
    if (!executionConfigured(env)) return json({ ok: false, error: "Execution controls are not configured.", executionEnabled: false }, 503);
    if (request.method === "POST" && url.pathname === "/t212/proposals") return handlePrepare(request, env);
    if (request.method === "POST") { const match = url.pathname.match(/^\/t212\/proposals\/([^/]+)\/(approve|execute)$/); if (match?.[2] === "approve") return handleApprove(request, env, match[1]); if (match?.[2] === "execute") return handleExecute(request, env, match[1]); }
    return json({ ok: false, error: "Method or route not allowed." }, 405);
  },
};
