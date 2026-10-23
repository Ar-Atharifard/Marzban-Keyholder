// Forward subscription downloads without storing or logging bearer URLs.
const TOKEN_PATH = /^\/s\/[A-Za-z0-9_-]{43}$/;
const FORMATS = new Set(["uri", "xray", "info"]);
const RESPONSE_HEADERS = [
  "content-type", "content-length", "subscription-userinfo", "profile-title",
  "profile-update-interval", "support-url", "retry-after",
];

function failure(status, message, head = false) {
  return new Response(head ? null : JSON.stringify({ detail: message }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Robots-Tag": "noindex, nofollow, nosnippet",
    },
  });
}

export async function deliver(request, env, fetcher = (...args) => globalThis.fetch(...args)) {
  const head = request.method === "HEAD";
  if (request.method !== "GET" && !head) {
    const response = failure(405, "Method not allowed");
    response.headers.set("Allow", "GET, HEAD");
    return response;
  }
  const incoming = new URL(request.url);
  if (!TOKEN_PATH.test(incoming.pathname)) return failure(404, "Subscription not found", head);
  const formats = incoming.searchParams.getAll("format");
  if (formats.length > 1 || (formats.length && !FORMATS.has(formats[0]))) {
    return failure(422, "Invalid request", head);
  }

  let origin;
  let timeout;
  try {
    timeout = Number(env.UPSTREAM_TIMEOUT_MS ?? 10000);
    if (!Number.isInteger(timeout) || timeout < 100 || timeout > 60000) {
      throw new Error("Invalid timeout");
    }
    origin = new URL(env.UPSTREAM_ORIGIN);
    if (origin.protocol !== "https:" || origin.username || origin.password ||
        origin.port || origin.pathname !== "/" || origin.search || origin.hash ||
        origin.hostname.endsWith(".invalid")) throw new Error("Invalid origin");
  } catch {
    return failure(503, "Delivery configuration unavailable", head);
  }
  const target = new URL(incoming.pathname, origin);
  if (formats.length) target.searchParams.set("format", formats[0]);
  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of ["user-agent", "accept", "accept-encoding"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    // GET also supports HEAD against older Keyholder versions lacking HEAD routes.
    // Do not forward cookies, Authorization, caller Host or client-supplied URLs.
    const upstream = await fetcher(target.toString(), {
      method: "GET", headers, redirect: "manual", cache: "no-store",
      signal: AbortSignal.timeout(timeout),
      // workerd rejects any cacheTtl override combined with cache: no-store.
      cf: { cacheEverything: false },
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      await upstream.body?.cancel();
      return failure(502, "Unexpected upstream redirect", head);
    }
    const type = (upstream.headers.get("content-type") || "").split(";", 1)[0].trim();
    const permitted = formats[0] === "info"
      ? new Set(["text/html", "application/json"])
      : new Set(["text/plain", "application/json"]);
    if (!permitted.has(type)) {
      await upstream.body?.cancel();
      return failure(upstream.ok ? 502 : upstream.status, "Subscription delivery unavailable", head);
    }
    const resultHeaders = new Headers();
    for (const name of RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    // Stream the bytes unchanged, including any upstream content encoding.
    const encoding = upstream.headers.get("content-encoding");
    if (encoding) resultHeaders.set("content-encoding", encoding);
    resultHeaders.set("Cache-Control", "private, no-store");
    resultHeaders.set("Referrer-Policy", "no-referrer");
    resultHeaders.set("X-Content-Type-Options", "nosniff");
    resultHeaders.set("X-Robots-Tag", "noindex, nofollow, nosnippet");
    resultHeaders.set("Vary", "User-Agent, Accept-Encoding");
    if (formats[0] === "info") resultHeaders.set("Content-Security-Policy",
      "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
    if (head) await upstream.body?.cancel();
    return new Response(head ? null : upstream.body, { status: upstream.status, headers: resultHeaders });
  } catch (error) {
    // Exception strings can contain the bearer URL. Never log or return them.
    const timeout = error?.name === "TimeoutError" || error?.name === "AbortError";
    return failure(timeout ? 504 : 502, "Subscription delivery unavailable", head);
  }
}

export default { fetch(request, env) { return deliver(request, env); } };
