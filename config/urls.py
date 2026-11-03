from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    # The logged-in customer and staff portal.
    path("portal/", include("helpdesk.urls")),
    # The public TechCare website: home page and services.
    path("", include("website.urls")),
]
