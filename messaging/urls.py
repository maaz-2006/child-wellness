from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("messages/", views.ThreadListView.as_view(), name="inbox"),
    path("messages/<int:pk>/", views.ThreadDetailView.as_view(), name="thread"),
    path(
        "children/<int:child_id>/messages/new/",
        views.ThreadCreateView.as_view(),
        name="new_thread",
    ),
]
