from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from helpdesk import sla


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class TicketQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=Ticket.OPEN_STATUSES)

    def visible_to(self, user):
        """IT staff see every ticket; everyone else only sees tickets they raised."""
        if user.is_staff:
            return self
        return self.filter(requester=user)


class Ticket(models.Model):
    class Priority(models.IntegerChoices):
        CRITICAL = 1, "P1 - Critical"
        HIGH = 2, "P2 - High"
        MEDIUM = 3, "P3 - Medium"
        LOW = 4, "P4 - Low"

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING = "waiting", "Waiting on requester"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    OPEN_STATUSES = [Status.NEW, Status.IN_PROGRESS, Status.WAITING]
    DONE_STATUSES = [Status.RESOLVED, Status.CLOSED]

    title = models.CharField(max_length=200)
    description = models.TextField()
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
        limit_choices_to={"is_staff": True},
    )
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)

    # A plain default (not auto_now_add) so imported or demo tickets can keep their real date.
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    response_due_at = models.DateTimeField(editable=False)
    resolution_due_at = models.DateTimeField(editable=False)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = TicketQuerySet.as_manager()

    class Meta:
        ordering = ["resolution_due_at"]
        indexes = [models.Index(fields=["status", "resolution_due_at"])]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    def get_absolute_url(self):
        return reverse("ticket_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        # Due dates always follow from priority and the time the ticket was raised, so
        # changing the priority moves the deadlines (counted from creation, not from now).
        self.response_due_at, self.resolution_due_at = sla.due_dates(self.priority, self.created_at)

        # Resolving stops the resolution clock; reopening restarts it.
        if self.status in self.DONE_STATUSES:
            if self.resolved_at is None:
                self.resolved_at = timezone.now()
        else:
            self.resolved_at = None
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    def response_sla(self, now=None):
        return sla.sla_state(
            self.created_at, self.response_due_at, self.first_response_at, now or timezone.now()
        )

    def resolution_sla(self, now=None):
        return sla.sla_state(
            self.created_at, self.resolution_due_at, self.resolved_at, now or timezone.now()
        )

    def add_comment(self, author, body, internal=False, at=None):
        """Adds a comment. The first public reply from IT staff stops the response clock;
        internal notes and the requester's own comments do not count."""
        comment = self.comments.create(
            author=author, body=body, is_internal=internal, created_at=at or timezone.now()
        )
        counts_as_response = (
            not internal
            and author.is_staff
            and author != self.requester
            and self.first_response_at is None
        )
        if counts_as_response:
            self.first_response_at = comment.created_at
            self.save()
        return comment


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False, help_text="Internal notes are only visible to IT staff."
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on #{self.ticket_id}"


class Article(models.Model):
    """A knowledge-base article: a fix people can apply themselves."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    is_published = models.BooleanField(default=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("article_detail", args=[self.slug])
