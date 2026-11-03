"""Account rules that sit next to django-allauth.

Login requires a verified email address (ACCOUNT_EMAIL_VERIFICATION = "mandatory"). People
who sign up themselves prove their address by clicking the link in the verification email.
Accounts that TechCare creates (business customers and staff, in the admin) are different:
a TechCare employee typed the address in, so it is trusted straight away. Otherwise those
people would be asked to verify on their first login, or be stuck if no email was entered.
"""

from allauth.account.models import EmailAddress


def display_name(user):
    """How allauth names people in its messages and emails (ACCOUNT_USER_DISPLAY):
    'Alex Rivera' rather than the generated username."""
    return user.get_full_name() or user.get_username()


def trust_email(user):
    """Mark the user's current email address as verified and primary. Does nothing when the
    user has no email address."""
    if not user.email:
        return
    EmailAddress.objects.filter(user=user).exclude(email__iexact=user.email).update(primary=False)
    EmailAddress.objects.update_or_create(
        user=user,
        email__iexact=user.email,
        defaults={"email": user.email.lower(), "verified": True, "primary": True},
    )
