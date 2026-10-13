from django.contrib import admin

from .models import BetaInvite


@admin.register(BetaInvite)
class BetaInviteAdmin(admin.ModelAdmin):
    list_display = (
        "slot",
        "invite_status",
        "claimed_by",
        "claimed_at",
    )
    list_display_links = None
    list_select_related = ("claimed_by",)
    ordering = ("slot",)

    fields = (
        "slot",
        "invite_status",
        "is_active",
        "claimed_by",
        "claimed_at",
        "created_at",
    )
    readonly_fields = (
        "slot",
        "invite_status",
        "is_active",
        "claimed_by",
        "claimed_at",
        "created_at",
    )

    @admin.display(description="Status")
    def invite_status(self, obj):
        if obj.claimed_by_id:
            return "Used"
        if not obj.is_active:
            return "Paused"
        return "Unused (legacy)"

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
