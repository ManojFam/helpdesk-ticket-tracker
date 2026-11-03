from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from helpdesk import roles, sla


class Organisation(models.Model):
    """A business customer of TechCare, e.g. a dental clinic or a logistics company."""

    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=250, blank=True)
    is_active = models.BooleanField(
        default=True, help_text="Untick when the organisation is no longer a customer."
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    """Extra details for every user. Created automatically with the user (see signals.py)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
        help_text="Leave empty for home customers and TechCare staff.",
    )
    is_org_manager = models.BooleanField(
        "organisation manager",
        default=False,
        help_text="Can see every ticket raised by people in their organisation.",
    )
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f"Profile of {self.user}"

    def clean(self):
        if self.is_org_manager and not self.organisation_id:
            raise ValidationError(
                {"is_org_manager": "Only a member of an organisation can be its manager."}
            )


class Service(models.Model):
    """Something TechCare sells, shown on the public website's price list. Admins edit
    these in /admin/; bookings and quotes will use them too."""

    class Audience(models.TextChoices):
        BUSINESS = "business", "Businesses"
        HOME = "home", "Homes"
        BOTH = "both", "Businesses and homes"

    class Delivery(models.TextChoices):
        ONSITE = "onsite", "On site"
        REMOTE = "remote", "Remote"
        EITHER = "either", "On site or remote"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    summary = models.CharField(max_length=200, help_text="One line, shown on the home page.")
    description = models.TextField(blank=True, help_text="Shown on the services page.")
    audience = models.CharField(max_length=10, choices=Audience.choices, default=Audience.BOTH)
    delivery = models.CharField(max_length=10, choices=Delivery.choices, default=Delivery.EITHER)
    price_from = models.DecimalField(
        max_digits=8, decimal_places=2, help_text="Starting price in AUD, including GST."
    )
    price_unit = models.CharField(max_length=40, help_text='e.g. "per visit", "per user / month".')
    is_active = models.BooleanField(default=True, help_text="Untick to hide it from the website.")
    sort_order = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers come first.")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def price_label(self):
        """'From $129 per visit' (cents only shown when there are some)."""
        whole = self.price_from == self.price_from.to_integral_value()
        amount = f"{self.price_from:,.0f}" if whole else f"{self.price_from:,.2f}"
        return f"From ${amount} {self.price_unit}"

    @property
    def for_business(self):
        return self.audience in (self.Audience.BUSINESS, self.Audience.BOTH)

    @property
    def for_home(self):
        return self.audience in (self.Audience.HOME, self.Audience.BOTH)


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
        """The tickets a user may see. Every page that shows or changes a ticket uses this.

        TechCare staff: every ticket. Organisation managers: their organisation's tickets
        and their own. Everyone else: only the tickets they raised.
        """
        if user.is_staff:
            return self
        if roles.role_of(user) == roles.ORG_MANAGER:
            return self.filter(
                models.Q(organisation=roles.organisation_of(user)) | models.Q(requester=user)
            )
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
    # Copied from the requester when the ticket is raised, so the ticket stays with that
    # organisation even if the person later moves on.
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True, related_name="tickets"
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
        if self._state.adding and self.organisation_id is None:
            self.organisation = roles.organisation_of(self.requester)

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
