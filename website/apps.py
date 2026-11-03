from django.apps import AppConfig


class WebsiteConfig(AppConfig):
    """The public TechCare website. It has no tables of its own: it shows the services
    and SLA promises that live in the helpdesk app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "website"
