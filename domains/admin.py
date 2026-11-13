from django.contrib import admin

from .models import AcademicRecord, AttendanceRecord, EmotionalCheckin, HabitLog, SocialObservation


class DomainEntryAdmin(admin.ModelAdmin):
    """Shared admin behaviour: the child and date are what staff filter by."""

    list_filter = ("source", "note_visibility")
    search_fields = ("child__first_name", "child__last_name")
    autocomplete_fields = ("child",)
    date_hierarchy = "occurred_on"
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmotionalCheckin)
class EmotionalCheckinAdmin(DomainEntryAdmin):
    list_display = ("child", "occurred_on", "mood", "energy", "source")
    list_filter = DomainEntryAdmin.list_filter + ("mood",)


@admin.register(AcademicRecord)
class AcademicRecordAdmin(DomainEntryAdmin):
    list_display = ("child", "subject", "kind", "score", "max_score", "occurred_on")
    list_filter = DomainEntryAdmin.list_filter + ("kind", "subject")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("child", "occurred_on", "status")
    list_filter = ("status",)
    search_fields = ("child__first_name", "child__last_name")
    autocomplete_fields = ("child",)


@admin.register(SocialObservation)
class SocialObservationAdmin(DomainEntryAdmin):
    list_display = ("child", "dimension", "rating", "context", "occurred_on")
    list_filter = DomainEntryAdmin.list_filter + ("dimension", "context")


@admin.register(HabitLog)
class HabitLogAdmin(DomainEntryAdmin):
    list_display = ("child", "occurred_on", "sleep_hours", "activity_minutes", "screen_minutes")
    list_filter = DomainEntryAdmin.list_filter
