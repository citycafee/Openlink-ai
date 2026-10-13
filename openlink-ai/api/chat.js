// Vercel serverless function: /api/chat
//
// Keeps the AI provider keys as secret Vercel environment variables and adds
// the Authorization header server-side, so the key NEVER reaches the browser.
//
//   GET  -> { ok: true, providers: ["openrouter", ...] }  (which keys exist)
//   POST -> { provider, model, messages, stream, extra_headers }
//           Forwards to <base_url>/chat/completions and streams the OpenAI
//           SSE back to the browser unchanged.
//
// The PROVIDERS env var is a single-line JSON object:
//   { "openrouter": { "base_url": "...", "key": "..." }, ... }

function loadProviders() {
  var raw = process.env.PROVIDERS || "";
  try {
    var obj = JSON.parse(raw);
    return obj && typeof obj === "object" ? obj : {};
  } catch (e) {
    return {};
  }
}

function readBody(req) {
  // Vercel normally auto-parses JSON into req.body; fall back to reading the stream.
  if (req.body !== undefined && req.body !== null) {
    var b = req.body;
    if (typeof b === "string") { try { b = JSON.parse(b); } catch (e) { b = {}; } }
    else if (Buffer.isBuffer(b)) { try { b = JSON.parse(b.toString("utf8")); } catch (e) { b = {}; } }
    return Promise.resolve(b && typeof b === "object" ? b : {});
  }
  return new Promise(function (resolve) {
    var chunks = [];
    req.on("data", function (c) { chunks.push(c); });
    req.on("end", function () {
      var raw = Buffer.concat(chunks).toString("utf8");
      try { resolve(JSON.parse(raw || "{}")); } catch (e) { resolve({}); }
    });
    req.on("error", function () { resolve({}); });
  });
}

function sendJson(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

module.exports = async function handler(req, res) {
  // Same-origin in production, but allow CORS anyway (harmless + useful in dev).
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");

  if (req.method === "OPTIONS") { res.statusCode = 204; res.end(); return; }

  var providers = loadProviders();

  if (req.method === "GET") {
    sendJson(res, 200, { ok: true, providers: Object.keys(providers) });
    return;
  }

  if (req.method !== "POST") {
    sendJson(res, 405, { error: "method not allowed" });
    return;
  }

  var body = await readBody(req);
  var id = String(body.provider || "").trim();
  var entry = providers[id];
  if (!entry || !entry.key) {
    sendJson(res, 401, { error: "No server key configured for provider '" + id + "'." });
    return;
  }
  var base = String(entry.base_url || "").replace(/\/+$/, "");
  if (!/^https?:\/\//.test(base)) {
    sendJson(res, 400, { error: "Bad base_url for provider '" + id + "'." });
    return;
  }

  var payload = {
    model: body.model,
    messages: Array.isArray(body.messages) ? body.messages : [],
    stream: body.stream !== false
  };

  var headers = { "Content-Type": "application/json", "Authorization": "Bearer " + entry.key };
  var extra = body.extra_headers && typeof body.extra_headers === "object" ? body.extra_headers : {};
  Object.keys(extra).forEach(function (k) { headers[k] = extra[k]; });

  var up;
  try {
    up = await fetch(base + "/chat/completions", {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payload)
    });
  } catch (e) {
    sendJson(res, 502, { error: "Upstream request failed: " + ((e && e.message) || e) });
    return;
  }

  // Surface provider errors (bad key, quota, etc.) verbatim.
  if (!up.ok) {
    var txt = "";
    try { txt = await up.text(); } catch (e) {}
    res.statusCode = up.status;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(txt || JSON.stringify({ error: "HTTP " + up.status }));
    return;
  }

  if (!payload.stream) {
    var out = "";
    try { out = await up.text(); } catch (e) {}
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(out);
    return;
  }

  // Stream the provider's OpenAI SSE straight through to the browser.
  res.statusCode = 200;
  res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");

  if (!up.body) { res.end(); return; }
  var reader = up.body.getReader();
  try {
    for (;;) {
      var r = await reader.read();
      if (r.done) break;
      if (r.value) res.write(Buffer.from(r.value));
    }
  } catch (e) {
    // Client disconnected or upstream ended mid-stream.
  }
  res.end();
};
