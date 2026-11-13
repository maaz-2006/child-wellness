from django.contrib import admin

from .models import Child, ConsentRecord, Guardianship, Mentorship


class GuardianshipInline(admin.TabularInline):
    model = Guardianship
    extra = 1
    autocomplete_fields = ("parent",)
    fields = ("parent", "label", "is_primary", "is_active", "consent_granted_at", "consent_version")


class MentorshipInline(admin.TabularInline):
    model = Mentorship
    extra = 1
    autocomplete_fields = ("mentor",)
    fields = ("mentor", "role", "subject", "is_active", "active_from", "active_to")


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ("avatar", "full_name", "year_group", "age", "is_active", "school")
    list_filter = ("is_active", "year_group", "school")
    search_fields = ("first_name", "last_name")
    inlines = [GuardianshipInline, MentorshipInline]
    fieldsets = (
        ("Identity (minimum necessary)", {"fields": ("first_name", "last_name", "avatar", "year_group")}),
        ("Context", {"fields": ("date_of_birth", "school", "user", "is_active")}),
    )


@admin.register(Guardianship)
class GuardianshipAdmin(admin.ModelAdmin):
    list_display = ("parent", "child", "label", "is_primary", "is_active", "has_consent")
    list_filter = ("is_active", "label")
    search_fields = ("parent__username", "child__first_name", "child__last_name")
    autocomplete_fields = ("parent", "child")

    @admin.display(boolean=True, description="Consent on file")
    def has_consent(self, obj):
        return obj.has_consent


@admin.register(Mentorship)
class MentorshipAdmin(admin.ModelAdmin):
    list_display = ("mentor", "child", "role", "subject", "is_active", "active_from", "active_to")
    list_filter = ("is_active", "role")
    search_fields = ("mentor__username", "child__first_name", "child__last_name")
    autocomplete_fields = ("mentor", "child")


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ("child", "guardian", "consent_type", "version", "granted_at", "revoked_at")
    list_filter = ("consent_type", "version")
    search_fields = ("child__first_name", "child__last_name", "guardian__username")
    autocomplete_fields = ("child", "guardian")
