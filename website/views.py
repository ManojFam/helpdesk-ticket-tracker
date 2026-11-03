from django.shortcuts import render

from helpdesk import sla
from helpdesk.models import Service, Ticket

# What each priority means, in customers' words.
PRIORITY_EXAMPLES = {
    1: "Everyone is affected, or a key system is down",
    2: "One person can't work",
    3: "Something is broken, but there's a workaround",
    4: "Requests, questions and small changes",
}


def response_times():
    """The SLA table for the website, read from the same targets the tickets use."""
    return [
        {
            "label": label,
            "example": PRIORITY_EXAMPLES[value],
            "response": sla.describe_duration(sla.SLA_TARGETS[value].response),
            "resolution": sla.describe_duration(sla.SLA_TARGETS[value].resolution),
        }
        for value, label in Ticket.Priority.choices
    ]


def home(request):
    context = {
        "services": Service.objects.filter(is_active=True)[:6],
        "response_times": response_times(),
    }
    return render(request, "website/home.html", context)


def services(request):
    active = list(Service.objects.filter(is_active=True))
    context = {
        "business_services": [s for s in active if s.for_business],
        "home_services": [s for s in active if s.for_home],
        "response_times": response_times(),
    }
    return render(request, "website/services.html", context)
