# Data migration: users created before profiles existed get one now. New users get theirs
# from the signal in helpdesk/signals.py (signals do not run inside migrations).

from django.conf import settings
from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Profile = apps.get_model("helpdesk", "Profile")
    for user in User.objects.filter(profile__isnull=True):
        Profile.objects.create(user=user)


class Migration(migrations.Migration):
    dependencies = [
        ("helpdesk", "0002_organisations_and_profiles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Going backwards needs no action: 0002 drops the profile table.
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
    ]
