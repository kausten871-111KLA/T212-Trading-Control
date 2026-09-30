"""Persistent catalyst handoff queue with deduplication, acknowledgement and daily budget."""
import json, uuid
from datetime import datetime, timezone
from pathlib import Path

class CatalystHandoffQueue:
    def __init__(self,path="/app/backend/data/catalyst_handoff_queue.jsonl",max_per_day=20):
        self.path=Path(path)
        self.max_per_day=int(max_per_day)

    def _today(self):
        return datetime.now(timezone.utc).date().isoformat()

    def _read(self):
        if not self.path.exists():
            return []
        rows=[]
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(line))
            except Exception: pass
        return rows

    def _rewrite(self,rows):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text("".join(json.dumps(r,default=str)+"\n" for r in rows),encoding="utf-8")
        tmp.replace(self.path)

    def _dedup_key(self,candidate):
        symbol=str(candidate.get("symbol") or candidate.get("t212_ticker") or "").upper()
        tier=((candidate.get("tier_state") or {}).get("current_tier"))
        return f"{self._today()}|{symbol}|{tier}"

    def enqueue(self,candidate):
        rows=self._read()
        today=self._today()
        pending_today=[r for r in rows if r.get("session_date")==today and r.get("status") in ("pending","claimed","done")]
        key=self._dedup_key(candidate)
        for r in pending_today:
            if r.get("dedup_key")==key:
                return {"queued":False,"reason":"duplicate","event":r}
        if len(pending_today) >= self.max_per_day:
            return {"queued":False,"reason":"daily_budget_reached","daily_count":len(pending_today)}
        event={
            "id":uuid.uuid4().hex,
            "queued_at":datetime.now(timezone.utc).isoformat(),
            "session_date":today,
            "status":"pending",
            "dedup_key":key,
            "candidate":candidate,
        }
        rows.append(event)
        self._rewrite(rows)
        return {"queued":True,"event":event}

    def pending(self,limit=20):
        return [r for r in self._read() if r.get("status")=="pending"][:max(1,int(limit))]

    def claim(self,event_id):
        rows=self._read()
        changed=None
        for r in rows:
            if r.get("id")==event_id and r.get("status")=="pending":
                r["status"]="claimed"
                r["claimed_at"]=datetime.now(timezone.utc).isoformat()
                changed=r
                break
        if changed: self._rewrite(rows)
        return changed

    def acknowledge(self,event_id,outcome="done",result=None):
        rows=self._read()
        changed=None
        for r in rows:
            if r.get("id")==event_id:
                r["status"]=outcome
                r["completed_at"]=datetime.now(timezone.utc).isoformat()
                if result is not None: r["result"]=result
                changed=r
                break
        if changed: self._rewrite(rows)
        return changed

    def stats(self):
        rows=self._read()
        today=self._today()
        today_rows=[r for r in rows if r.get("session_date")==today]
        return {
            "session_date":today,
            "daily_budget":self.max_per_day,
            "today_count":len(today_rows),
            "pending":sum(r.get("status")=="pending" for r in today_rows),
            "claimed":sum(r.get("status")=="claimed" for r in today_rows),
            "done":sum(r.get("status")=="done" for r in today_rows),
        }
