"""Authenticated WebUI v0.12.3 automation update/rollback transport.

The actual deployed WebUI routes were inspected on Contabo 23 Oct 2026:
GET /api/v1/automations/{id}; POST /api/v1/automations/{id}/update.
The API uses AutomationForm {name,folder_id,data,meta,is_active}; data
requires {prompt,model_id,rrule}, optional terminal/target. Never write
WebUI SQLite schedules. This module does nothing until explicitly called
with an authorized user's bearer token and a pre-validated five-job plan.
"""
from datetime import datetime, timezone
import json
from urllib.request import Request, urlopen
from .webui_dst_migration import PHASE_FOR_NAME

FIELDS=("name","folder_id","data","meta","is_active")


class WebUIAutomationAPI:
    def __init__(self, *, base_url, bearer_token, transport=None):
        if not isinstance(base_url,str) or not base_url.startswith(("https://","http://127.0.0.1:","http://localhost:")):
            raise ValueError("HTTPS or local-loopback WebUI base URL required")
        if not isinstance(bearer_token,str) or not bearer_token.strip():
            raise ValueError("Authenticated WebUI user token required")
        self.base_url=base_url.rstrip("/")
        self.token=bearer_token
        self.transport=transport or urlopen

    def request(self, method, path, body=None):
        if method not in ("GET","POST") or not path.startswith("/api/v1/automations/"):
            raise ValueError("Unexpected WebUI automation route")
        payload=None if body is None else json.dumps(body,sort_keys=True).encode()
        req=Request(self.base_url+path,data=payload,method=method,
                    headers={"Authorization":"Bearer "+self.token,
                             "Content-Type":"application/json"})
        # Exceptions are allowed to propagate; caller logs type only, not token.
        with self.transport(req,timeout=15) as response:
            return json.loads(response.read())

    def get(self,automation_id):
        return self.request("GET","/api/v1/automations/"+automation_id)

    def update(self,automation_id,form):
        if set(form)!=set(FIELDS):
            raise ValueError("Exact AutomationForm fields required")
        return self.request("POST","/api/v1/automations/"+automation_id+"/update",form)


def form_of(row):
    if not isinstance(row,dict) or not all(k in row for k in FIELDS):
        raise ValueError("Incomplete WebUI automation response")
    data=row["data"]
    if not isinstance(data,dict) or not {"prompt","model_id","rrule"}<=set(data):
        raise ValueError("Incomplete automation data")
    return {k:row[k] for k in FIELDS}


def apply_five_job_plan(api, plan, *, restore=False):
    """Validate all five remote jobs before any update; rollback partial writes.

    Returns a change report; raises on verification or rollback failure.
    Use only in a controlled post-Friday-market cutover with authenticated
    WebUI user token, backed-up manifest and an approved restore window.
    """
    if len(plan)!=5 or {p["name"] for p in plan}!=set(PHASE_FOR_NAME):
        raise ValueError("Expected the five established trading automations")
    if len({p["automation_id"] for p in plan})!=5:
        raise ValueError("Duplicate automation IDs")
    current={}
    before={}
    expected_key="proposed_rrule" if restore else "original_rrule"
    desired_key="original_rrule" if restore else "proposed_rrule"
    for p in plan:
        aid=p["automation_id"]
        row=api.get(aid)
        if row.get("id")!=aid or row.get("name")!=p["name"] or row.get("is_active") is not True:
            raise RuntimeError("Existing WebUI automation identity/active mismatch")
        form=form_of(row)
        if form["data"]["model_id"]!="trading-operations--deepseek":
            raise RuntimeError("Model mismatch")
        if form["data"]["rrule"]!=p[expected_key]:
            raise RuntimeError("Existing schedule differs from approved manifest")
        current[aid]=row
        before[aid]=form
    changed=[]
    try:
        for p in plan:
            aid=p["automation_id"]
            new_form={**before[aid],"data":{**before[aid]["data"],"rrule":p[desired_key]}}
            response=api.update(aid,new_form)
            if (response.get("id")!=aid or
                response.get("data",{}).get("rrule")!=p[desired_key] or
                response.get("is_active") is not True):
                # This update may have persisted despite a bad response.
                changed.append(aid)
                raise RuntimeError("WebUI update acceptance mismatch")
            changed.append(aid)
            observed=api.get(aid)
            if observed.get("data",{}).get("rrule")!=p[desired_key]:
                raise RuntimeError("WebUI persisted RRULE mismatch")
        return {"ok":True,"restored":restore,"updated_ids":changed}
    except Exception as error:
        rollback_errors=[]
        for aid in reversed(changed):
            try:
                api.update(aid,before[aid])
                observed=api.get(aid)
                if observed.get("data",{}).get("rrule")!=before[aid]["data"]["rrule"]:
                    raise RuntimeError("Rollback verification failed")
            except Exception as rollback_error:
                rollback_errors.append((aid,type(rollback_error).__name__))
        if rollback_errors:
            raise RuntimeError("Partial automation rollback failed; manual recovery required") from error
        raise RuntimeError("WebUI schedule change rejected and rolled back") from error
