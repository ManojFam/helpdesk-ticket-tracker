from django.contrib.auth import get_user_model

from helpdesk.models import Category, Ticket

PASSWORD = "test-pass-123"


def make_user(username, staff=False, **extra):
    return get_user_model().objects.create_user(
        username=username, password=PASSWORD, is_staff=staff, **extra
    )


def make_ticket(requester, **fields):
    fields.setdefault("title", "Printer not working")
    fields.setdefault("description", "It prints blank pages.")
    return Ticket.objects.create(requester=requester, **fields)


def make_category(name="Printing"):
    return Category.objects.get_or_create(name=name)[0]
