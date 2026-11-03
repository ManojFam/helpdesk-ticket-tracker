"""Pages for technician visits. The rules live in helpdesk/bookings.py; these views only
check who is asking, show forms and call those rules."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from helpdesk import bookings
from helpdesk.forms import BookingConfirmForm, BookingRequestForm
from helpdesk.models import Booking
from helpdesk.permissions import staff_required


def _visible_booking(request, pk):
    # Bookings you may not see give a 404, exactly like tickets.
    return get_object_or_404(
        Booking.objects.visible_to(request.user).select_related(
            "service", "technician", "ticket__requester", "ticket__organisation"
        ),
        pk=pk,
    )


@login_required
def booking_list(request):
    visits = Booking.objects.visible_to(request.user).select_related(
        "service", "technician", "ticket__requester", "ticket__organisation"
    )
    show = request.GET.get("show", "upcoming")
    if show == "upcoming":
        visits = visits.upcoming()
    elif show in Booking.Status.values:
        visits = visits.filter(status=show)
    context = {"visits": visits, "show": show, "statuses": Booking.Status.choices}
    return render(request, "helpdesk/booking_list.html", context)


@login_required
def booking_create(request):
    today = timezone.localdate()
    initial = {"contact_phone": request.user.profile.phone}
    # /portal/bookings/new/?service=home-wi-fi-and-network-setup (from the website) preselects it.
    service = (
        bookings.bookable_services(request.user).filter(slug=request.GET.get("service")).first()
    )
    if service:
        initial["service"] = service

    form = BookingRequestForm(request.POST or None, user=request.user, today=today, initial=initial)
    if request.method == "POST" and form.is_valid():
        booking = bookings.request_visit(request.user, **form.cleaned_data)
        messages.success(
            request,
            "Visit requested. We'll confirm the time and your technician shortly; "
            f"you can follow it on ticket #{booking.ticket.pk}.",
        )
        return redirect(booking)
    return render(request, "helpdesk/booking_form.html", {"form": form})


@login_required
def booking_detail(request, pk):
    booking = _visible_booking(request, pk)
    today = timezone.localdate()
    confirm_form = None
    if request.user.is_staff and booking.status in (
        Booking.Status.REQUESTED,
        Booking.Status.CONFIRMED,
    ):
        confirm_form = BookingConfirmForm(instance=booking, today=today)
    context = {
        "booking": booking,
        "confirm_form": confirm_form,
        "can_complete": request.user.is_staff and booking.status == Booking.Status.CONFIRMED,
        "can_cancel": bookings.can_cancel(booking, request.user, today),
    }
    return render(request, "helpdesk/booking_detail.html", context)


@staff_required
@require_POST
def booking_confirm(request, pk):
    booking = _visible_booking(request, pk)
    # The form validates against a copy, so a rejected change doesn't alter `booking`.
    form = BookingConfirmForm(
        request.POST, instance=Booking.objects.get(pk=pk), today=timezone.localdate()
    )
    if not form.is_valid():
        messages.error(request, "Couldn't confirm the visit: " + form.errors.as_text())
        return redirect(booking)
    try:
        bookings.confirm_visit(booking, by=request.user, **form.cleaned_data)
        messages.success(request, "Visit confirmed and the customer has been updated.")
    except bookings.BookingError as error:
        messages.error(request, str(error))
    return redirect(booking)


@staff_required
@require_POST
def booking_complete(request, pk):
    booking = _visible_booking(request, pk)
    try:
        bookings.complete_visit(booking, by=request.user, summary=request.POST.get("summary", ""))
        messages.success(request, "Visit marked as completed and the ticket resolved.")
    except bookings.BookingError as error:
        messages.error(request, str(error))
    return redirect(booking)


@login_required
@require_POST
def booking_cancel(request, pk):
    booking = _visible_booking(request, pk)
    try:
        bookings.cancel_visit(
            booking,
            by=request.user,
            today=timezone.localdate(),
            reason=request.POST.get("reason", ""),
        )
        messages.success(request, "Visit cancelled.")
    except bookings.BookingError as error:
        messages.error(request, str(error))
    return redirect(booking)


@staff_required
def schedule(request):
    """A technician's confirmed visits for the next two weeks. Defaults to your own."""
    technicians = (
        get_user_model()
        .objects.filter(is_staff=True, is_active=True)
        .order_by("first_name", "username")
    )
    technician = technicians.filter(pk=request.GET.get("technician") or request.user.pk).first()
    technician = technician or request.user
    context = {
        "technician": technician,
        "technicians": technicians,
        "days": bookings.schedule_for(technician, timezone.localdate()),
    }
    return render(request, "helpdesk/schedule.html", context)
