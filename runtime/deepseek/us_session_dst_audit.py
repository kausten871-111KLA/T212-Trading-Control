"""NY-session to UK local time alignment, without changing any automation.

US and UK daylight-saving transitions differ for some weeks. This helper
computes UK clock targets from fixed America/New_York phase times. It does
NOT decide if an exchange is trading, check holidays or dispatch broker jobs.
"""
from datetime import date,datetime,time
from zoneinfo import ZoneInfo

UK=ZoneInfo("Europe/London")
NY=ZoneInfo("America/New_York")
# Derived from the established weekday UK schedule on a normal Oct 2026 day.
# These are schedule-time targets, not trade/order rules.
PHASES_NY={
    "US OPEN":time(9,35),
    "US MIDDAY":time(12,30),
    "US CLOSE":time(15,35),
    "US CONTROLLER":time(9,0),
    "Morning Research Runner":time(8,0),
}

def uk_target(day:date,phase:str)->datetime:
    if not isinstance(day,date) or isinstance(day,datetime):
        raise ValueError("calendar date required")
    if day.weekday()>=5:raise ValueError("no ordinary weekday session target")
    if phase not in PHASES_NY:raise ValueError("unknown phase")
    local_ny=datetime.combine(day,PHASES_NY[phase],NY)
    return local_ny.astimezone(UK)

def drift_minutes(day:date,phase:str,scheduled_hour:int,scheduled_minute:int)->int:
    """Positive means scheduled UK clock time is later than intended NY phase."""
    if not (type(scheduled_hour)==int and 0<=scheduled_hour<=23 and
            type(scheduled_minute)==int and 0<=scheduled_minute<=59):
        raise ValueError("invalid UK clock time")
    expected=uk_target(day,phase)
    scheduled=datetime.combine(day,time(scheduled_hour,scheduled_minute),UK)
    return int((scheduled-expected).total_seconds()//60)
