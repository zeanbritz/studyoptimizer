from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import BetaInvite


@admin.register(BetaInvite)
class BetaInviteAdmin(admin.ModelAdmin):
    list_display = (
        "slot",
        "invite_status",
        "claimed_by",
        "claimed_at",
        "invite_link",
    )
    list_display_links = ("slot",)
    list_select_related = ("claimed_by",)
    ordering = ("slot",)

    fields = (
        "slot",
        "invite_status",
        "is_active",
        "invite_link",
        "claimed_by",
        "claimed_at",
        "created_at",
    )
    readonly_fields = (
        "slot",
        "invite_status",
        "invite_link",
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
        return "Available"

    @admin.display(description="Invitation link")
    def invite_link(self, obj):
        if obj.claimed_by_id or not obj.is_active:
            return "—"

        url = f"{reverse('register')}?invite={obj.token}"

        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">'
            "Open / copy invitation"
            "</a>",
            url,
        )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False