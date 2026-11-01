import unittest
from datetime import date
from runtime.deepseek.us_session_dst_audit import uk_target,drift_minutes

class TradingDSTAudit(unittest.TestCase):
    def test_last_friday_bst_open_unchanged(self):
        self.assertEqual(uk_target(date(2026,10,23),"US OPEN").strftime("%H:%M"),"14:35")
        self.assertEqual(drift_minutes(date(2026,10,23),"US OPEN",14,35),0)
    def test_gap_week_open_one_hour_late(self):
        for day in (date(2026,10,26),date(2026,10,30)):
            self.assertEqual(uk_target(day,"US OPEN").strftime("%H:%M"),"13:35")
            self.assertEqual(drift_minutes(day,"US OPEN",14,35),60)
    def test_gap_week_midday(self):
        self.assertEqual(uk_target(date(2026,10,26),"US MIDDAY").strftime("%H:%M"),"16:30")
        self.assertEqual(drift_minutes(date(2026,10,26),"US MIDDAY",17,30),60)
    def test_gap_week_close(self):
        self.assertEqual(uk_target(date(2026,10,26),"US CLOSE").strftime("%H:%M"),"19:35")
        self.assertEqual(drift_minutes(date(2026,10,26),"US CLOSE",20,35),60)
    def test_gap_week_new_controller(self):
        self.assertEqual(uk_target(date(2026,10,26),"US CONTROLLER").strftime("%H:%M"),"13:00")
        self.assertEqual(drift_minutes(date(2026,10,26),"US CONTROLLER",14,0),60)
    def test_gap_week_morning_research(self):
        self.assertEqual(uk_target(date(2026,10,26),"Morning Research Runner").strftime("%H:%M"),"12:00")
        self.assertEqual(drift_minutes(date(2026,10,26),"Morning Research Runner",13,0),60)
    def test_us_standard_time_resynchronises_in_november(self):
        self.assertEqual(uk_target(date(2026,11,2),"US OPEN").strftime("%H:%M"),"14:35")
        self.assertEqual(drift_minutes(date(2026,11,2),"US OPEN",14,35),0)
    def test_weekend_cannot_be_scheduled_as_normal_market_open(self):
        with self.assertRaises(ValueError):uk_target(date(2026,10,25),"US OPEN")
    def test_invalid_phase_rejected(self):
        with self.assertRaises(ValueError):uk_target(date(2026,10,26),"UNKNOWN")
    def test_invalid_scheduled_clock_rejected(self):
        with self.assertRaises(ValueError):drift_minutes(date(2026,10,26),"US OPEN",25,0)
if __name__=="__main__":unittest.main()
