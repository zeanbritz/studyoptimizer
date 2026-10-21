from django.contrib import admin

from .models import BetaInvite, PaystackWebhookReceipt, StudyRefund


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


@admin.register(PaystackWebhookReceipt)
class PaystackWebhookReceiptAdmin(admin.ModelAdmin):
    list_display = ("event_type", "mode", "received_at", "processing_state")
    list_filter = ("mode", "event_type", "processing_status")
    readonly_fields = ("mode", "event_type", "payload_sha256", "snapshot", "received_at", "processed_at", "processing_state", "attempt_count", "next_attempt_at", "last_result")
    fields = readonly_fields
    actions = None

    @admin.display(description="Processing")
    def processing_state(self, obj):
        return obj.get_processing_status_display()

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


@admin.register(StudyRefund)
class StudyRefundAdmin(PaystackWebhookReceiptAdmin):
    list_display = ("id", "user", "payment", "status", "amount_cents", "requested_at", "last_result")
    list_filter = ("mode", "status")
    readonly_fields = tuple(field.name for field in StudyRefund._meta.fields)
    fields = readonly_fields
    list_select_related = ("user", "payment")
