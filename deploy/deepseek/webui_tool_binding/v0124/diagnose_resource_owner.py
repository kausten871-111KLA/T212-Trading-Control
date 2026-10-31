#!/usr/bin/env python3
"""Strict non-mutating, no-identity WebUI principal/resource check."""
import asyncio
import os
import sqlite3
from open_webui.models.users import Users

async def main():
    key = os.environ.get("OPENWEBUI_ADMIN_API_KEY", "").strip()
    if not key.startswith("sk-"):
        print("RESOURCE_ACCESS_PROBE_BLOCKED key_not_api_format")
        return
    user = await Users.get_user_by_api_key(key)
    if user is None:
        print("RESOURCE_ACCESS_PROBE_BLOCKED principal_not_found")
        return
    db=sqlite3.connect("file:/app/backend/data/webui.db?mode=ro",uri=True)
    try:
        model=db.execute("select user_id from model where id=?",("trading-operations--deepseek",)).fetchone()
        tool=db.execute("select user_id from tool where id=?",("market_data_gateway",)).fetchone()
    finally:
        db.close()
    print("WEBUI_AUTH_PRINCIPAL_ROLE", user.role)
    print("WEBUI_AUTH_OWNS_MODEL",bool(model and user.id==model[0]))
    print("WEBUI_AUTH_OWNS_MARKET_TOOL",bool(tool and user.id==tool[0]))
    print("WEBUI_MODEL_AND_TOOL_SAME_OWNER",bool(model and tool and model[0]==tool[0]))
    print("WEBUI_AUTH_RESOURCE_PROBE_PASS identity_not_displayed",flush=True)
asyncio.run(main())
