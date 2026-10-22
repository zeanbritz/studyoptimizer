from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email")


class AdultSignupForm(SignupForm):
    """Require an adult's self-confirmation on both allauth signup routes."""

    age_confirmed = forms.BooleanField(
        required=True,
        label="I confirm I am 18 years or older.",
        help_text="StudiGarden is for adults aged 18 or older.",
        error_messages={
            "required": "You must confirm you are 18 or older to create an account.",
        },
        widget=forms.CheckboxInput(
            attrs={
                "aria-describedby": "age-confirmation-help age-confirmation-errors",
            },
        ),
    )
