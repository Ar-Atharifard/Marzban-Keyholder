// Optional platform contract test. Uses synthetic data and no Internet access.
// WORKERD_BIN=/path/to/workerd node --test deploy/cloudflare-subscription/runtime.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, copyFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { once } from "node:events";

test("workerd accepts outbound cache settings and streams the subscription", {
  skip: !process.env.WORKERD_BIN,
  timeout: 15000,
}, async () => {
  const socket = createServer();
  socket.listen(0, "127.0.0.1");
  await once(socket, "listening");
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const directory = await mkdtemp(join(tmpdir(), "keyholder-workerd-test-"));
  let child;
  let diagnostics = "";
  try {
    await copyFile(new URL("./worker.mjs", import.meta.url), join(directory, "worker.mjs"));
    await writeFile(join(directory, "origin.mjs"), `export default {fetch(){
      return new Response("dmxlc3M6Ly9zeW50aGV0aWM=", {headers:{
        "content-type":"text/plain", "subscription-userinfo":"upload=0; download=1; total=2"
      }});
    }};`);
    await writeFile(join(directory, "config.capnp"), `using Workerd = import "/workerd/workerd.capnp";
const config :Workerd.Config = (
  services = [
    (name = "main", worker = (
      modules = [(name = "worker.mjs", esModule = embed "worker.mjs")],
      compatibilityDate = "2026-10-16",
      bindings = [(name = "UPSTREAM_ORIGIN", text = "https://origin.example.com")],
      globalOutbound = "origin")),
    (name = "origin", worker = (
      modules = [(name = "origin.mjs", esModule = embed "origin.mjs")],
      compatibilityDate = "2026-10-16"))
  ],
  sockets = [(name = "http", address = "127.0.0.1:${port}", http = (), service = "main")]
);`);
    child = spawn(process.env.WORKERD_BIN, ["serve", join(directory, "config.capnp")], {
      stdio: ["ignore", "ignore", "pipe"],
    });
    let startupError;
    child.on("error", error => { startupError = error; });
    child.stderr.on("data", data => { diagnostics += data.toString(); });
    let response;
    const target = `http://127.0.0.1:${port}/s/${"a".repeat(43)}`;
    for (let attempt = 0; attempt < 50; attempt++) {
      if (startupError) throw startupError;
      if (child.exitCode !== null) throw new Error(diagnostics || "workerd exited");
      try { response = await fetch(target, {signal: AbortSignal.timeout(1000)}); break; }
      catch { await new Promise(resolve => setTimeout(resolve, 50)); }
    }
    assert.ok(response, diagnostics || "workerd did not start");
    assert.equal(response.status, 200, diagnostics);
    assert.equal(await response.text(), "dmxlc3M6Ly9zeW50aGV0aWM=");
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    assert.match(response.headers.get("subscription-userinfo"), /download=1/);
  } finally {
    if (child && child.exitCode === null && !child.signalCode) {
      const exited = once(child, "exit");
      child.kill("SIGTERM");
      await exited;
    }
    await rm(directory, {recursive: true, force: true});
  }
});
