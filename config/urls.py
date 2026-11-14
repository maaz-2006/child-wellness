"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Kito administration"
admin.site.site_title = "Kito admin"
admin.site.index_title = "Platform configuration"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
    path("children/", include("children.urls")),
    path("", include("alerts.urls")),
    path("", include("feedback.urls")),
    path("", include("domains.urls")),
    path("", include("analytics.urls")),
]

# Custom error pages (DEBUG=False only, but defined unconditionally so the
# templates are exercised in development via the 403/404 test cases).
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
