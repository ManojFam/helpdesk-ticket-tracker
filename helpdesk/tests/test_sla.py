from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from helpdesk import sla

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


class DueDateTests(SimpleTestCase):
    def test_each_priority_has_response_and_resolution_targets(self):
        expected = {1: (0.5, 4), 2: (1, 8), 3: (4, 24), 4: (8, 72)}
        for priority, (response_h, resolution_h) in expected.items():
            with self.subTest(priority=priority):
                response_due, resolution_due = sla.due_dates(priority, START)
                self.assertEqual(response_due, START + timedelta(hours=response_h))
                self.assertEqual(resolution_due, START + timedelta(hours=resolution_h))


class SlaStateTests(SimpleTestCase):
    due = START + timedelta(hours=8)  # an 8 hour timer

    def state(self, now_offset_h, done_offset_h=None):
        done = START + timedelta(hours=done_offset_h) if done_offset_h is not None else None
        return sla.sla_state(START, self.due, done, START + timedelta(hours=now_offset_h))

    def test_running_timer_is_on_track_until_the_last_quarter(self):
        self.assertEqual(self.state(1), sla.ON_TRACK)
        self.assertEqual(self.state(5.9), sla.ON_TRACK)

    def test_running_timer_is_at_risk_in_the_last_quarter(self):
        self.assertEqual(self.state(6), sla.AT_RISK)  # exactly 2h of 8h left
        self.assertEqual(self.state(7.99), sla.AT_RISK)

    def test_running_timer_is_breached_once_due(self):
        self.assertEqual(self.state(8), sla.BREACHED)
        self.assertEqual(self.state(30), sla.BREACHED)

    def test_finished_timer_is_met_or_breached_whatever_the_time_now(self):
        self.assertEqual(self.state(100, done_offset_h=8), sla.MET)
        self.assertEqual(self.state(100, done_offset_h=8.01), sla.BREACHED)


class TimeLeftTests(SimpleTestCase):
    def test_formats(self):
        cases = [
            (timedelta(minutes=45), "45m left"),
            (timedelta(hours=2, minutes=15), "2h 15m left"),
            (timedelta(days=1, hours=3), "1d 3h left"),
            (-timedelta(hours=1, minutes=5), "overdue by 1h 5m"),
        ]
        for delta, text in cases:
            with self.subTest(text=text):
                self.assertEqual(sla.describe_time_left(START + delta, START), text)
