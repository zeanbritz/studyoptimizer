from django.contrib import admin

from .models import AssessmentEvent


@admin.register(AssessmentEvent)
class AssessmentEventAdmin(admin.ModelAdmin):
    list_display = ("date", "subject", "kind", "title")
    list_filter = ("kind", "date")
    search_fields = ("subject__name", "title")
