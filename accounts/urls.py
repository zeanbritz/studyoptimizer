from allauth.account import views as account_views
from django.urls import path

from .views import BetaSignupView


urlpatterns = [
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
        BetaSignupView.as_view(),
        name="register",
    ),
]