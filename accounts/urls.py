from allauth.account import views as account_views
from django.urls import path

from .plan_views import my_plan
from .checkout_views import cancel_test_membership, start_test_checkout, test_checkout_return
from .webhook_views import paystack_test_webhook


urlpatterns = [
    path("payments/paystack/test/start/", start_test_checkout, name="start_test_checkout"),
    path("payments/paystack/test/return/", test_checkout_return, name="test_checkout_return"),
    path("payments/paystack/test/cancel/", cancel_test_membership, name="cancel_test_membership"),
    path("payments/paystack/test/webhook/", paystack_test_webhook, name="paystack_test_webhook"),
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
