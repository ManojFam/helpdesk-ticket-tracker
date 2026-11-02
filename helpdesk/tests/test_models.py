from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from helpdesk import sla
from helpdesk.models import Ticket
from helpdesk.tests.helpers import make_ticket, make_user


class TicketSlaTests(TestCase):
    def setUp(self):
        self.requester = make_user("sam")
        self.agent = make_user("jordan", staff=True)

    def test_due_dates_are_set_from_priority_on_create(self):
        created = timezone.now() - timedelta(hours=1)
        ticket = make_ticket(self.requester, priority=Ticket.Priority.CRITICAL, created_at=created)

        self.assertEqual(ticket.response_due_at, created + timedelta(minutes=30))
        self.assertEqual(ticket.resolution_due_at, created + timedelta(hours=4))

    def test_changing_priority_moves_the_deadlines_from_creation_time(self):
        ticket = make_ticket(self.requester, priority=Ticket.Priority.LOW)
        ticket.priority = Ticket.Priority.HIGH
        ticket.save()

        self.assertEqual(ticket.resolution_due_at, ticket.created_at + timedelta(hours=8))

    def test_resolving_records_the_time_and_reopening_clears_it(self):
        ticket = make_ticket(self.requester)
        ticket.status = Ticket.Status.RESOLVED
        ticket.save()
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.resolution_sla(), sla.MET)

        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()
        self.assertIsNone(ticket.resolved_at)

    def test_closing_a_resolved_ticket_keeps_the_original_resolved_time(self):
        ticket = make_ticket(self.requester, status=Ticket.Status.RESOLVED)
        resolved_at = ticket.resolved_at
        ticket.status = Ticket.Status.CLOSED
        ticket.save()
        self.assertEqual(ticket.resolved_at, resolved_at)

    def test_open_ticket_past_due_is_breached(self):
        ticket = make_ticket(
            self.requester,
            priority=Ticket.Priority.CRITICAL,
            created_at=timezone.now() - timedelta(hours=5),
        )
        self.assertEqual(ticket.resolution_sla(), sla.BREACHED)


class FirstResponseTests(TestCase):
    def setUp(self):
        self.requester = make_user("sam")
        self.agent = make_user("jordan", staff=True)
        self.ticket = make_ticket(self.requester)

    def test_public_reply_from_it_staff_stops_the_response_clock(self):
        comment = self.ticket.add_comment(self.agent, "Looking into it.")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_response_at, comment.created_at)
        self.assertEqual(self.ticket.response_sla(), sla.MET)

    def test_requester_comment_does_not_count(self):
        self.ticket.add_comment(self.requester, "Any update?")
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_response_at)

    def test_internal_note_does_not_count(self):
        self.ticket.add_comment(self.agent, "Probably the fuser.", internal=True)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_response_at)

    def test_staff_member_commenting_on_their_own_ticket_does_not_count(self):
        own = make_ticket(self.agent)
        own.add_comment(self.agent, "Adding more detail.")
        own.refresh_from_db()
        self.assertIsNone(own.first_response_at)

    def test_later_replies_do_not_move_the_first_response_time(self):
        first = self.ticket.add_comment(self.agent, "On it.")
        self.ticket.add_comment(self.agent, "Fixed?", at=timezone.now() + timedelta(hours=1))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_response_at, first.created_at)


class QuerySetTests(TestCase):
    def test_open_and_visible_to(self):
        sam, casey, agent = make_user("sam"), make_user("casey"), make_user("jordan", staff=True)
        mine = make_ticket(sam)
        make_ticket(sam, status=Ticket.Status.CLOSED)
        theirs = make_ticket(casey)

        self.assertEqual(list(Ticket.objects.visible_to(sam).open()), [mine])
        self.assertCountEqual(Ticket.objects.visible_to(agent).open(), [mine, theirs])
