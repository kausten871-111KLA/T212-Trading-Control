import assert from "node:assert/strict";
import worker from "../src/index.js";

class Guard {
  constructor() { this.map = new Map(); }
  async get(key, options) {
    const value = this.map.get(key);
    return options?.type === "json" && value ? JSON.parse(value) : value ?? null;
  }
  async put(key, value) { this.map.set(key, value); }
}

const env = {
  T212_DEMO_API_KEY: "demo-key",
  T212_DEMO_API_SECRET: "demo-secret",
  T212_CONTROL_TOKEN: "control-token",
  T212_ORDER_GUARD: new Guard(),
};

const originalFetch = globalThis.fetch;
let postCount = 0;
globalThis.fetch = async (url, init = {}) => {
  if (String(url).endsWith("/equity/account/cash")) return Response.json({ free: 300 });
  if (String(url).endsWith("/equity/orders/market") && init.method === "POST") {
    postCount += 1;
    return Response.json({ id: 123, status: "NEW" });
  }
  if (String(url).endsWith("/equity/orders/123")) return Response.json({ id: 123, status: "FILLED" });
  return Response.json([]);
};

const auth = { Authorization: "Bearer control-token" };

const health = await worker.fetch(new Request("https://worker.test/health"), env);
assert.equal(health.status, 200);
assert.equal((await health.json()).executionEnabled, true);

const unauthorised = await worker.fetch(new Request("https://worker.test/t212/test"), env);
assert.equal(unauthorised.status, 401);

const account = await worker.fetch(new Request("https://worker.test/t212/test", { headers: auth }), env);
assert.equal(account.status, 200);
assert.equal((await account.json()).connected, true);

const orderBody = {
  environment: "demo",
  confirmed: true,
  approvalId: "PAPER-TEST-0001",
  ticker: "AAPL_US_EQ",
  quantity: 0.01,
};
const orderRequest = () => new Request("https://worker.test/t212/orders/market", {
  method: "POST",
  headers: { ...auth, "Content-Type": "application/json" },
  body: JSON.stringify(orderBody),
});
const placed = await worker.fetch(orderRequest(), env);
assert.equal(placed.status, 201);
assert.equal((await placed.json()).orderId, 123);

const duplicate = await worker.fetch(orderRequest(), env);
assert.equal(duplicate.status, 409);
assert.equal((await duplicate.json()).duplicateBlocked, true);
assert.equal(postCount, 1);

const readback = await worker.fetch(new Request("https://worker.test/t212/orders/123", { headers: auth }), env);
assert.equal(readback.status, 200);
assert.equal((await readback.json()).data.status, "FILLED");

globalThis.fetch = originalFetch;
console.log("worker tests passed");
