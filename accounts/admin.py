from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    BetaInvite,
    PaystackWebhookReceipt,
    StudyPlanChange,
    StudyRefund,
    SupportQuery,
    User,
    UserActivity,
)


class UserActivityInline(admin.TabularInline):
    """Show a student's latest recorded activity on their admin profile."""

    model = UserActivity
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("created_at", "activity_type", "label", "path")
    readonly_fields = fields
    ordering = ("-created_at", "-pk")
    verbose_name = "recent website activity"
    verbose_name_plural = "Recent website activity"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Student accounts with a concise activity profile for support work."""

    list_display = (
        "email",
        "username",
        "date_joined",
        "last_login",
        "login_count",
        "is_active",
        "is_staff",
    )
    list_display_links = ("email",)
    list_filter = ("is_active", "is_staff", "is_superuser", "date_joined")
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login", "login_count", "deleted_at")
    inlines = (UserActivityInline,)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "email")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Account activity",
            {"fields": ("date_joined", "last_login", "login_count")},
        ),
        (
            "StudiGarden access",
            {"fields": ("beta_lifetime_access", "deleted_at")},
        ),
    )


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "activity_type", "label", "path")
    list_filter = ("activity_type", "created_at")
    search_fields = ("user__email", "user__username", "label", "path")
    readonly_fields = ("user", "activity_type", "label", "path", "created_at")
    fields = readonly_fields
    list_select_related = ("user",)
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupportQuery)
class SupportQueryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "category",
        "username",
        "email",
        "status",
        "email_status",
        "created_at",
    )
    list_editable = ("status",)
    list_filter = ("category", "status", "email_status", "created_at")
    search_fields = ("message", "username", "email")
    readonly_fields = (
        "user",
        "username",
        "email",
        "category",
        "message",
        "page_path",
        "email_status",
        "email_attempted_at",
        "created_at",
        "updated_at",
    )
    fields = (
        "status",
        "category",
        "message",
        "user",
        "username",
        "email",
        "page_path",
        "email_status",
        "email_attempted_at",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at", "-pk")
    list_select_related = ("user",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
    list_display = ("id", "user", "payment", "reason", "status", "amount_cents", "requested_at", "last_result")
    list_filter = ("mode", "reason", "status")
    readonly_fields = tuple(field.name for field in StudyRefund._meta.fields)
    fields = readonly_fields
    list_select_related = ("user", "payment")


@admin.register(StudyPlanChange)
class StudyPlanChangeAdmin(PaystackWebhookReceiptAdmin):
    list_display = ("id", "user", "kind", "from_tier", "to_tier", "state", "effective_at", "last_result")
    list_filter = ("kind", "state", "from_tier", "to_tier")
    readonly_fields = tuple(field.name for field in StudyPlanChange._meta.fields)
    fields = readonly_fields
    list_select_related = ("user", "payment", "previous_payment")
