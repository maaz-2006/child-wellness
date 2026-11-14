from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path(
        "cohort/wellness/",
        views.CohortWellnessView.as_view(),
        name="cohort_wellness",
    ),
]
