from django.urls import path

from analytics.views import ChildWellnessView

from . import views

app_name = "children"

urlpatterns = [
    path("<int:child_id>/", views.ChildDetailView.as_view(), name="detail"),
    # The trend is a view of the child, so it lives under the child's prefix.
    # Keeping it here also stops the generic domain route (<slug:domain_key>)
    # from matching "wellness" and returning a 404 from the domain registry.
    path(
        "<int:child_id>/wellness/",
        ChildWellnessView.as_view(),
        name="wellness",
    ),
]
