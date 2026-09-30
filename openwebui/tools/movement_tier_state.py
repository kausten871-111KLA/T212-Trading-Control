"""Movement tier state for deterministic discovery."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

class MovementTierState:
    def __init__(self, path="/app/backend/data/trading_movement_tiers.json", tiers=None):
        self.path=Path(path)
        self.tiers=tiers or [5.0,10.0,20.0,50.0,100.0]

    def _today(self):
        return datetime.now(timezone.utc).date().isoformat()

    def _load(self):
        if not self.path.exists():
            return {"session_date":self._today(),"symbols":{}}
        try:
            payload=json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"session_date":self._today(),"symbols":{}}
        if payload.get("session_date") != self._today():
            return {"session_date":self._today(),"symbols":{}}
        payload.setdefault("symbols",{})
        return payload

    def _save(self,payload):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
        tmp.replace(self.path)

    def tier_for_change(self,change_pct):
        reached=0.0
        for tier in self.tiers:
            if float(change_pct) >= tier:
                reached=tier
        return reached

    def update(self,symbol,change_pct):
        symbol=(symbol or "").upper().strip()
        if not symbol:
            return {"error":"empty symbol"}
        state=self._load()
        previous=state["symbols"].get(symbol) or {}
        previous_tier=float(previous.get("tier",0.0) or 0.0)
        current_tier=self.tier_for_change(float(change_pct))
        escalated=current_tier>previous_tier
        state["symbols"][symbol]={
            "tier":current_tier,
            "last_change_pct":float(change_pct),
            "updated_at":datetime.now(timezone.utc).isoformat(),
        }
        self._save(state)
        return {
            "symbol":symbol,
            "session_date":state["session_date"],
            "previous_tier":previous_tier,
            "current_tier":current_tier,
            "escalated":escalated,
            "newly_qualified":previous_tier==0.0 and current_tier>0.0,
        }

    def reset(self):
        payload={"session_date":self._today(),"symbols":{}}
        self._save(payload)
        return payload
