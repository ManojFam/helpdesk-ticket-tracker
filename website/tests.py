from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from helpdesk.models import Service
from helpdesk.tests.helpers import PASSWORD, make_user


def make_service(name, audience="both", price="129", unit="per visit", **extra):
    return Service.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        summary=f"{name} summary",
        audience=audience,
        price_from=Decimal(price),
        price_unit=unit,
        **extra,
    )


class PublicPageTests(TestCase):
    def setUp(self):
        self.repair = make_service("Repair visit", sort_order=1)
        self.wifi = make_service("Home Wi-Fi", audience="home", sort_order=2)
        self.plan = make_service(
            "Support plan", audience="business", price="39", unit="per user / month", sort_order=3
        )
        self.hidden = make_service("Old service", is_active=False)

    def test_home_page_is_public(self):
        response = self.client.get(reverse("site_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IT support that comes to you")
        self.assertContains(response, f'href="{reverse("login")}"')

    def test_home_page_lists_active_services_only(self):
        response = self.client.get(reverse("site_home"))
        self.assertContains(response, "Repair visit")
        self.assertContains(response, "From $39 per user / month")
        self.assertNotContains(response, "Old service")

    def test_home_page_shows_at_most_six_services(self):
        for n in range(10):
            make_service(f"Extra {n}", sort_order=10 + n)
        self.assertEqual(len(self.client.get(reverse("site_home")).context["services"]), 6)

    def test_services_page_groups_by_audience(self):
        response = self.client.get(reverse("site_services"))
        self.assertEqual(response.status_code, 200)
        business = [s.name for s in response.context["business_services"]]
        home = [s.name for s in response.context["home_services"]]
        self.assertEqual(business, ["Repair visit", "Support plan"])
        self.assertEqual(home, ["Repair visit", "Home Wi-Fi"])

    def test_response_times_come_from_the_sla_rules(self):
        rows = self.client.get(reverse("site_home")).context["response_times"]
        self.assertEqual(
            [(r["response"], r["resolution"]) for r in rows],
            [
                ("30 minutes", "4 hours"),
                ("1 hour", "8 hours"),
                ("4 hours", "24 hours"),
                ("8 hours", "3 days"),
            ],
        )

    def test_empty_price_list_still_renders(self):
        Service.objects.all().delete()
        self.assertContains(self.client.get(reverse("site_home")), "being updated")


class PortalLinkTests(TestCase):
    def test_logged_in_visitors_get_a_portal_link(self):
        self.client.force_login(make_user("sam"))
        response = self.client.get(reverse("site_home"))
        self.assertContains(response, "Open portal")
        self.assertContains(response, f'href="{reverse("portal")}"')

    def test_portal_lives_under_portal(self):
        self.assertEqual(reverse("portal"), "/portal/")
        self.assertEqual(reverse("ticket_list"), "/portal/tickets/")

    def test_logging_in_opens_the_portal(self):
        make_user("sam")
        response = self.client.post(reverse("login"), {"username": "sam", "password": PASSWORD})
        self.assertRedirects(response, reverse("portal"), fetch_redirect_response=False)

    def test_logging_out_returns_to_the_website(self):
        self.client.force_login(make_user("sam"))
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("site_home"))


class PriceLabelTests(TestCase):
    def test_whole_and_cents_prices(self):
        self.assertEqual(make_service("A", price="129").price_label, "From $129 per visit")
        self.assertEqual(
            make_service("B", price="24.50", unit="per user").price_label, "From $24.50 per user"
        )
        self.assertEqual(make_service("C", price="1499").price_label, "From $1,499 per visit")
