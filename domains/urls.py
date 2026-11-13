from django.urls import path

from . import views

app_name = "domains"

urlpatterns = [
    # The child's own check-in. No child id in the URL: it is resolved from the
    # session, so there is nothing to tamper with.
    path("checkin/", views.ChildCheckinView.as_view(), name="checkin"),
    # Adult observation is more specific than the generic list route, so it is
    # declared first.
    path(
        "children/<int:child_id>/emotional/observe/",
        views.EmotionalObservationCreateView.as_view(),
        name="emotional_observe",
    ),
    path(
        "children/<int:child_id>/<slug:domain_key>/",
        views.DomainListView.as_view(),
        name="list",
    ),
]
