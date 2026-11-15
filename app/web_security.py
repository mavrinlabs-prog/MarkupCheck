"""Security headers and a per-visitor rate limit for the Gradio server, following AdmitPath's
next.config.js, proxy.ts and lib/rate-limit.ts.

Written as plain ASGI middleware: Starlette's BaseHTTPMiddleware buffers responses, which breaks the
server-sent events Gradio streams results over.
"""

import collections
import json
import os
import time

# The Space page on huggingface.co shows the app in an iframe, so framing is allowed from there only
# (AdmitPath sends X-Frame-Options: DENY, which would blank the Space).
_CSP = "; ".join([
    "default-src 'self'",
    # 'unsafe-eval': Gradio 6's HTML component compiles its templates with new Function(), so without it
    # the header and the result panel never render. AdmitPath allows it only in development.
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self' https://huggingface.co",  # Gradio looks up its Space there when framed on huggingface.co
    "frame-src 'none'",
    "frame-ancestors 'self' https://huggingface.co https://*.huggingface.co",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
] + (["upgrade-insecure-requests"] if os.environ.get("SPACE_ID") else []))  # SPACE_ID is set on Hugging Face

HEADERS = [(k.lower().encode(), v.encode()) for k, v in [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    # AdmitPath also lists interest-cohort; Chrome logs a console error for that retired feature.
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), browsing-topics=(), payment=()"),
    ("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"),
    ("X-DNS-Prefetch-Control", "on"),
    ("X-Permitted-Cross-Domain-Policies", "none"),
    ("X-XSS-Protection", "0"),
    ("Content-Security-Policy", _CSP),
]]
_OURS = {k for k, _ in HEADERS} | {b"cache-control", b"x-robots-tag"}

# MC_RATE_LIMIT lets the local browser-test run (many checks a minute from one address) raise the limit.
LIMIT, WINDOW_S, MAX_KEYS, SWEEP_S = int(os.environ.get("MC_RATE_LIMIT", "30")), 60.0, 50_000, 60.0


class RateLimiter:
    """Sliding window per client IP, bounded to MAX_KEYS entries (oldest evicted first)."""

    def __init__(self, limit=LIMIT, window_s=WINDOW_S, max_keys=MAX_KEYS, clock=time.monotonic):
        self.limit, self.window_s, self.max_keys, self.clock = limit, window_s, max_keys, clock
        self.hits = collections.OrderedDict()
        self.last_sweep = clock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        if now - self.last_sweep > SWEEP_S:
            for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window_s]:
                del self.hits[k]
            self.last_sweep = now
        q = self.hits.get(key)
        if q is None:
            if len(self.hits) >= self.max_keys:
                self.hits.popitem(last=False)
            q = self.hits[key] = collections.deque()
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def client_ip(scope) -> str:
    headers = dict(scope.get("headers") or [])
    forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
    if forwarded:
        return forwarded
    real = headers.get(b"x-real-ip", b"").decode("latin-1").strip()
    if real:
        return real
    return (scope.get("client") or ("unknown",))[0]


class SecurityHeaders:
    """Adds the headers above to every response and limits queue joins (one per check) per client IP."""

    def __init__(self, app, limiter=None):
        self.app = app
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        extra = list(HEADERS)
        if path.startswith("/mc-fonts/"):
            extra.append((b"cache-control", b"public, max-age=31536000, immutable"))
        if "/gradio_api/" in path:
            extra.append((b"x-robots-tag", b"noindex, nofollow"))

        # One queue join per check in the page; API clients POST to /gradio_api/call/<name>, /run/ or /api/.
        # The client address is the first X-Forwarded-For entry (as AdmitPath does). A client can forge it; the
        # right-most entry can't be forged, but behind two proxies it is the proxy's own address and would put
        # every visitor in one bucket, so keep this until the Space's real header has been checked.
        is_check = path.endswith("/queue/join") or any(f"/gradio_api/{r}/" in path for r in ("call", "run", "api"))
        if scope.get("method") == "POST" and is_check and not self.limiter.allow(client_ip(scope)):
            body = json.dumps({"error": "Too many checks from this connection. Wait a minute, then try again.",
                               "retryable": True}).encode()
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60"),
                                    (b"cache-control", b"no-store"), *HEADERS]})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _OURS]
                message = {**message, "headers": kept + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)
