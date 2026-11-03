from django.urls import path

from website import views

urlpatterns = [
    path("", views.home, name="site_home"),
    path("services/", views.services, name="site_services"),
]
