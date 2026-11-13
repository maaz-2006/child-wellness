from django.urls import path

from . import views

app_name = "children"

urlpatterns = [
    path("<int:child_id>/", views.ChildDetailView.as_view(), name="detail"),
]
