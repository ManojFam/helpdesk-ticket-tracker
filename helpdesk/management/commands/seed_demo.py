"""Fills an empty database with fictional demo data: users, categories, knowledge-base
articles and tickets in every SLA state. For local demos only.

    python manage.py seed_demo                    # prints a generated password
    python manage.py seed_demo --password "..."   # choose the password
    python manage.py seed_demo --reset            # wipe demo data first
"""

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from helpdesk.models import Article, Category, Comment, Ticket

# username, first name, last name, is_staff, is_superuser
USERS = [
    ("helpdesk.admin", "Helpdesk", "Admin", True, True),
    ("jordan.lee", "Jordan", "Lee", True, False),
    ("riley.morgan", "Riley", "Morgan", True, False),
    ("sam.taylor", "Sam", "Taylor", False, False),
    ("casey.nguyen", "Casey", "Nguyen", False, False),
    ("alex.chen", "Alex", "Chen", False, False),
]

CATEGORIES = [
    "Accounts & access",
    "Email & Teams",
    "Hardware",
    "Network & Wi-Fi",
    "Printing",
    "Software",
]

# title, category, summary, body
ARTICLES = [
    (
        "Reset your password",
        "Accounts & access",
        "Change a forgotten or expired password yourself in a few minutes.",
        "1. Go to the self-service password reset page from any browser.\n"
        "2. Enter your work email address and complete the code sent to your phone.\n"
        "3. Choose a new password: at least 12 characters, not used before.\n"
        "4. On a work laptop, connect to the office network or VPN, then lock and unlock "
        "(Windows + L) so Windows picks up the new password.\n\n"
        "Phones and tablets will ask for the new password the next time they check email.",
    ),
    (
        "Set up multi-factor authentication (MFA)",
        "Accounts & access",
        "Register the authenticator app so you can sign in from anywhere.",
        "1. Install Microsoft Authenticator from the App Store or Google Play.\n"
        "2. On a computer, sign in to your account security page and choose Add sign-in method.\n"
        "3. Pick Authenticator app and scan the QR code with your phone.\n"
        "4. Approve the test notification.\n\n"
        "Add a second method (such as a phone number) in case you lose your phone.",
    ),
    (
        "Connect to the staff Wi-Fi",
        "Network & Wi-Fi",
        "Join the secure staff network on a laptop or phone.",
        "1. Choose the STAFF network (not GUEST).\n"
        "2. Sign in with your work email address and password.\n"
        "3. If asked about a certificate, check it is issued to the company's Wi-Fi server, then accept.\n\n"
        "If it keeps failing after a password change, choose Forget this network and connect again.",
    ),
    (
        "Connect to the VPN from home",
        "Network & Wi-Fi",
        "Reach shared drives and internal systems when you are off site.",
        "1. Open the VPN client from the Start menu.\n"
        "2. Sign in with your work account and approve the MFA prompt.\n"
        "3. Wait for Connected, then open File Explorer to reach your drives.\n\n"
        "If it will not connect: check your home internet works, restart the laptop and try again.",
    ),
    (
        "Map a shared network drive",
        "Network & Wi-Fi",
        "Get the S: or other shared drive back in File Explorer.",
        "1. Open File Explorer and right-click This PC, then choose Map network drive.\n"
        "2. Pick the drive letter and type the folder path from your team, e.g. \\\\fileserver\\shared.\n"
        "3. Tick Reconnect at sign-in and click Finish.\n\n"
        "Off site, connect to the VPN first.",
    ),
    (
        "Fix a stuck print queue",
        "Printing",
        "Clear jobs that will not print or delete.",
        "1. Open Settings > Bluetooth & devices > Printers & scanners and select the printer.\n"
        "2. Open the print queue and cancel every job.\n"
        "3. Turn the printer off and on again, and restart your computer.\n"
        "4. Print a test page.\n\n"
        "Still stuck? Raise a ticket with the printer name (on the sticker on the front).",
    ),
    (
        "Clear the Microsoft Teams cache",
        "Email & Teams",
        "Fixes Teams that will not load, shows old messages or keeps signing out.",
        "1. Quit Teams completely: right-click the icon near the clock and choose Quit.\n"
        "2. Press Windows + R, type %localappdata%\\Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache "
        "and press Enter.\n"
        "3. Delete everything in that folder.\n"
        "4. Start Teams again and sign in.\n\n"
        "Your chats and files are stored online and are not affected.",
    ),
    (
        "Outlook keeps asking for your password",
        "Email & Teams",
        "Stop repeated password prompts after a password change.",
        "1. Close Outlook.\n"
        "2. Open Credential Manager from the Start menu, choose Windows Credentials and remove "
        "entries that mention Office or Outlook.\n"
        "3. Open Outlook and sign in once with your new password.\n\n"
        "If prompts continue, check your password works on the web version of Outlook.",
    ),
    (
        "Free up disk space on your laptop",
        "Hardware",
        "Make room when Windows warns that the disk is nearly full.",
        "1. Open Settings > System > Storage and turn on Storage Sense.\n"
        "2. Click Temporary files, tick everything except Downloads, and remove them.\n"
        "3. Empty the Recycle Bin.\n"
        "4. Set OneDrive folders to Free up space so files stay online until you open them.",
    ),
    (
        "Report a phishing email",
        "Email & Teams",
        "What to do with a suspicious email, and what to do if you clicked a link.",
        "1. Do not click links, open attachments or reply.\n"
        "2. In Outlook, choose Report > Report phishing.\n"
        "3. If you entered your password on a suspicious page, reset your password straight away "
        "and raise a P2 ticket so IT can check your account.",
    ),
]

# title, category, priority, age in hours, status, responded after (h), resolved after (h),
# assignee, requester. Ages are chosen so every SLA state shows up on the dashboard.
TICKETS = [
    (
        "Wi-Fi down for everyone in Building B",
        "Network & Wi-Fi",
        1,
        5,
        "in_progress",
        0.2,
        None,
        "jordan.lee",
        "sam.taylor",
    ),
    (
        "Student system not loading for anyone",
        "Software",
        1,
        3.3,
        "in_progress",
        0.3,
        None,
        "riley.morgan",
        "casey.nguyen",
    ),
    (
        "Projector in Room 204 not detecting laptops",
        "Hardware",
        2,
        2,
        "new",
        None,
        None,
        None,
        "alex.chen",
    ),
    (
        "S: drive missing after password change",
        "Network & Wi-Fi",
        2,
        7,
        "in_progress",
        0.5,
        None,
        "jordan.lee",
        "sam.taylor",
    ),
    (
        "New starter needs laptop and accounts for Monday",
        "Accounts & access",
        3,
        20,
        "in_progress",
        1,
        None,
        "riley.morgan",
        "casey.nguyen",
    ),
    (
        "Outlook keeps asking for my password",
        "Email & Teams",
        3,
        3,
        "waiting",
        0.8,
        None,
        "jordan.lee",
        "alex.chen",
    ),
    (
        "Level 2 printer printing blank pages",
        "Printing",
        3,
        30,
        "in_progress",
        2,
        None,
        None,
        "sam.taylor",
    ),
    (
        "Access to the Finance shared mailbox",
        "Accounts & access",
        3,
        1,
        "new",
        None,
        None,
        None,
        "casey.nguyen",
    ),
    ("Second monitor for my desk", "Hardware", 4, 10, "new", None, None, None, "alex.chen"),
    (
        "Laptop keyboard keys sticking",
        "Hardware",
        4,
        80,
        "in_progress",
        6,
        None,
        "riley.morgan",
        "sam.taylor",
    ),
    (
        "Teams camera not working in meetings",
        "Email & Teams",
        3,
        50,
        "resolved",
        1,
        10,
        "jordan.lee",
        "casey.nguyen",
    ),
    (
        "Install Python 3.13 on the lab PCs",
        "Software",
        3,
        70,
        "resolved",
        2,
        30,
        "riley.morgan",
        "alex.chen",
    ),
    (
        "Payroll export fails with access denied",
        "Software",
        2,
        30,
        "closed",
        0.5,
        6,
        "jordan.lee",
        "sam.taylor",
    ),
    (
        "Update the email signature template",
        "Email & Teams",
        4,
        100,
        "closed",
        4,
        48,
        "riley.morgan",
        "casey.nguyen",
    ),
]

# Older resolved tickets so the 30-day SLA compliance figure has something to measure.
HISTORY = [
    ("Locked out after too many sign-in attempts", "Accounts & access", 2, 3),
    ("VPN disconnects every few minutes", "Network & Wi-Fi", 2, 6),
    ("Excel crashes when opening a shared workbook", "Software", 3, 20),
    ("Toner low on reception printer", "Printing", 4, 30),
    ("Phishing email received - please check", "Email & Teams", 2, 2),
    ("Laptop will not charge", "Hardware", 2, 12),
    ("Request Adobe Acrobat licence", "Software", 4, 60),
    ("Cannot join Wi-Fi on new phone", "Network & Wi-Fi", 3, 28),
    ("Shared calendar not updating", "Email & Teams", 3, 9),
    ("Monitor flickering", "Hardware", 3, 16),
]


class Command(BaseCommand):
    help = "Create fictional demo users, knowledge-base articles and tickets (local demos only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="password for every demo user (default: generated)")
        parser.add_argument("--reset", action="store_true", help="delete existing demo data first")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["reset"]:
            Comment.objects.all().delete()
            Ticket.objects.all().delete()
            Article.objects.all().delete()
            Category.objects.all().delete()
            User.objects.filter(username__in=[u[0] for u in USERS]).delete()
        elif Ticket.objects.exists():
            raise CommandError("The database already has tickets. Use --reset to replace them.")

        password = options["password"] or secrets.token_urlsafe(12)
        users = {}
        for username, first, last, is_staff, is_superuser in USERS:
            user = User(
                username=username,
                first_name=first,
                last_name=last,
                email=f"{username}@example.com",
                is_staff=is_staff,
                is_superuser=is_superuser,
            )
            user.set_password(password)
            user.save()
            users[username] = user

        categories = {name: Category.objects.create(name=name) for name in CATEGORIES}

        for title, category, summary, body in ARTICLES:
            Article.objects.create(
                title=title,
                slug=slugify(title),
                category=categories[category],
                summary=summary,
                body=body,
                author=users["jordan.lee"],
            )

        now = timezone.now()
        for (
            title,
            category,
            priority,
            age,
            status,
            responded,
            resolved,
            assignee,
            requester,
        ) in TICKETS:
            created = now - timedelta(hours=age)
            ticket = Ticket(
                title=title,
                description=f"{title}.\n\nRaised through the self-service portal.",
                category=categories[category],
                priority=priority,
                status=status,
                requester=users[requester],
                assignee=users.get(assignee),
                created_at=created,
                resolved_at=created + timedelta(hours=resolved) if resolved else None,
            )
            ticket.save()
            if responded is not None:
                ticket.add_comment(
                    users[assignee or "jordan.lee"],
                    "Thanks for reporting this - I'm looking into it now.",
                    at=created + timedelta(hours=responded),
                )
            if status == "waiting":
                ticket.add_comment(
                    users[assignee],
                    "Can you tell me which device this happens on (laptop or phone)?",
                    at=created + timedelta(hours=responded + 0.5),
                )
            if priority == 1:
                ticket.add_comment(
                    users[assignee],
                    "Vendor case opened; waiting for their engineer to call back.",
                    internal=True,
                    at=created + timedelta(hours=responded + 1),
                )

        for days_ago, (title, category, priority, hours_to_fix) in enumerate(HISTORY, start=2):
            created = now - timedelta(days=days_ago * 2)
            ticket = Ticket.objects.create(
                title=title,
                description=f"{title}.",
                category=categories[category],
                priority=priority,
                status=Ticket.Status.CLOSED,
                requester=users[USERS[3 + days_ago % 3][0]],
                assignee=users["jordan.lee" if days_ago % 2 else "riley.morgan"],
                created_at=created,
                resolved_at=created + timedelta(hours=hours_to_fix),
            )
            ticket.add_comment(ticket.assignee, "On it.", at=created + timedelta(minutes=20))

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(USERS)} users, {len(ARTICLES)} articles and "
                f"{Ticket.objects.count()} tickets."
            )
        )
        self.stdout.write(
            "Log in as jordan.lee (IT staff), sam.taylor (requester) or helpdesk.admin."
        )
        if not options["password"]:
            self.stdout.write(f"Password for all demo users: {password}")
