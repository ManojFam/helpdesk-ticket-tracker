import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from helpdesk import roles
from helpdesk.accounts import trust_email
from helpdesk.tests.helpers import PASSWORD, make_organisation, make_user

NEW_PASSWORD = "Blue-kettle-472"

GOOGLE_CONFIGURED = {
    "GOOGLE_LOGIN_ENABLED": True,
    "SOCIALACCOUNT_PROVIDERS": {
        "google": {"APP": {"client_id": "test-id", "secret": "test-secret"}, "SCOPE": ["email"]}
    },
}


def sign_up(client, **overrides):
    data = {
        "first_name": "Alex",
        "last_name": "Rivera",
        "email": "alex.rivera@example.com",
        "password1": NEW_PASSWORD,
        "password2": NEW_PASSWORD,
    }
    data.update(overrides)
    return client.post(reverse("account_signup"), data)


def confirmation_link(email):
    return re.search(r"https?://testserver(/accounts/confirm-email/[^\s]+/)", email.body).group(1)


class SignUpTests(TestCase):
    def setUp(self):
        # allauth rate-limits emails (e.g. one verification email per address every few
        # minutes) using Django's cache, which is shared between tests. Start each test clean.
        cache.clear()

    def test_sign_up_creates_a_home_customer_and_sends_a_verification_email(self):
        response = sign_up(self.client)

        self.assertRedirects(response, reverse("account_email_verification_sent"))
        user = get_user_model().objects.get(email="alex.rivera@example.com")
        self.assertEqual(user.get_full_name(), "Alex Rivera")
        self.assertFalse(user.is_staff)
        self.assertIsNone(user.profile.organisation)
        self.assertEqual(roles.role_of(user), roles.CUSTOMER)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/confirm-email/", mail.outbox[0].body)

    def test_verification_email_is_branded(self):
        sign_up(self.client)
        email = mail.outbox[0]
        self.assertTrue(email.subject.startswith("[TechCare Services] "))
        self.assertIn("Hello from TechCare Services", email.body)
        self.assertEqual(email.to, ["alex.rivera@example.com"])

    def test_cannot_log_in_before_confirming_the_email(self):
        sign_up(self.client)
        self.client.logout()
        response = self.client.post(
            reverse("account_login"), {"login": "alex.rivera@example.com", "password": NEW_PASSWORD}
        )
        self.assertRedirects(response, reverse("account_email_verification_sent"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_confirming_the_email_logs_in_and_opens_the_portal(self):
        sign_up(self.client)
        link = confirmation_link(mail.outbox[0])

        page = self.client.get(link)
        self.assertContains(page, "TechCare Services")  # allauth's page in our layout
        response = self.client.post(link)

        self.assertRedirects(response, reverse("portal"), fetch_redirect_response=False)
        self.assertTrue(EmailAddress.objects.get(email="alex.rivera@example.com").verified)
        tickets_page = self.client.get(reverse("ticket_list"))
        self.assertEqual(tickets_page.status_code, 200)
        # Messages name the person, not the username allauth generated.
        self.assertContains(tickets_page, "Successfully signed in as Alex Rivera")

    def test_sign_up_cannot_make_someone_staff_or_join_an_organisation(self):
        org = make_organisation()
        sign_up(self.client, is_staff="on", is_superuser="on", organisation=org.pk)
        user = get_user_model().objects.get(email="alex.rivera@example.com")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertIsNone(user.profile.organisation)

    def test_existing_email_does_not_reveal_that_the_account_exists(self):
        """allauth's enumeration protection: the page looks like a normal sign-up, so the form
        can't be used to find out who is a customer. The real owner is emailed instead."""
        make_user("existing", email="alex.rivera@example.com")
        response = sign_up(self.client)

        self.assertRedirects(response, reverse("account_email_verification_sent"))
        self.assertEqual(
            get_user_model().objects.filter(email="alex.rivera@example.com").count(), 1
        )
        self.assertEqual(mail.outbox[0].to, ["alex.rivera@example.com"])

    def test_weak_passwords_are_rejected(self):
        response = sign_up(self.client, password1="password", password2="password")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email="alex.rivera@example.com").exists())


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user("jordan", email="jordan@example.com")
        trust_email(self.user)

    def test_log_in_with_username_or_email(self):
        for login in ["jordan", "jordan@example.com"]:
            with self.subTest(login=login):
                response = self.client.post(
                    reverse("account_login"), {"login": login, "password": PASSWORD}
                )
                self.assertRedirects(response, reverse("portal"), fetch_redirect_response=False)
                self.client.logout()

    def test_wrong_password(self):
        response = self.client.post(
            reverse("account_login"), {"login": "jordan", "password": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_log_out_returns_to_the_website(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.post(reverse("account_logout")), reverse("site_home"))

    def test_password_reset_sends_an_email(self):
        response = self.client.post(
            reverse("account_reset_password"), {"email": "jordan@example.com"}
        )
        self.assertRedirects(response, reverse("account_reset_password_done"))
        self.assertEqual(len(mail.outbox), 1)


class TrustedEmailTests(TestCase):
    def test_trust_email_marks_the_current_address_verified_and_primary(self):
        user = make_user("casey", email="Casey@Example.com")
        trust_email(user)
        address = EmailAddress.objects.get(user=user)
        self.assertTrue(address.verified and address.primary)
        self.assertEqual(address.email, "casey@example.com")

    def test_saving_a_user_in_admin_trusts_their_email(self):
        admin = make_user("boss", staff=True, is_superuser=True)
        customer = make_user("casey")
        self.client.force_login(admin)
        self.client.post(
            reverse("admin:auth_user_change", args=[customer.pk]),
            {
                "username": "casey",
                "email": "casey@example.com",
                "is_active": "on",
                "date_joined_0": "2026-11-01",
                "date_joined_1": "09:00:00",
                "profile-TOTAL_FORMS": "1",
                "profile-INITIAL_FORMS": "1",
                "profile-MIN_NUM_FORMS": "0",
                "profile-MAX_NUM_FORMS": "1",
                "profile-0-id": customer.profile.pk,
                "profile-0-user": customer.pk,
            },
        )
        self.assertTrue(EmailAddress.objects.filter(user=customer, verified=True).exists())

        self.client.logout()
        response = self.client.post(
            reverse("account_login"), {"login": "casey@example.com", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("portal"), fetch_redirect_response=False)


class GoogleButtonTests(TestCase):
    def test_hidden_when_google_is_not_configured(self):
        for name in ["account_login", "account_signup"]:
            with self.subTest(page=name):
                self.assertNotContains(self.client.get(reverse(name)), "with Google")

    @override_settings(**GOOGLE_CONFIGURED)
    def test_shown_when_google_is_configured(self):
        login_page = self.client.get(reverse("account_login"))
        self.assertContains(login_page, "Continue with Google")
        self.assertContains(login_page, 'action="/accounts/google/login/')
        self.assertContains(self.client.get(reverse("account_signup")), "Sign up with Google")

    @override_settings(**GOOGLE_CONFIGURED)
    def test_google_login_starts_by_redirecting_to_google(self):
        response = self.client.post("/accounts/google/login/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://accounts.google.com/"))
        self.assertIn("client_id=test-id", response["Location"])
