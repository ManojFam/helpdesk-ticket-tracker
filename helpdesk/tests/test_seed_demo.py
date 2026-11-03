from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from helpdesk import roles, sla
from helpdesk.models import Article, Organisation, Ticket


class SeedDemoTests(TestCase):
    def test_creates_users_articles_and_tickets_in_every_sla_state(self):
        out = StringIO()
        call_command("seed_demo", password="demo-pass-123", stdout=out)

        self.assertTrue(get_user_model().objects.get(username="jordan.lee").is_staff)
        self.assertTrue(
            get_user_model().objects.get(username="jordan.lee").check_password("demo-pass-123")
        )
        self.assertEqual(Article.objects.count(), 10)

        now = timezone.now()
        states = {t.resolution_sla(now) for t in Ticket.objects.all()}
        self.assertEqual(states, {sla.ON_TRACK, sla.AT_RISK, sla.BREACHED, sla.MET})
        self.assertNotIn("demo-pass-123", out.getvalue())

    def test_creates_business_and_home_customers(self):
        call_command("seed_demo", password="demo-pass-123", stdout=StringIO())
        User = get_user_model()

        self.assertEqual(roles.role_of(User.objects.get(username="sam.taylor")), roles.ORG_MANAGER)
        self.assertEqual(
            str(roles.organisation_of(User.objects.get(username="casey.nguyen"))),
            "Northside Dental Clinic",
        )
        self.assertIsNone(roles.organisation_of(User.objects.get(username="alex.chen")))
        self.assertEqual(Organisation.objects.count(), 2)
        self.assertTrue(Ticket.objects.filter(organisation__isnull=True).exists())
        self.assertEqual(
            Ticket.objects.filter(organisation__name="Harbour Freight Co")
            .exclude(requester__username="dana.kim")
            .count(),
            0,
        )

    def test_generates_and_prints_a_password_when_none_is_given(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        self.assertIn("Password for all demo users:", out.getvalue())

    def test_refuses_to_run_twice_without_reset(self):
        call_command("seed_demo", password="demo-pass-123", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("seed_demo", password="demo-pass-123", stdout=StringIO())

        call_command("seed_demo", password="demo-pass-123", reset=True, stdout=StringIO())
        self.assertEqual(get_user_model().objects.filter(username="jordan.lee").count(), 1)
