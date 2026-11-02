from django import template
from django.utils import timezone
from django.utils.html import format_html

from helpdesk import sla

register = template.Library()


@register.simple_tag
def sla_badge(ticket, timer="resolution"):
    """A coloured badge for one SLA timer, e.g. 'At risk - 45m left'."""
    now = timezone.now()
    if timer == "response":
        state, due = ticket.response_sla(now), ticket.response_due_at
        running = ticket.first_response_at is None
    else:
        state, due = ticket.resolution_sla(now), ticket.resolution_due_at
        running = ticket.resolved_at is None

    label = sla.STATE_LABELS[state]
    if running:
        label = f"{label} - {sla.describe_time_left(due, now)}"
    return format_html('<span class="badge sla-{}">{}</span>', state, label)


@register.filter
def person(user, fallback="-"):
    """Full name, else username; `fallback` when there is no user (e.g. unassigned)."""
    if user is None:
        return fallback
    return user.get_full_name() or user.get_username()


@register.simple_tag
def priority_badge(ticket):
    return format_html(
        '<span class="badge p{}">{}</span>', ticket.priority, ticket.get_priority_display()
    )
