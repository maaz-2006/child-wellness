from django.contrib import admin

from .models import ModelReport


@admin.register(ModelReport)
class ModelReportAdmin(admin.ModelAdmin):
    """Read-only. The report has no child-level predictions to expose."""

    list_display = ("as_of", "algorithm", "status", "n_examples", "n_children", "created_at")
    list_filter = ("status", "algorithm")
    readonly_fields = [field.name for field in ModelReport._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
