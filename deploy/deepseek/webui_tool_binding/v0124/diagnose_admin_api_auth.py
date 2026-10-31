#!/usr/bin/env python3
"""Non-mutating WebUI API auth diagnostics. Prints NO token, body, user or secrets."""
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
value = os.environ.get("OPENWEBUI_ADMIN_API_KEY", "").strip()
kind = ("missing" if not value else "sk_api_key" if value.startswith("sk-")
        else "jwt_format" if value.count(".") == 2 else "other")
print("WEBUI_AUTH_KEY_TYPE", kind, flush=True)
urls = [
    "/health",
    "/api/v1/tools/",
    "/api/v1/models/",
    "/api/v1/models/model?id=trading-operations--deepseek",
    "/api/v1/tools/id/market_data_gateway",
    "/api/v1/auths/",
]
for path in urls:
    headers = {"Accept": "application/json"}
    if value:
        headers["Authorization"] = "Bearer " + value
    request = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as res:
            status = res.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError:
        status = "unavailable"
    print("WEBUI_AUTH_ROUTE", path.split("?")[0], status, flush=True)
print("WEBUI_AUTH_PROBE_DONE no_auth_changes no_api_writes", flush=True)
