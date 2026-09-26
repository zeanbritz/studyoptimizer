from allauth.account.views import SignupView

from .adapter import InviteUnavailable


class BetaSignupView(SignupView):
    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except InviteUnavailable:
            form.add_error(
                None,
                "This invitation has already been used or is no longer available.",
            )
            return self.form_invalid(form)