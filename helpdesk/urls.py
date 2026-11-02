from django.urls import path

from helpdesk import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/comment/", views.ticket_comment, name="ticket_comment"),
    path("tickets/<int:pk>/update/", views.ticket_update, name="ticket_update"),
    path("kb/", views.article_list, name="article_list"),
    path("kb/<slug:slug>/", views.article_detail, name="article_detail"),
]
