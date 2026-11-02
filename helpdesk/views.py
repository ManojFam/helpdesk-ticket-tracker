from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q, TextField, Value
from django.db.models.functions import Concat, Replace
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from helpdesk import sla
from helpdesk.forms import CommentForm, TicketCreateForm, TicketUpdateForm
from helpdesk.models import Article, Ticket
from helpdesk.permissions import staff_required


@login_required
def home(request):
    if request.user.is_staff:
        return redirect("dashboard")
    return redirect("ticket_list")


@staff_required
def dashboard(request):
    now = timezone.now()
    open_tickets = list(Ticket.objects.open().select_related("assignee", "category"))
    for ticket in open_tickets:
        ticket.sla_state = ticket.resolution_sla(now)

    def count(state):
        return sum(1 for t in open_tickets if t.sla_state == state)

    by_priority = []
    for value, label in Ticket.Priority.choices:
        n = sum(1 for t in open_tickets if t.priority == value)
        share = round(100 * n / len(open_tickets)) if open_tickets else 0
        by_priority.append({"value": value, "label": label, "count": n, "share": share})

    by_status = [
        {"value": value, "label": label, "count": sum(1 for t in open_tickets if t.status == value)}
        for value, label in Ticket.Status.choices
        if value in Ticket.OPEN_STATUSES
    ]

    # SLA compliance: tickets resolved in the last 30 days that met their resolution target.
    resolved_30d = Ticket.objects.filter(resolved_at__gte=now - timedelta(days=30))
    resolved_count = resolved_30d.count()
    met_count = resolved_30d.filter(resolved_at__lte=F("resolution_due_at")).count()

    needs_attention = sorted(
        (t for t in open_tickets if t.sla_state in (sla.BREACHED, sla.AT_RISK)),
        key=lambda t: t.resolution_due_at,
    )

    context = {
        "open_count": len(open_tickets),
        "breached_count": count(sla.BREACHED),
        "at_risk_count": count(sla.AT_RISK),
        "unassigned_count": sum(1 for t in open_tickets if t.assignee_id is None),
        "awaiting_response_count": sum(1 for t in open_tickets if t.first_response_at is None),
        "my_open_count": sum(1 for t in open_tickets if t.assignee_id == request.user.id),
        "created_7d": Ticket.objects.filter(created_at__gte=now - timedelta(days=7)).count(),
        "resolved_7d": Ticket.objects.filter(resolved_at__gte=now - timedelta(days=7)).count(),
        "compliance": round(100 * met_count / resolved_count) if resolved_count else None,
        "resolved_30d": resolved_count,
        "by_priority": by_priority,
        "by_status": by_status,
        "needs_attention": needs_attention[:10],
    }
    return render(request, "helpdesk/dashboard.html", context)


@login_required
def ticket_list(request):
    tickets = Ticket.objects.visible_to(request.user).select_related("assignee", "category")

    status = request.GET.get("status", "open")
    if status == "open":
        tickets = tickets.open()
    elif status in Ticket.Status.values:
        tickets = tickets.filter(status=status)

    priority = request.GET.get("priority", "")
    if priority.isdigit():
        tickets = tickets.filter(priority=int(priority))

    assigned = request.GET.get("assigned", "")
    if request.user.is_staff and assigned == "me":
        tickets = tickets.filter(assignee=request.user)
    elif request.user.is_staff and assigned == "none":
        tickets = tickets.filter(assignee__isnull=True)

    query = request.GET.get("q", "").strip()
    if query:
        filters = Q(title__icontains=query) | Q(description__icontains=query)
        if query.lstrip("#").isdigit():
            filters |= Q(pk=int(query.lstrip("#")))
        tickets = tickets.filter(filters)

    page = Paginator(tickets, 25).get_page(request.GET.get("page"))
    # The current filters, so the "next page" links keep them.
    filters_query = request.GET.copy()
    filters_query.pop("page", None)
    context = {
        "page": page,
        "status": status,
        "priority": priority,
        "assigned": assigned,
        "q": query,
        "statuses": Ticket.Status.choices,
        "priorities": Ticket.Priority.choices,
        "filters_query": filters_query.urlencode(),
    }
    return render(request, "helpdesk/ticket_list.html", context)


@login_required
def ticket_create(request):
    form = TicketCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.requester = request.user
        ticket.save()
        messages.success(request, f"Ticket #{ticket.pk} raised. We'll be in touch.")
        return redirect(ticket)

    articles = Article.objects.filter(is_published=True).order_by("-updated_at")[:5]
    return render(request, "helpdesk/ticket_form.html", {"form": form, "articles": articles})


@login_required
def ticket_detail(request, pk):
    # Requesters get a 404 for other people's tickets, so ticket numbers reveal nothing.
    ticket = get_object_or_404(
        Ticket.objects.visible_to(request.user).select_related("requester", "assignee", "category"),
        pk=pk,
    )
    comments = ticket.comments.select_related("author")
    if not request.user.is_staff:
        comments = comments.filter(is_internal=False)

    related_articles = Article.objects.filter(is_published=True, category=ticket.category)[:3]
    context = {
        "ticket": ticket,
        "comments": comments,
        "comment_form": CommentForm(user=request.user),
        "update_form": TicketUpdateForm(instance=ticket) if request.user.is_staff else None,
        "related_articles": related_articles if ticket.category else [],
    }
    return render(request, "helpdesk/ticket_detail.html", context)


@login_required
@require_POST
def ticket_comment(request, pk):
    ticket = get_object_or_404(Ticket.objects.visible_to(request.user), pk=pk)
    form = CommentForm(request.POST, user=request.user)
    if form.is_valid():
        ticket.add_comment(
            author=request.user,
            body=form.cleaned_data["body"],
            internal=form.cleaned_data.get("is_internal", False),
        )
        # A requester replying to "waiting on requester" puts the ticket back in the queue.
        if not request.user.is_staff and ticket.status == Ticket.Status.WAITING:
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save()
        messages.success(request, "Comment added.")
    else:
        messages.error(request, "The comment was empty.")
    return redirect(ticket)


@staff_required
@require_POST
def ticket_update(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    form = TicketUpdateForm(request.POST, instance=ticket)
    if form.is_valid():
        form.save()
        messages.success(request, "Ticket updated.")
    else:
        messages.error(request, "Could not update the ticket: " + form.errors.as_text())
    return redirect(ticket)


@login_required
def article_list(request):
    articles = Article.objects.filter(is_published=True).select_related("category")
    query = request.GET.get("q", "").strip()
    if query:
        # Hyphens are ignored on both sides, so "wifi" finds "Wi-Fi" and "e-mail" finds "email".
        text = Replace(
            Concat("title", Value(" "), "summary", Value(" "), "body", output_field=TextField()),
            Value("-"),
            Value(""),
            output_field=TextField(),
        )
        articles = articles.annotate(search_text=text).filter(
            search_text__icontains=query.replace("-", "")
        )
    return render(request, "helpdesk/article_list.html", {"articles": articles, "q": query})


@login_required
def article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug, is_published=True)
    return render(request, "helpdesk/article_detail.html", {"article": article})
