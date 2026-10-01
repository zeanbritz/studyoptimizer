from django.contrib import admin

from .models import AssessmentEvent


@admin.register(AssessmentEvent)
class AssessmentEventAdmin(admin.ModelAdmin):
    list_display = ("date", "subject", "kind", "title", "reminder_days", "completed_at")
    list_filter = ("kind", "date", "completed_at")
    search_fields = ("subject__name", "title")
