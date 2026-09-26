from django.contrib import admin

from .models import BetaFeedback


@admin.register(BetaFeedback)
class BetaFeedbackAdmin(admin.ModelAdmin):
    list_display = ("category", "user", "status", "created_at", "page_path")
    list_editable = ("status",)
    list_filter = ("category", "status", "created_at")
    search_fields = ("message", "user__username", "user__email")
    readonly_fields = ("user", "category", "message", "page_path", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")