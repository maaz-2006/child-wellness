from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("alerts/", views.AlertQueueView.as_view(), name="queue"),
    path("alerts/family/", views.GuardianAlertListView.as_view(), name="family"),
    path("alerts/<int:pk>/", views.AlertDetailView.as_view(), name="detail"),
    path("cohort/alerts/", views.CohortAlertView.as_view(), name="cohort"),
]
