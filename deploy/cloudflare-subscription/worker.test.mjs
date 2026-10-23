import test from "node:test";
import assert from "node:assert/strict";
import worker, { deliver } from "./worker.mjs";
const token = "a".repeat(43);
const env = { UPSTREAM_ORIGIN: "https://subscription.example.com" };
const url = `https://delivery.example.net/s/${token}`;
const request = (suffix = "", options = {}) => new Request(url + suffix, options);
const content = Buffer.from("vless://synthetic-config\n").toString("base64");
const reply = (headers = {}) => new Response(content, {
  headers: { "Content-Type": "text/plain; charset=utf-8", "subscription-userinfo": "upload=0; download=1; total=2; expire=0", ...headers },
});

test("preserves body and metadata, strips credentials and unsafe headers, never caches", async () => {
  const result = await deliver(request("?origin=https://attacker.invalid", {headers:{Authorization:"Bearer secret",Cookie:"private=secret","User-Agent":"v2rayNG/test"}}), env, async (target, init) => {
    assert.equal(target, `https://subscription.example.com/s/${token}`);
    assert.equal(init.redirect, "manual"); assert.equal(init.cache, "no-store");
    assert.equal("cacheTtl" in init.cf, false);
    assert.equal(init.headers.has("Authorization"), false); assert.equal(init.headers.has("Cookie"), false);
    assert.equal(init.headers.get("User-Agent"), "v2rayNG/test");
    return reply({"Set-Cookie":"private=secret",Location:"https://attacker.invalid","Cache-Control":"public,max-age=999"});
  });
  assert.equal(await result.text(), content);
  assert.equal(result.headers.get("Cache-Control"), "private, no-store");
  assert.equal(result.headers.has("Set-Cookie"), false); assert.equal(result.headers.has("Location"), false);
  assert.match(result.headers.get("subscription-userinfo"), /download=1/);
});

test("HEAD validates through GET and has no response body", async () => {
  const response = await deliver(request("", {method:"HEAD"}), env, async (_url, init) => {
    assert.equal(init.method, "GET"); return reply({"Content-Length":String(content.length)});
  });
  assert.equal(response.status, 200); assert.equal(await response.text(), "");
  assert.equal(response.headers.get("Content-Length"), String(content.length));
});

for (const path of ["/admin/customers", "/health", "/s/invalid", `/s/${token}/extra`, `/s/${token}%2fadmin`]) {
  test(`rejects route ${path.replace(token,"TOKEN")} without contacting origin`, async () => {
    const r = await deliver(new Request("https://delivery.example.net"+path),env,()=>{throw Error("must not fetch");});
    assert.equal(r.status,404);
  });
}

test("method and query validation", async () => {
  assert.equal((await deliver(request("",{method:"POST"}),env)).status,405);
  for (const q of ["?format=other","?format=uri&format=xray"]) assert.equal((await deliver(request(q),env)).status,422);
});

for (const origin of [undefined,"http://example.com","https://user:password@example.com","https://example.com/private","https://example.com/?x=y","https://example.invalid","https://example.com:9443"]) {
  test(`fails closed on invalid origin ${origin ? new URL(origin).origin : "missing"}`,async()=>{
    const r=await deliver(request(),{UPSTREAM_ORIGIN:origin},()=>{throw Error("must not fetch");});
    assert.equal(r.status,503);
  });
}

test("rejects redirects without leaking Location or token",async()=>{
  const r=await deliver(request(),env,async()=>new Response(null,{status:302,headers:{Location:`https://attacker.invalid/${token}`}}));
  assert.equal(r.status,502);assert.equal(r.headers.has("Location"),false);assert.equal((await r.text()).includes(token),false);
});

test("preserves disabled or revoked customer responses; no stale cache",async()=>{
  const r=await deliver(request(),env,async()=>new Response('{"detail":"Subscription unavailable"}',{status:404,headers:{"Content-Type":"application/json"}}));
  assert.equal(r.status,404);assert.match(await r.text(),/unavailable/);
});

test("turns unexpected HTML challenge into a nonsecret delivery error",async()=>{
  const r=await deliver(request(),env,async()=>new Response("<html>challenge</html>",{status:403,headers:{"Content-Type":"text/html"}}));
  assert.equal(r.status,403);assert.doesNotMatch(await r.text(),/<html>/);
});

test("usage page and JSON formats are forwarded explicitly",async()=>{
  for(const format of ["info","xray","uri"]){
    const r=await deliver(request("?format="+format),env,async(target)=>{
      assert.equal(new URL(target).searchParams.get("format"),format);
      return new Response(format==="info"?"<html>usage</html>":"[]",{headers:{"Content-Type":format==="info"?"text/html":"application/json"}});
    });
    assert.equal(r.status,200);
    if(format==="info")assert.match(r.headers.get("Content-Security-Policy"),/frame-ancestors 'none'/);
  }
});

test("timeouts and transport exceptions do not expose bearer URLs",async()=>{
  for(const name of ["TimeoutError","TypeError"]){
    const r=await deliver(request(),env,async()=>{const e=Error(url);e.name=name;throw e;});
    assert.equal(r.status,name==="TimeoutError"?504:502);assert.equal((await r.text()).includes(token),false);
  }
});

test("Workers execution-context argument is not treated as a fetch function",async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async()=>reply();
  try{const r=await worker.fetch(request(),env,{waitUntil(){}});assert.equal(r.status,200);assert.equal(await r.text(),content);}
  finally{globalThis.fetch=previous;}
});

test("platform fetch retains its global receiver",async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async function(){assert.equal(this,globalThis);return reply();};
  try{const r=await worker.fetch(request(),env,{});assert.equal(r.status,200);}
  finally{globalThis.fetch=previous;}
});


for (const timeout of ["0", "-1", "NaN", "100000", "1.5", ""]) {
  const result = await deliver(request(), {...env, UPSTREAM_TIMEOUT_MS: timeout}, () => {
    throw Error("Invalid configuration must not contact upstream");
  });
  assert.equal(result.status, 503);
}
