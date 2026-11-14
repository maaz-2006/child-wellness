from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path(
        "children/<int:child_id>/pulse/",
        views.PulseCreateView.as_view(),
        name="pulse",
    ),
    path(
        "children/<int:child_id>/pulse/history/",
        views.PulseHistoryView.as_view(),
        name="pulse_history",
    ),
    path("cohort/pulse/", views.PulseCohortView.as_view(), name="cohort_pulse"),
]
