from django.contrib import admin

from .models import Alert, AlertEvent


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    """Read-only. Alerts are worked in the application, with an audit trail."""

    list_display = ("child", "tier", "status", "rule_key", "opened_on", "assigned_to")
    list_filter = ("tier", "status")
    search_fields = ("child__first_name", "child__last_name", "rule_key")
    readonly_fields = [field.name for field in Alert._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    """Visibly append-only: no add, change or delete from the admin."""

    list_display = ("alert", "kind", "actor", "created_at")
    list_filter = ("kind",)
    readonly_fields = [field.name for field in AlertEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
