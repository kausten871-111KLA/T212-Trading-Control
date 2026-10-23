"""Reversible DST-week schedule plan for the five EXISTING WebUI trading jobs.

Report-only. Does not write WebUI SQLite, API, systemd or add jobs.
On 26-30 October 2026, Britain is on GMT while New York is still EDT.
The US market open is 13:30 GMT; existing UK-local clock schedules drift
one hour late. Return to ordinary UK clocks on Monday 2 November.
"""
from __future__ import annotations
from datetime import date,datetime
import json
import re
from .us_session_dst_audit import uk_target

PHASE_FOR_NAME = {
    "US OPEN — Trading Operations (DEMO)": "US OPEN",
    "US MIDDAY — Trading Operations (DEMO, monitor+rescan)": "US MIDDAY",
    "US CLOSE — Trading Operations (DEMO)": "US CLOSE",
    "Morning Research Runner  (US)- Light DS Trading Operations": "Morning Research Runner",
    "US CONTROLLER — decide & authorise": "US CONTROLLER",
}
RRULE_RE = re.compile(r"(?:^|;)BYHOUR=(\d{1,2});BYMINUTE=(\d{1,2})(?:;|$)")


def prepare_dst_plan(automations, day=date(2026,10,26)):
    """A diff/rollback manifest requiring independent host validation.

    The host must apply changes through a supported authenticated WebUI API,
    refresh scheduler state, independently test the next-run time, and retain
    original rules. Do NOT update SQLite schedules or next_run_at manually.
    """
    if not isinstance(day,date) or isinstance(day,datetime) or not date(2026,10,26)<=day<=date(2026,10,30):
        raise ValueError("Plan limited to 26-30 Oct 2026 trading week")
    mapping={}
    for row in automations:
        name=row.get("name")
        if name not in PHASE_FOR_NAME:
            continue
        if name in mapping:
            raise ValueError("Duplicate trading automation")
        if row.get("is_active") not in (True,1):
            raise ValueError("Existing trading job inactive")
        data=row.get("data")
        if isinstance(data,str):
            data=json.loads(data)
        if not isinstance(data,dict) or data.get("model_id")!="trading-operations--deepseek":
            raise ValueError("Incorrect existing DeepSeek model ID")
        old=data.get("rrule")
        if not isinstance(old,str):
            raise ValueError("Missing schedule")
        match=RRULE_RE.search(old)
        if not match:
            raise ValueError("Unsupported rule; manual review required")
        original_h,original_m=map(int,match.groups())
        phase=PHASE_FOR_NAME[name]
        target=uk_target(day,phase)
        if (original_h,original_m) != (target.hour+1,target.minute):
            raise ValueError("Rule differs from expected established UK schedule")
        new=old[:match.start(1)]+str(target.hour)+old[match.end(1):]
        # Existing minute is unchanged for this DST correction.
        mapping[name]={
            "automation_id":row.get("id"),"name":name,
            "model_id":"trading-operations--deepseek",
            "original_rrule":old,"proposed_rrule":new,
            "target_local_uk":target.isoformat(),
            "restore_not_before":"2026-11-01T00:00:00+00:00",
        }
    if set(mapping)!=set(PHASE_FOR_NAME):
        raise ValueError("Expected exactly five existing trading automations")
    ids=[x["automation_id"] for x in mapping.values()]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=5:
        raise ValueError("Missing or duplicate automation IDs")
    return [mapping[n] for n in PHASE_FOR_NAME]
