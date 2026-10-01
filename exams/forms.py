from django import forms

from learning.models import Subject

from .models import AssessmentEvent


class AssessmentEventForm(forms.ModelForm):
    class Meta:
        model = AssessmentEvent
        fields = ("date", "subject", "kind", "title", "reminder_days")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "title": forms.TextInput(attrs={"placeholder": "e.g. Chapter 4 or Paper 1"}),
            "reminder_days": forms.NumberInput(attrs={"min": "0", "max": "365"}),
        }
        labels = {
            "kind": "Type",
            "title": "Description",
            "reminder_days": "Remind me this many days before",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = Subject.objects.filter(user=user).order_by("name", "pk")
        self.fields["subject"].empty_label = "Choose a subject"
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        # Older forms did not send this field; keep those requests valid.
        self.fields["reminder_days"].required = False

    def clean_reminder_days(self):
        value = self.cleaned_data["reminder_days"]
        if value is not None:
            return value
        return self.instance.reminder_days if self.instance.pk else 3
