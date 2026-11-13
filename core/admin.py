from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import AuditLog, School, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "display_name", "role", "is_active", "is_staff", "last_login")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("role", "first_name")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Platform", {"fields": ("role", "must_change_password")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Platform", {"fields": ("role", "first_name", "last_name", "email")}),
    )


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "timezone", "created_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only by design: the audit trail must not be editable, including by
    the administrator whose actions it records."""

    list_display = ("created_at", "actor", "actor_role", "action", "resource_type", "child_id", "ip_address")
    list_filter = ("action", "actor_role", "resource_type")
    search_fields = ("actor__username", "resource_type", "resource_id")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
