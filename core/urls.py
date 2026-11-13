from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.AuditedLoginView.as_view(), name="login"),
    path("logout/", views.AuditedLogoutView.as_view(), name="logout"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("admin/permissions/", views.PermissionMatrixView.as_view(), name="permission_matrix"),
    path("healthz/", views.healthz, name="healthz"),
]
