from allauth.account import views as account_views
from django.urls import path

from .plan_views import my_plan
from .checkout_views import cancel_test_membership, start_test_checkout, test_checkout_return
from .webhook_views import paystack_test_webhook, paystack_live_webhook
from .live_checkout_views import start_live_checkout, live_checkout_return, cancel_live_plan
from .preview_relay_views import local_preview_webhook
from .refund_views import request_live_refund
from .plan_change_views import change_live_plan, cancel_scheduled_plan
from .support_views import submit_support_query


urlpatterns = [
    path("support/submit/", submit_support_query, name="submit_support_query"),
    path("my-plan/change/<str:tier>/", change_live_plan, name="change_live_plan"),
    path("my-plan/scheduled/<int:change_id>/cancel/", cancel_scheduled_plan, name="cancel_scheduled_plan"),
    path("payments/paystack/refund/", request_live_refund, name="request_live_refund"),
    path("payments/paystack/start/", start_live_checkout, name="start_live_checkout"),
    path("payments/paystack/return/", live_checkout_return, name="live_checkout_return"),
    path("payments/paystack/cancel/", cancel_live_plan, name="cancel_live_plan"),
    path("payments/paystack/webhook/", paystack_live_webhook, name="paystack_live_webhook"),
    path("payments/paystack/test/start/", start_test_checkout, name="start_test_checkout"),
    path("payments/paystack/test/return/", test_checkout_return, name="test_checkout_return"),
    path("payments/paystack/test/cancel/", cancel_test_membership, name="cancel_test_membership"),
    path("payments/paystack/test/webhook/", paystack_test_webhook, name="paystack_test_webhook"),
    path("payments/paystack/test/local-relay/", local_preview_webhook, name="local_preview_webhook"),
    path(
        "login/",
        account_views.LoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        account_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "register/",
        account_views.SignupView.as_view(),
        name="register",
    ),
    path(
        "my-plan/",
        my_plan,
        name="my_plan",
    ),
]
