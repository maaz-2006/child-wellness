from django.contrib import admin

from .models import PulseResponse


@admin.register(PulseResponse)
class PulseResponseAdmin(admin.ModelAdmin):
    """Read-only in the admin.

    The pulse is edited by the guardian who wrote it, through the pulse form. The
    admin is for inspecting the data model during development, not for silently
    rewriting a family's account of their week.
    """

    list_display = ("child", "guardian", "week_start", "wellbeing", "support")
    list_filter = ("week_start", "wellbeing")
    search_fields = ("child__first_name", "child__last_name", "guardian__username")
    readonly_fields = [field.name for field in PulseResponse._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
