from django import forms
from django.contrib.auth import get_user_model

from helpdesk import bookings
from helpdesk.models import Booking, Comment, Ticket
from helpdesk.sla import SLA_TARGETS


def _hours(delta):
    hours = delta.total_seconds() / 3600
    return f"{hours:g}h" if hours >= 1 else f"{int(delta.total_seconds() // 60)}m"


PRIORITY_HELP = " | ".join(
    f"P{p}: reply {_hours(t.response)}, fix {_hours(t.resolution)}" for p, t in SLA_TARGETS.items()
)


class TicketCreateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["title", "category", "priority", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}
        help_texts = {
            "priority": "P1 only when many people or a whole service is down. " + PRIORITY_HELP,
            "description": "What happened, when it started, and any error message.",
        }


class TicketUpdateForm(forms.ModelForm):
    """Fields IT staff change while working a ticket."""

    class Meta:
        model = Ticket
        fields = ["status", "priority", "assignee", "category"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _staff_choices(self.fields["assignee"])


class ISODateInput(forms.DateInput):
    """A browser date picker. Browsers only accept dates as 2026-11-05, while Django would
    format them for the site's language (05/11/2026), which the picker silently discards."""

    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


def _staff_choices(field):
    field.queryset = (
        get_user_model()
        .objects.filter(is_staff=True, is_active=True)
        .order_by("first_name", "username")
    )
    field.label_from_instance = lambda u: u.get_full_name() or u.username


class BookingRequestForm(forms.ModelForm):
    """A customer asks for a technician visit. The rules (which services, which dates) come
    from helpdesk/bookings.py."""

    problem = forms.CharField(
        label="What do you need help with?",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="e.g. 'Set up our new printer and connect it to three laptops'.",
    )

    class Meta:
        model = Booking
        fields = ["service", "visit_date", "time_slot", "address", "contact_phone", "notes"]
        widgets = {
            "visit_date": ISODateInput(),
            "time_slot": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"visit_date": "Preferred date", "time_slot": "Preferred time"}

    field_order = [
        "service",
        "problem",
        "visit_date",
        "time_slot",
        "address",
        "contact_phone",
        "notes",
    ]

    def __init__(self, *args, user, today, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today
        self.fields["service"].queryset = bookings.bookable_services(user)
        self.fields["service"].label_from_instance = lambda s: f"{s.name} ({s.price_label})"
        self.fields["service"].empty_label = "Choose a service"
        self.fields["time_slot"].choices = Booking.Slot.choices  # no blank "Select an option"
        # Lets the browser's date picker grey out dates that can't be booked.
        self.fields["visit_date"].widget.attrs.update(
            min=bookings.earliest_visit_date(today).isoformat(),
            max=bookings.latest_visit_date(today).isoformat(),
        )

    def clean_visit_date(self):
        visit_date = self.cleaned_data["visit_date"]
        bookings.check_visit_date(visit_date, self.today)
        return visit_date


class BookingConfirmForm(forms.ModelForm):
    """Staff choose the technician and settle the date and slot."""

    class Meta:
        model = Booking
        fields = ["technician", "visit_date", "time_slot"]
        widgets = {"visit_date": ISODateInput()}

    def __init__(self, *args, today, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today
        self.fields["technician"].required = True
        _staff_choices(self.fields["technician"])

    def clean(self):
        cleaned = super().clean()
        technician = cleaned.get("technician")
        visit_date = cleaned.get("visit_date")
        time_slot = cleaned.get("time_slot")
        if visit_date and visit_date < self.today:
            self.add_error("visit_date", "The visit date can't be in the past.")
        if (
            technician
            and visit_date
            and time_slot
            and not bookings.technician_is_free(
                technician, visit_date, time_slot, exclude_booking=self.instance
            )
        ):
            self.add_error("technician", "This technician already has a visit in that slot.")
        return cleaned


class SignupDetailsForm(forms.Form):
    """Extra fields on the self sign-up page (django-allauth adds email and password).

    allauth calls signup() after it creates the user. People who sign up themselves are
    always home customers: no organisation and not staff. Business customers' accounts are
    created by TechCare in the admin.
    """

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    # allauth's sign-up form inherits from this class, so this also orders its fields.
    field_order = ["first_name", "last_name", "email", "password1", "password2"]

    def signup(self, request, user):
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save()


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body", "is_internal"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}
        labels = {"body": "Add a comment", "is_internal": "Internal note (TechCare staff only)"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Requesters cannot write internal notes.
        if user is None or not user.is_staff:
            del self.fields["is_internal"]
