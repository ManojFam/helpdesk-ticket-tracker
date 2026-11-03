from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from helpdesk.models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    """Every user gets a profile as soon as they are created, however they are created
    (admin, createsuperuser, seed_demo, and later self sign-up)."""
    if created:
        Profile.objects.get_or_create(user=instance)
