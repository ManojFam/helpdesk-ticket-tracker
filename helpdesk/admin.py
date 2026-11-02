from django.contrib import admin

from helpdesk.models import Article, Category, Comment, Ticket


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
        "priority",
        "status",
        "requester",
        "assignee",
        "resolution_due_at",
    ]
    list_filter = ["status", "priority", "category"]
    search_fields = ["title", "description", "requester__username"]
    readonly_fields = ["response_due_at", "resolution_due_at", "updated_at"]
    inlines = [CommentInline]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "is_published", "updated_at"]
    list_filter = ["is_published", "category"]
    search_fields = ["title", "summary", "body"]
    prepopulated_fields = {"slug": ["title"]}
