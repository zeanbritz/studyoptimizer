from django import forms

from learning.models import Subject

from .models import AssessmentEvent


class AssessmentEventForm(forms.ModelForm):
    class Meta:
        model = AssessmentEvent
        fields = ("date", "subject", "kind", "title")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "title": forms.TextInput(attrs={"placeholder": "e.g. Chapter 4 or Paper 1"}),
        }
        labels = {"kind": "Type", "title": "Description"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = Subject.objects.filter(user=user).order_by("name", "pk")
        self.fields["subject"].empty_label = "Choose a subject"
        self.fields["date"].input_formats = ["%Y-%m-%d"]
