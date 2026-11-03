from django.apps import AppConfig


class HelpdeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "helpdesk"

    def ready(self):
        # Connects the signal that creates a Profile for every new user.
        from helpdesk import signals  # noqa: F401
