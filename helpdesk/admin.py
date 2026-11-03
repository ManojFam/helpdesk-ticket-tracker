from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from helpdesk import roles
from helpdesk.models import Article, Category, Comment, Organisation, Profile, Ticket

User = get_user_model()


class MemberInline(admin.TabularInline):
    """People in an organisation. Add people from the Users page (Profile section);
    here you can see them and change who the managers are."""

    model = Profile
    fields = ["user", "is_org_manager", "phone"]
    readonly_fields = ["user"]
    extra = 0
    can_delete = False
    verbose_name = "member"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "member_count", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    inlines = [MemberInline]

    @admin.display(description="members")
    def member_count(self, obj):
        return obj.members.count()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ["organisation", "is_org_manager", "phone"]


# Django's own user admin, with the profile (organisation, manager flag) on the same page.
admin.site.unregister(User)


@admin.register(User)
class TechCareUserAdmin(UserAdmin):
    list_display = ["username", "first_name", "last_name", "role", "organisation", "is_active"]
    list_filter = ["is_staff", "is_superuser", "profile__organisation", "is_active"]
    list_select_related = ["profile__organisation"]

    def get_inlines(self, request, obj):
        # On "Add user" the signal creates the profile when the user is saved, so the
        # profile section only appears afterwards, on the change page.
        return [ProfileInline] if obj else []

    @admin.display(description="role")
    def role(self, obj):
        return roles.LABELS[roles.role_of(obj)]

    @admin.display(description="organisation")
    def organisation(self, obj):
        return roles.organisation_of(obj) or "-"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ["author", "body", "is_internal", "created_at"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "organisation",
        "priority",
        "status",
        "requester",
        "assignee",
        "resolution_due_at",
    ]
    list_filter = ["status", "priority", "organisation", "category"]
    search_fields = ["title", "description", "requester__username"]
    readonly_fields = ["response_due_at", "resolution_due_at", "updated_at"]
    inlines = [CommentInline]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "is_published", "updated_at"]
    list_filter = ["is_published", "category"]
    search_fields = ["title", "summary", "body"]
    prepopulated_fields = {"slug": ["title"]}
