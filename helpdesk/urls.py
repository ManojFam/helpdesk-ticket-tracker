from django.urls import path

from helpdesk import booking_views, views

urlpatterns = [
    path("", views.portal, name="portal"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/comment/", views.ticket_comment, name="ticket_comment"),
    path("tickets/<int:pk>/update/", views.ticket_update, name="ticket_update"),
    path("bookings/", booking_views.booking_list, name="booking_list"),
    path("bookings/new/", booking_views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/", booking_views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/confirm/", booking_views.booking_confirm, name="booking_confirm"),
    path("bookings/<int:pk>/complete/", booking_views.booking_complete, name="booking_complete"),
    path("bookings/<int:pk>/cancel/", booking_views.booking_cancel, name="booking_cancel"),
    path("schedule/", booking_views.schedule, name="schedule"),
    path("kb/", views.article_list, name="article_list"),
    path("kb/<slug:slug>/", views.article_detail, name="article_detail"),
]
