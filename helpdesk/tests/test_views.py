from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from helpdesk.accounts import trust_email
from helpdesk.models import Article, Ticket
from helpdesk.tests.helpers import PASSWORD, make_category, make_ticket, make_user


class AccessTests(TestCase):
    def setUp(self):
        self.sam = make_user("sam")
        self.casey = make_user("casey")
        self.agent = make_user("jordan", staff=True)
        self.ticket = make_ticket(self.sam)

    def test_anonymous_users_are_sent_to_login(self):
        for name, args in [
            ("portal", []),
            ("ticket_list", []),
            ("ticket_detail", [self.ticket.pk]),
            ("dashboard", []),
            ("article_list", []),
        ]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertRedirects(
                    response, f"{reverse('account_login')}?next={reverse(name, args=args)}"
                )

    def test_home_sends_staff_to_dashboard_and_requesters_to_their_tickets(self):
        self.client.force_login(self.agent)
        self.assertRedirects(self.client.get(reverse("portal")), reverse("dashboard"))
        self.client.force_login(self.sam)
        self.assertRedirects(self.client.get(reverse("portal")), reverse("ticket_list"))

    def test_requesters_cannot_open_the_dashboard(self):
        self.client.force_login(self.sam)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_requesters_get_404_for_other_peoples_tickets(self):
        self.client.force_login(self.casey)
        url = reverse("ticket_detail", args=[self.ticket.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_requesters_cannot_comment_on_other_peoples_tickets(self):
        self.client.force_login(self.casey)
        url = reverse("ticket_comment", args=[self.ticket.pk])
        self.assertEqual(self.client.post(url, {"body": "Hi"}).status_code, 404)
        self.assertFalse(self.ticket.comments.exists())

    def test_requesters_cannot_update_tickets(self):
        self.client.force_login(self.sam)
        url = reverse("ticket_update", args=[self.ticket.pk])
        response = self.client.post(url, {"status": "closed", "priority": 1})
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.NEW)

    def test_login_page_works(self):
        self.sam.email = "sam@example.com"
        self.sam.save()
        trust_email(self.sam)  # login needs a verified address (see helpdesk/accounts.py)
        response = self.client.post(
            reverse("account_login"), {"login": "sam", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("portal"), fetch_redirect_response=False)


class TicketFlowTests(TestCase):
    def setUp(self):
        self.sam = make_user("sam")
        self.agent = make_user("jordan", staff=True, first_name="Jordan", last_name="Lee")
        self.category = make_category()

    def test_raising_a_ticket_sets_the_requester_and_sla(self):
        self.client.force_login(self.sam)
        response = self.client.post(
            reverse("ticket_create"),
            {
                "title": "Printer jammed",
                "category": self.category.pk,
                "priority": Ticket.Priority.HIGH,
                "description": "Paper jam on level 2.",
            },
        )
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertEqual(ticket.requester, self.sam)
        self.assertEqual(ticket.resolution_due_at, ticket.created_at + timedelta(hours=8))

    def test_requester_cannot_choose_the_requester_or_status(self):
        self.client.force_login(self.sam)
        self.client.post(
            reverse("ticket_create"),
            {
                "title": "Hack",
                "priority": 3,
                "description": "x",
                "requester": self.agent.pk,
                "status": "closed",
            },
        )
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.requester, self.sam)
        self.assertEqual(ticket.status, Ticket.Status.NEW)

    def test_staff_can_assign_and_resolve(self):
        ticket = make_ticket(self.sam)
        self.client.force_login(self.agent)
        self.client.post(
            reverse("ticket_update", args=[ticket.pk]),
            {
                "status": "resolved",
                "priority": 3,
                "assignee": self.agent.pk,
                "category": "",
            },
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)
        self.assertEqual(ticket.assignee, self.agent)
        self.assertIsNotNone(ticket.resolved_at)

    def test_internal_notes_are_hidden_from_the_requester(self):
        ticket = make_ticket(self.sam)
        ticket.add_comment(self.agent, "Public reply")
        ticket.add_comment(self.agent, "Secret internal note", internal=True)

        self.client.force_login(self.sam)
        page = self.client.get(ticket.get_absolute_url()).content.decode()
        self.assertIn("Public reply", page)
        self.assertNotIn("Secret internal note", page)
        self.assertNotIn("Internal note (TechCare staff only)", page)  # no checkbox either

        self.client.force_login(self.agent)
        self.assertContains(self.client.get(ticket.get_absolute_url()), "Secret internal note")

    def test_requester_cannot_post_an_internal_note(self):
        ticket = make_ticket(self.sam)
        self.client.force_login(self.sam)
        self.client.post(
            reverse("ticket_comment", args=[ticket.pk]), {"body": "Hello", "is_internal": "on"}
        )
        self.assertFalse(ticket.comments.get().is_internal)

    def test_requester_reply_moves_a_waiting_ticket_back_to_in_progress(self):
        ticket = make_ticket(self.sam, status=Ticket.Status.WAITING)
        self.client.force_login(self.sam)
        self.client.post(reverse("ticket_comment", args=[ticket.pk]), {"body": "It's my laptop."})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)

    def test_staff_reply_records_first_response(self):
        ticket = make_ticket(self.sam)
        self.client.force_login(self.agent)
        self.client.post(reverse("ticket_comment", args=[ticket.pk]), {"body": "On it."})
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_at)


class TicketListTests(TestCase):
    def setUp(self):
        self.sam = make_user("sam")
        self.casey = make_user("casey")
        self.agent = make_user("jordan", staff=True)
        self.wifi = make_ticket(self.sam, title="Wi-Fi drops", priority=1, assignee=self.agent)
        self.printer = make_ticket(self.casey, title="Printer jam", priority=4)
        self.closed = make_ticket(self.sam, title="Old issue", status=Ticket.Status.CLOSED)

    def titles(self, **params):
        response = self.client.get(reverse("ticket_list"), params)
        return [t.title for t in response.context["page"].object_list]

    def test_requesters_only_see_their_own_open_tickets(self):
        self.client.force_login(self.sam)
        self.assertEqual(self.titles(), ["Wi-Fi drops"])
        self.assertCountEqual(self.titles(status="all"), ["Wi-Fi drops", "Old issue"])

    def test_staff_filters(self):
        self.client.force_login(self.agent)
        self.assertCountEqual(self.titles(), ["Wi-Fi drops", "Printer jam"])
        self.assertEqual(self.titles(priority=4), ["Printer jam"])
        self.assertEqual(self.titles(assigned="me"), ["Wi-Fi drops"])
        self.assertEqual(self.titles(assigned="none"), ["Printer jam"])
        self.assertEqual(self.titles(q="jam"), ["Printer jam"])
        self.assertEqual(self.titles(q=f"#{self.wifi.pk}"), ["Wi-Fi drops"])
        self.assertEqual(self.titles(status="closed"), ["Old issue"])

    def test_most_urgent_deadline_comes_first(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.titles(), ["Wi-Fi drops", "Printer jam"])


class DashboardTests(TestCase):
    def test_counts(self):
        sam, agent = make_user("sam"), make_user("jordan", staff=True)
        now = timezone.now()
        # Breached: P1 raised 5 hours ago. At risk: P1 raised 3.5 hours ago.
        make_ticket(sam, priority=1, created_at=now - timedelta(hours=5))
        make_ticket(sam, priority=1, created_at=now - timedelta(hours=3.5), assignee=agent)
        make_ticket(sam, priority=3)
        # Resolved in the last 30 days: one within target, one late.
        make_ticket(
            sam,
            priority=1,
            status=Ticket.Status.CLOSED,
            created_at=now - timedelta(days=3),
            resolved_at=now - timedelta(days=3) + timedelta(hours=2),
        )
        make_ticket(
            sam,
            priority=1,
            status=Ticket.Status.CLOSED,
            created_at=now - timedelta(days=3),
            resolved_at=now - timedelta(days=3) + timedelta(hours=9),
        )

        self.client.force_login(agent)
        context = self.client.get(reverse("dashboard")).context

        self.assertEqual(context["open_count"], 3)
        self.assertEqual(context["breached_count"], 1)
        self.assertEqual(context["at_risk_count"], 1)
        self.assertEqual(context["unassigned_count"], 2)
        self.assertEqual(context["my_open_count"], 1)
        self.assertEqual(context["compliance"], 50)
        self.assertEqual(len(context["needs_attention"]), 2)
        self.assertEqual(context["by_priority"][0]["count"], 2)

    def test_empty_helpdesk(self):
        self.client.force_login(make_user("jordan", staff=True))
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["compliance"])


class KnowledgeBaseTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("sam"))
        Article.objects.create(
            title="Connect to the staff Wi-Fi", slug="wifi", body="Choose STAFF."
        )
        Article.objects.create(
            title="Reset your password", slug="password", body="Use self-service."
        )
        Article.objects.create(title="Draft article", slug="draft", body="wifi", is_published=False)

    def search(self, query):
        response = self.client.get(reverse("article_list"), {"q": query})
        return [a.slug for a in response.context["articles"]]

    def test_search_covers_title_and_body_and_skips_drafts(self):
        self.assertEqual(self.search("staff"), ["wifi"])
        self.assertEqual(self.search("self-service"), ["password"])

    def test_search_ignores_hyphens(self):
        self.assertEqual(self.search("wifi"), ["wifi"])
        self.assertEqual(self.search("WI-FI"), ["wifi"])
        self.assertEqual(self.search("selfservice"), ["password"])

    def test_drafts_are_not_reachable(self):
        self.assertEqual(
            self.client.get(reverse("article_detail", args=["draft"])).status_code, 404
        )
        self.assertContains(
            self.client.get(reverse("article_detail", args=["wifi"])), "Choose STAFF."
        )
