from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from helpdesk import roles
from helpdesk.models import Profile, Ticket
from helpdesk.tests.helpers import make_organisation, make_ticket, make_user


class Customers(TestCase):
    """Two business customers and a home customer, as in the demo data."""

    def setUp(self):
        self.northside = make_organisation("Northside Dental Clinic")
        self.harbour = make_organisation("Harbour Freight Co")
        self.manager = make_user("sam", organisation=self.northside, manager=True)
        self.colleague = make_user("casey", organisation=self.northside)
        self.other_org = make_user("dana", organisation=self.harbour, manager=True)
        self.home = make_user("alex")
        self.technician = make_user("jordan", staff=True)
        self.admin = make_user("boss", staff=True, is_superuser=True)

        self.manager_ticket = make_ticket(self.manager, title="Manager's ticket")
        self.colleague_ticket = make_ticket(self.colleague, title="Colleague's ticket")
        self.other_org_ticket = make_ticket(self.other_org, title="Harbour ticket")
        self.home_ticket = make_ticket(self.home, title="Home ticket")


class ProfileTests(Customers):
    def test_every_new_user_gets_a_profile(self):
        user = get_user_model().objects.create_user(username="new", password="x")
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_a_manager_must_belong_to_an_organisation(self):
        profile = self.home.profile
        profile.is_org_manager = True
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_roles(self):
        self.assertEqual(roles.role_of(self.admin), roles.ADMIN)
        self.assertEqual(roles.role_of(self.technician), roles.TECHNICIAN)
        self.assertEqual(roles.role_of(self.manager), roles.ORG_MANAGER)
        self.assertEqual(roles.role_of(self.colleague), roles.CUSTOMER)
        self.assertEqual(roles.role_of(self.home), roles.CUSTOMER)

    def test_manager_flag_without_organisation_gives_no_extra_access(self):
        Profile.objects.filter(user=self.home).update(is_org_manager=True)
        self.home.refresh_from_db()
        self.assertEqual(roles.role_of(self.home), roles.CUSTOMER)


class TicketOrganisationTests(Customers):
    def test_ticket_takes_the_requesters_organisation(self):
        self.assertEqual(self.colleague_ticket.organisation, self.northside)
        self.assertIsNone(self.home_ticket.organisation)

    def test_ticket_stays_with_the_organisation_when_the_person_leaves(self):
        profile = self.colleague.profile
        profile.organisation = None
        profile.save()
        self.colleague_ticket.refresh_from_db()
        self.assertEqual(self.colleague_ticket.organisation, self.northside)


class VisibilityTests(Customers):
    def visible(self, user):
        return set(Ticket.objects.visible_to(user).values_list("title", flat=True))

    def test_manager_sees_their_organisations_tickets(self):
        self.assertEqual(self.visible(self.manager), {"Manager's ticket", "Colleague's ticket"})

    def test_organisation_member_sees_only_their_own(self):
        self.assertEqual(self.visible(self.colleague), {"Colleague's ticket"})

    def test_home_customer_sees_only_their_own(self):
        self.assertEqual(self.visible(self.home), {"Home ticket"})

    def test_techcare_staff_see_everything(self):
        self.assertEqual(len(self.visible(self.technician)), 4)
        self.assertEqual(len(self.visible(self.admin)), 4)


class ManagerPageTests(Customers):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.manager)

    def test_ticket_list_shows_the_organisation_with_who_raised_each_ticket(self):
        response = self.client.get(reverse("ticket_list"))
        titles = {t.title for t in response.context["page"].object_list}
        self.assertEqual(titles, {"Manager's ticket", "Colleague's ticket"})
        self.assertTrue(response.context["show_requester"])
        self.assertContains(response, "Northside Dental Clinic tickets")
        self.assertContains(response, "Raised by")

    def test_can_open_and_comment_on_a_colleagues_ticket(self):
        url = self.colleague_ticket.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(
            reverse("ticket_comment", args=[self.colleague_ticket.pk]), {"body": "Any news?"}
        )
        self.assertEqual(self.colleague_ticket.comments.get().body, "Any news?")

    def test_cannot_see_another_organisations_ticket(self):
        url = self.other_org_ticket.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_cannot_see_internal_notes(self):
        self.colleague_ticket.add_comment(self.technician, "Internal only", internal=True)
        self.assertNotContains(
            self.client.get(self.colleague_ticket.get_absolute_url()), "Internal only"
        )

    def test_is_still_a_customer_for_staff_pages(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
        response = self.client.post(
            reverse("ticket_update", args=[self.colleague_ticket.pk]),
            {"status": "closed", "priority": 1},
        )
        self.assertEqual(response.status_code, 403)

    def test_comment_does_not_count_as_techcare_first_response(self):
        self.colleague_ticket.add_comment(self.manager, "I'll chase this.")
        self.colleague_ticket.refresh_from_db()
        self.assertIsNone(self.colleague_ticket.first_response_at)


class MemberPageTests(Customers):
    def test_member_cannot_open_a_colleagues_ticket(self):
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(self.manager_ticket.get_absolute_url()).status_code, 404)

    def test_member_list_has_no_raised_by_column(self):
        self.client.force_login(self.colleague)
        response = self.client.get(reverse("ticket_list"))
        self.assertFalse(response.context["show_requester"])
        self.assertContains(response, "My tickets")


class StaffPageTests(Customers):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.technician)

    def titles(self, **params):
        response = self.client.get(reverse("ticket_list"), params)
        return {t.title for t in response.context["page"].object_list}

    def test_filter_by_organisation(self):
        self.assertEqual(
            self.titles(organisation=self.northside.pk), {"Manager's ticket", "Colleague's ticket"}
        )
        self.assertEqual(self.titles(organisation="home"), {"Home ticket"})
        self.assertEqual(len(self.titles()), 4)

    def test_dashboard_counts_open_tickets_per_customer(self):
        by_organisation = self.client.get(reverse("dashboard")).context["by_organisation"]
        self.assertEqual(
            by_organisation,
            [("Northside Dental Clinic", 2), ("Harbour Freight Co", 1), ("Home customers", 1)],
        )

    def test_header_shows_role(self):
        self.assertContains(self.client.get(reverse("ticket_list")), "Technician")
        self.client.force_login(self.manager)
        self.assertContains(
            self.client.get(reverse("ticket_list")), "Manager, Northside Dental Clinic"
        )


class AdminPageTests(Customers):
    def test_admin_pages_load(self):
        self.client.force_login(self.admin)
        for url in [
            reverse("admin:helpdesk_organisation_changelist"),
            reverse("admin:helpdesk_organisation_change", args=[self.northside.pk]),
            reverse("admin:auth_user_changelist"),
            reverse("admin:auth_user_change", args=[self.manager.pk]),
            reverse("admin:auth_user_add"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_adding_a_user_in_admin_creates_one_profile(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "newstarter",
                "password1": "Sup3r-secret-pw!",
                "password2": "Sup3r-secret-pw!",
                "usable_password": "true",
            },
        )
        user = get_user_model().objects.get(username="newstarter")
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)
