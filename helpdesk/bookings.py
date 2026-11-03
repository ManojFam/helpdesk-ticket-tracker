"""Rules for technician visits, kept in one place (like sla.py).

Views call these functions instead of changing bookings themselves, so every way of
confirming, completing or cancelling a visit follows the same rules and leaves the same
trail of comments on the ticket.
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from helpdesk import roles
from helpdesk.models import Booking, Service, Ticket

# Visits can be booked from tomorrow up to this many days ahead, Monday to Saturday.
MAX_DAYS_AHEAD = 60
SUNDAY = 6  # date.weekday(): Monday is 0


class BookingError(Exception):
    """An action that isn't allowed for the booking's current status."""


def earliest_visit_date(today: date) -> date:
    return today + timedelta(days=1)


def latest_visit_date(today: date) -> date:
    return today + timedelta(days=MAX_DAYS_AHEAD)


def check_visit_date(visit_date: date, today: date) -> None:
    """Raises ValidationError with a customer-friendly message if the date can't be booked."""
    if visit_date < earliest_visit_date(today):
        raise ValidationError("Please choose a date from tomorrow onwards.")
    if visit_date > latest_visit_date(today):
        raise ValidationError(f"Visits can be booked up to {MAX_DAYS_AHEAD} days ahead.")
    if visit_date.weekday() == SUNDAY:
        raise ValidationError("We don't do visits on Sundays. Please choose another day.")


def bookable_services(user):
    """Active on-site services offered to this kind of customer. Staff can book anything."""
    services = Service.objects.filter(
        is_active=True, delivery__in=[Service.Delivery.ONSITE, Service.Delivery.EITHER]
    )
    if user.is_staff:
        return services
    if roles.organisation_of(user):
        return services.exclude(audience=Service.Audience.HOME)
    return services.exclude(audience=Service.Audience.BUSINESS)


def technician_is_free(technician, visit_date, time_slot, exclude_booking=None) -> bool:
    clashes = Booking.objects.filter(
        technician=technician,
        visit_date=visit_date,
        time_slot=time_slot,
        status=Booking.Status.CONFIRMED,
    )
    if exclude_booking is not None:
        clashes = clashes.exclude(pk=exclude_booking.pk)
    return not clashes.exists()


def _when(booking) -> str:
    return f"{booking.visit_date:%a %d %b %Y}, {booking.get_time_slot_display().lower()}"


@transaction.atomic
def request_visit(user, *, service, visit_date, time_slot, address, contact_phone, notes, problem):
    """Creates the ticket and the booking together: both exist, or neither does."""
    ticket = Ticket.objects.create(
        requester=user,
        title=f"On-site visit: {service.name}",
        description=(
            f"{problem}\n\n"
            f"Requested visit: {visit_date:%a %d %b %Y}, {dict(Booking.Slot.choices)[time_slot]}\n"
            f"Address: {address}\nPhone: {contact_phone}"
            + (f"\nAccess notes: {notes}" if notes else "")
        ),
    )
    return Booking.objects.create(
        ticket=ticket,
        service=service,
        visit_date=visit_date,
        time_slot=time_slot,
        address=address,
        contact_phone=contact_phone,
        notes=notes,
    )


@transaction.atomic
def confirm_visit(booking, *, by, technician, visit_date, time_slot):
    """Staff confirm (or re-confirm with changes) a requested or confirmed visit."""
    if booking.status not in (Booking.Status.REQUESTED, Booking.Status.CONFIRMED):
        raise BookingError(f"A {booking.get_status_display().lower()} visit can't be confirmed.")
    if not technician_is_free(technician, visit_date, time_slot, exclude_booking=booking):
        raise BookingError(f"{technician.get_full_name() or technician} already has a visit then.")

    booking.technician = technician
    booking.visit_date = visit_date
    booking.time_slot = time_slot
    booking.status = Booking.Status.CONFIRMED
    booking.save()

    ticket = booking.ticket
    if ticket.status == Ticket.Status.NEW:
        ticket.status = Ticket.Status.IN_PROGRESS
    ticket.assignee = technician
    ticket.save()
    name = technician.get_full_name() or technician.get_username()
    ticket.add_comment(by, f"Visit confirmed: {_when(booking)} with {name}.")
    return booking


@transaction.atomic
def complete_visit(booking, *, by, summary=""):
    """The visit happened: the booking is completed and its ticket resolved."""
    if booking.status != Booking.Status.CONFIRMED:
        raise BookingError("Only a confirmed visit can be marked as completed.")
    booking.status = Booking.Status.COMPLETED
    booking.save()

    ticket = booking.ticket
    ticket.add_comment(by, "Visit completed." + (f" {summary}" if summary else ""))
    ticket.status = Ticket.Status.RESOLVED
    ticket.save()
    return booking


def can_cancel(booking, user, today: date) -> bool:
    """Staff can cancel any open visit. Customers can cancel up to the day before."""
    if booking.status not in (Booking.Status.REQUESTED, Booking.Status.CONFIRMED):
        return False
    return user.is_staff or booking.visit_date > today


@transaction.atomic
def cancel_visit(booking, *, by, today: date, reason=""):
    if not can_cancel(booking, by, today):
        raise BookingError("This visit can no longer be cancelled online. Please call us.")
    booking.status = Booking.Status.CANCELLED
    booking.save()

    # The ticket stays open: the problem may still need solving another way.
    who = "TechCare" if by.is_staff else "the customer"
    message = f"Visit on {_when(booking)} cancelled by {who}." + (f" {reason}" if reason else "")
    booking.ticket.add_comment(by, message)
    return booking


def schedule_for(technician, today: date, days: int = 14):
    """A technician's confirmed visits from today, grouped by date: [(date, [bookings])]."""
    visits = (
        Booking.objects.filter(
            technician=technician,
            status=Booking.Status.CONFIRMED,
            visit_date__gte=today,
            visit_date__lt=today + timedelta(days=days),
        )
        .select_related("service", "ticket__requester", "ticket__organisation")
        .order_by("visit_date", "time_slot")
    )
    grouped = {}
    for visit in visits:
        grouped.setdefault(visit.visit_date, []).append(visit)
    return list(grouped.items())
