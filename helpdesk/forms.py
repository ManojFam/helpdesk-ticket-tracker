from django import forms
from django.contrib.auth import get_user_model

from helpdesk.models import Comment, Ticket
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
        self.fields["assignee"].queryset = (
            get_user_model()
            .objects.filter(is_staff=True, is_active=True)
            .order_by("first_name", "username")
        )
        self.fields["assignee"].label_from_instance = lambda u: u.get_full_name() or u.username


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body", "is_internal"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}
        labels = {"body": "Add a comment", "is_internal": "Internal note (IT staff only)"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Requesters cannot write internal notes.
        if user is None or not user.is_staff:
            del self.fields["is_internal"]
