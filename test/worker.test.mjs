import assert from "node:assert/strict";
import worker from "../src/index.js";

class FakeD1 {
  constructor() { this.rows = new Map(); }
  prepare(sql) {
    const db = this;
    return {
      args: [],
      bind(...args) { this.args = args; return this; },
      async first() { return { ...(db.rows.get(this.args[0]) || null) }; },
      async run() {
        if (sql.startsWith("INSERT")) {
          const [id, ticker, quantity, state, prepared_at, expires_at] = this.args;
          db.rows.set(id, { id, ticker, quantity, state, prepared_at, expires_at, approved_at: null, submitted_at: null, order_id: null, error_code: null });
          return { meta: { changes: 1 } };
        }
        const id = sql.includes("approved_at") ? this.args[1] : sql.includes("submitted_at") ? this.args[2] : this.args[0];
        const row = db.rows.get(id);
        if (!row) return { meta: { changes: 0 } };
        if (sql.includes("SET state='APPROVED'")) {
          const [approvedAt, , now] = this.args;
          if (row.state !== "PREPARED" || row.expires_at <= now) return { meta: { changes: 0 } };
          Object.assign(row, { state: "APPROVED", approved_at: approvedAt });
        } else if (sql.includes("SET state='SUBMITTING' WHERE")) {
          const [, now] = this.args;
          if (row.state !== "APPROVED" || row.expires_at <= now) return { meta: { changes: 0 } };
          row.state = "SUBMITTING";
        } else if (sql.includes("state='SUBMITTED'")) {
          const [submittedAt, orderId] = this.args;
          if (row.state !== "SUBMITTING") return { meta: { changes: 0 } };
          Object.assign(row, { state: "SUBMITTED", submitted_at: submittedAt, order_id: orderId });
        } else if (sql.includes("state='UNKNOWN'")) {
          row.state = "UNKNOWN"; row.error_code = "NETWORK_UNKNOWN";
        } else if (sql.includes("state='UPSTREAM_REJECTED'")) {
          row.state = "UPSTREAM_REJECTED"; row.error_code = this.args[0];
        }
        return { meta: { changes: 1 } };
      },
    };
  }
}

const env = {
  T212_DEMO_API_KEY: "demo-key",
  T212_DEMO_API_SECRET: "demo-secret",
  T212_AGENT_TOKEN: "agent-token",
  T212_APPROVER_TOKEN: "approver-token",
  T212_DB: new FakeD1(),
};

let postCount = 0;
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  const value = String(url);
  if (value.endsWith("/equity/account/cash")) return Response.json({ free: 300 });
  if (value.endsWith("/equity/orders/market") && init.method === "POST") { postCount += 1; return Response.json({ id: 123, status: "NEW" }); }
  return Response.json([]);
};

const agent = { Authorization: "Bearer agent-token" };
const approver = { Authorization: "Bearer approver-token" };
const asJson = (headers, body) => ({ method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });

const health = await worker.fetch(new Request("https://worker.test/health"), env);
assert.equal(health.status, 200);
assert.equal((await health.json()).executionEnabled, true);

const denied = await worker.fetch(new Request("https://worker.test/t212/test"), env);
assert.equal(denied.status, 401);

const account = await worker.fetch(new Request("https://worker.test/t212/test", { headers: agent }), env);
assert.equal(account.status, 200);
assert.equal((await account.json()).connected, true);

const preparedResponse = await worker.fetch(new Request("https://worker.test/t212/proposals", asJson(agent, { environment: "demo", ticker: "AAPL_US_EQ", quantity: 0.01 })), env);
assert.equal(preparedResponse.status, 201);
const prepared = await preparedResponse.json();
const id = prepared.proposal.id;

const wrongApproval = await worker.fetch(new Request(`https://worker.test/t212/proposals/${id}/approve`, asJson(approver, { confirm: "yes" })), env);
assert.equal(wrongApproval.status, 400);

const approved = await worker.fetch(new Request(`https://worker.test/t212/proposals/${id}/approve`, asJson(approver, { confirm: `APPROVE PAPER ${id} AS WRITTEN` })), env);
assert.equal(approved.status, 200);
assert.equal((await approved.json()).proposal.state, "APPROVED");

const executed = await worker.fetch(new Request(`https://worker.test/t212/proposals/${id}/execute`, { method: "POST", headers: agent }), env);
assert.equal(executed.status, 201);
assert.equal((await executed.json()).proposal.orderId, "123");

const duplicate = await worker.fetch(new Request(`https://worker.test/t212/proposals/${id}/execute`, { method: "POST", headers: agent }), env);
assert.equal(duplicate.status, 409);
assert.equal((await duplicate.json()).duplicateBlocked, true);
assert.equal(postCount, 1);

const verified = await worker.fetch(new Request(`https://worker.test/t212/proposals/${id}/verify`, { headers: agent }), env);
assert.equal(verified.status, 200);
assert.equal((await verified.json()).proposal.state, "SUBMITTED");

globalThis.fetch = originalFetch;
console.log("worker tests passed");
