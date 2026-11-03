from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from helpdesk import bookings
from helpdesk.models import Booking, Service, Ticket
from helpdesk.tests.helpers import make_organisation, make_user

MONDAY = date(2026, 11, 2)


def open_day(days_ahead):
    """A bookable day `days_ahead` from today (skipping Sundays)."""
    day = timezone.localdate() + timedelta(days=days_ahead)
    return day + timedelta(days=1) if day.weekday() == bookings.SUNDAY else day


def make_service(name, audience="both", delivery="onsite", **extra):
    return Service.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        summary=name,
        audience=audience,
        delivery=delivery,
        price_from=Decimal("129"),
        price_unit="per visit",
        **extra,
    )


class VisitDateRuleTests(SimpleTestCase):
    def test_tomorrow_up_to_60_days_ahead_is_fine(self):
        for days in (1, 2, 60):
            day = MONDAY + timedelta(days=days)
            if day.weekday() != bookings.SUNDAY:
                bookings.check_visit_date(day, MONDAY)

    def test_today_and_the_past_are_refused(self):
        for day in (MONDAY, MONDAY - timedelta(days=1)):
            with self.subTest(day=day), self.assertRaisesMessage(ValidationError, "tomorrow"):
                bookings.check_visit_date(day, MONDAY)

    def test_more_than_60_days_ahead_is_refused(self):
        with self.assertRaisesMessage(ValidationError, "60 days"):
            bookings.check_visit_date(MONDAY + timedelta(days=61), MONDAY)

    def test_sundays_are_refused(self):
        with self.assertRaisesMessage(ValidationError, "Sundays"):
            bookings.check_visit_date(MONDAY + timedelta(days=6), MONDAY)


class Visits(TestCase):
    def setUp(self):
        self.northside = make_organisation("Northside Dental Clinic")
        self.manager = make_user("sam", organisation=self.northside, manager=True)
        self.colleague = make_user("casey", organisation=self.northside)
        self.home = make_user("alex", first_name="Alex", last_name="Chen")
        self.other_home = make_user("pat")
        self.jordan = make_user("jordan", staff=True, first_name="Jordan", last_name="Lee")
        self.riley = make_user("riley", staff=True)

        self.repair = make_service("On-site repair", audience="both")
        self.home_wifi = make_service("Home Wi-Fi", audience="home")
        self.office = make_service("Office network", audience="business")
        self.remote = make_service("Remote support", delivery="remote")
        self.old = make_service("Old service", is_active=False)

    def request(self, user, service=None, day=2, slot="morning"):
        return bookings.request_visit(
            user,
            service=service or self.repair,
            visit_date=open_day(day),
            time_slot=slot,
            address="21 Example Avenue",
            contact_phone="0491 570 159",
            notes="",
            problem="Printer jams.",
        )


class BookableServiceTests(Visits):
    def names(self, user):
        return set(bookings.bookable_services(user).values_list("name", flat=True))

    def test_home_customers_see_home_and_shared_on_site_services(self):
        self.assertEqual(self.names(self.home), {"On-site repair", "Home Wi-Fi"})

    def test_business_customers_see_business_and_shared_on_site_services(self):
        self.assertEqual(self.names(self.colleague), {"On-site repair", "Office network"})

    def test_staff_can_book_any_active_on_site_service(self):
        self.assertEqual(
            self.names(self.jordan), {"On-site repair", "Home Wi-Fi", "Office network"}
        )


class RequestVisitTests(Visits):
    def form_data(self, **overrides):
        data = {
            "service": self.repair.pk,
            "problem": "Printer jams on every page.",
            "visit_date": open_day(3).isoformat(),
            "time_slot": "afternoon",
            "address": "21 Example Avenue, Northside",
            "contact_phone": "0491 570 159",
            "notes": "Side gate",
        }
        data.update(overrides)
        return data

    def test_requesting_a_visit_creates_a_booking_and_its_ticket(self):
        self.client.force_login(self.colleague)
        response = self.client.post(reverse("booking_create"), self.form_data())

        booking = Booking.objects.get()
        self.assertRedirects(response, booking.get_absolute_url())
        self.assertEqual(booking.status, Booking.Status.REQUESTED)
        self.assertEqual(booking.ticket.requester, self.colleague)
        self.assertEqual(booking.ticket.organisation, self.northside)
        self.assertEqual(booking.ticket.title, "On-site visit: On-site repair")
        self.assertIn("21 Example Avenue, Northside", booking.ticket.description)

    def test_cannot_book_a_remote_or_wrong_audience_service(self):
        self.client.force_login(self.home)
        for service in (self.remote, self.office, self.old):
            with self.subTest(service=service.name):
                response = self.client.post(
                    reverse("booking_create"), self.form_data(service=service.pk)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("service", response.context["form"].errors)
        self.assertFalse(Booking.objects.exists())

    def test_cannot_book_today(self):
        self.client.force_login(self.home)
        response = self.client.post(
            reverse("booking_create"),
            self.form_data(visit_date=timezone.localdate().isoformat()),
        )
        self.assertIn("visit_date", response.context["form"].errors)

    def test_website_link_preselects_the_service(self):
        self.client.force_login(self.home)
        response = self.client.get(reverse("booking_create"), {"service": "home-wi-fi"})
        self.assertEqual(response.context["form"].initial["service"], self.home_wifi)

    def test_anonymous_visitors_are_asked_to_log_in_first(self):
        url = reverse("booking_create") + "?service=home-wi-fi"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])


class VisibilityTests(Visits):
    def test_customers_see_only_their_own_visits(self):
        booking = self.request(self.home)
        self.client.force_login(self.other_home)
        self.assertEqual(self.client.get(booking.get_absolute_url()).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("booking_cancel", args=[booking.pk])).status_code, 404
        )

    def test_organisation_manager_sees_colleagues_visits(self):
        booking = self.request(self.colleague)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(booking.get_absolute_url()).status_code, 200)
        self.assertIn(booking, self.client.get(reverse("booking_list")).context["visits"])

    def test_customers_cannot_confirm_or_complete(self):
        booking = self.request(self.home)
        self.client.force_login(self.home)
        for name in ("booking_confirm", "booking_complete"):
            with self.subTest(action=name):
                self.assertEqual(
                    self.client.post(reverse(name, args=[booking.pk])).status_code, 403
                )
        self.assertEqual(self.client.get(reverse("schedule")).status_code, 403)


class StaffWorkflowTests(Visits):
    def confirm(self, booking, technician, day=2, slot="morning"):
        return self.client.post(
            reverse("booking_confirm", args=[booking.pk]),
            {
                "technician": technician.pk,
                "visit_date": open_day(day).isoformat(),
                "time_slot": slot,
            },
        )

    def test_confirming_assigns_the_technician_and_tells_the_customer(self):
        booking = self.request(self.home)
        self.client.force_login(self.jordan)
        self.confirm(booking, self.riley, day=4, slot="afternoon")

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.technician, self.riley)
        self.assertEqual(booking.visit_date, open_day(4))
        ticket = booking.ticket
        self.assertEqual(ticket.assignee, self.riley)
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertIn("Visit confirmed", ticket.comments.last().body)
        self.assertIsNotNone(ticket.first_response_at)  # TechCare replied publicly

    def test_a_technician_cannot_be_double_booked(self):
        first = self.request(self.home)
        second = self.request(self.other_home)
        self.client.force_login(self.jordan)
        self.confirm(first, self.jordan)
        self.confirm(second, self.jordan)  # same technician, day and slot

        second.refresh_from_db()
        self.assertEqual(second.status, Booking.Status.REQUESTED)
        self.assertIsNone(second.technician)
        # A different slot is fine.
        self.confirm(second, self.jordan, slot="afternoon")
        second.refresh_from_db()
        self.assertEqual(second.status, Booking.Status.CONFIRMED)

    def test_the_database_also_refuses_a_double_booking(self):
        first = self.request(self.home)
        second = self.request(self.other_home)
        bookings.confirm_visit(
            first,
            by=self.jordan,
            technician=self.jordan,
            visit_date=first.visit_date,
            time_slot="morning",
        )
        Booking.objects.filter(pk=second.pk).update(
            technician=self.jordan, visit_date=first.visit_date, time_slot="morning"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=second.pk).update(status=Booking.Status.CONFIRMED)

    def test_completing_resolves_the_ticket(self):
        booking = self.request(self.home)
        bookings.confirm_visit(
            booking,
            by=self.jordan,
            technician=self.jordan,
            visit_date=booking.visit_date,
            time_slot="morning",
        )
        self.client.force_login(self.jordan)
        self.client.post(reverse("booking_complete", args=[booking.pk]), {"summary": "New toner."})

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)
        self.assertEqual(booking.ticket.status, Ticket.Status.RESOLVED)
        self.assertIn("New toner.", booking.ticket.comments.last().body)

    def test_only_confirmed_visits_can_be_completed(self):
        booking = self.request(self.home)
        with self.assertRaises(bookings.BookingError):
            bookings.complete_visit(booking, by=self.jordan)

    def test_schedule_lists_the_technicians_confirmed_visits_by_day(self):
        mine = self.request(self.home, day=2)
        not_confirmed = self.request(self.other_home, day=2)
        bookings.confirm_visit(
            mine,
            by=self.jordan,
            technician=self.jordan,
            visit_date=mine.visit_date,
            time_slot="morning",
        )
        self.client.force_login(self.jordan)
        days = self.client.get(reverse("schedule")).context["days"]

        self.assertEqual(days, [(mine.visit_date, [mine])])
        self.assertNotIn(not_confirmed, days[0][1])
        riley_days = self.client.get(reverse("schedule"), {"technician": self.riley.pk}).context[
            "days"
        ]
        self.assertEqual(riley_days, [])

    def test_dashboard_counts_visits(self):
        self.request(self.home)
        today_visit = self.request(self.other_home)
        Booking.objects.filter(pk=today_visit.pk).update(
            status=Booking.Status.CONFIRMED, technician=self.riley, visit_date=timezone.localdate()
        )
        self.client.force_login(self.jordan)
        context = self.client.get(reverse("dashboard")).context
        self.assertEqual(context["visits_to_confirm"], 1)
        self.assertEqual(context["visits_today"], 1)


class FormDisplayTests(Visits):
    def test_staff_form_shows_the_current_date_in_the_format_browsers_need(self):
        booking = self.request(self.home)
        self.client.force_login(self.jordan)
        page = self.client.get(booking.get_absolute_url())
        self.assertContains(page, f'value="{booking.visit_date.isoformat()}"')

    def test_time_slot_has_no_blank_choice(self):
        self.client.force_login(self.home)
        page = self.client.get(reverse("booking_create")).content.decode()
        self.assertIn("Morning (8am - 12pm)", page)
        self.assertNotIn('name="time_slot" value=""', page)


class CancelTests(Visits):
    def test_customer_can_cancel_a_future_visit(self):
        booking = self.request(self.home)
        self.client.force_login(self.home)
        self.client.post(
            reverse("booking_cancel", args=[booking.pk]), {"reason": "Fixed it myself"}
        )

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertIn("cancelled by the customer", booking.ticket.comments.last().body)
        self.assertTrue(booking.ticket.is_open)  # the problem may still need solving

    def test_customer_cannot_cancel_on_the_day_but_staff_can(self):
        booking = self.request(self.home)
        today = booking.visit_date
        self.assertFalse(bookings.can_cancel(booking, self.home, today))
        self.assertTrue(bookings.can_cancel(booking, self.jordan, today))

    def test_finished_visits_cannot_be_cancelled(self):
        booking = self.request(self.home)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.Status.COMPLETED)
        booking.refresh_from_db()
        with self.assertRaises(bookings.BookingError):
            bookings.cancel_visit(booking, by=self.jordan, today=timezone.localdate())


class WebsiteLinkTests(Visits):
    def test_on_site_services_have_a_book_link_and_remote_ones_dont(self):
        page = self.client.get(reverse("site_services")).content.decode()
        self.assertIn(f"{reverse('booking_create')}?service=home-wi-fi", page)
        self.assertNotIn("?service=remote-support", page)
