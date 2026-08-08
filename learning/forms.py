from django import forms
from .models import KnowledgeUnit, Formula


class FormulaForm(forms.Form):

    title = forms.CharField(
        max_length=255,
        label="Formula name"
    )

    expression = forms.CharField(
        widget=forms.Textarea,
        label="Formula"
    )

    purpose = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="What does this formula do?"
    )

    when_to_use = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="When should I use it?"
    )

    difficulty = forms.IntegerField(
        min_value=1,
        max_value=5,
        initial=1,
        label="Difficulty"
    )

    estimated_minutes = forms.IntegerField(
        min_value=1,
        initial=2,
        label="Estimated study time (minutes)"
    )

    variable_1_symbol = forms.CharField(
    max_length=50,
    required=False,
    label="Variable 1"
)

variable_1_meaning = forms.CharField(
    max_length=255,
    required=False,
    label="Variable 1 meaning"
)

variable_2_symbol = forms.CharField(
    max_length=50,
    required=False,
    label="Variable 2"
)

variable_2_meaning = forms.CharField(
    max_length=255,
    required=False,
    label="Variable 2 meaning"
)