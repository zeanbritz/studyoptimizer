from django import forms

from .models import Question


ANSWER_NUMBERS = range(1, 7)


class QuestionForm(forms.ModelForm):
    answer_count = forms.TypedChoiceField(
        label="Number of answers", choices=[(n, n) for n in range(2, 7)], coerce=int,
        initial=2,
    )
    correct = forms.TypedChoiceField(
        label="Correct answer",
        choices=[("", "Choose the correct answer"), *((n, f"Answer {n}") for n in ANSWER_NUMBERS)],
        coerce=int,
    )

    class Meta:
        model = Question
        fields = ("prompt", "chapter")
        labels = {"prompt": "Question", "chapter": "Chapter (optional)"}
        widgets = {"prompt": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for number in ANSWER_NUMBERS:
            self.fields[f"answer_{number}"] = forms.CharField(
                label=f"Answer {number}", max_length=1000, required=False,
                widget=forms.Textarea(attrs={"rows": 2}),
            )
        if self.instance.pk:
            self.initial["answer_count"] = len(self.instance.choices)
            self.initial["correct"] = self.instance.correct_index + 1
            for number, answer in enumerate(self.instance.choices, start=1):
                self.initial[f"answer_{number}"] = answer

    @property
    def answer_fields(self):
        return [self[f"answer_{number}"] for number in ANSWER_NUMBERS]

    def clean(self):
        data = super().clean()
        count = data.get("answer_count")
        if count is None:
            return data

        seen = set()
        choices = []
        for number in range(1, count + 1):
            field = f"answer_{number}"
            choice = data.get(field, "")
            key = " ".join(choice.split()).casefold()
            if not choice:
                if field not in self.errors:
                    self.add_error(field, "Enter an answer.")
            elif key in seen:
                self.add_error(field, "Use a different answer.")
            seen.add(key)
            choices.append(choice)

        correct = data.get("correct")
        if correct is not None and correct > count:
            self.add_error("correct", "Choose one of the answers shown.")
        self.instance.choices = choices
        if correct is not None:
            self.instance.correct_index = correct - 1
        return data


class QuizSetupForm(forms.Form):
    chapter = forms.ChoiceField(required=False)
    minutes = forms.IntegerField(
        label="Time limit in minutes (optional)", required=False, min_value=1,
        max_value=1440, widget=forms.NumberInput(attrs={"placeholder": "No time limit"}),
    )

    def __init__(self, *args, chapters, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chapter"].choices = [("", "All chapters"), *((name, name) for name in chapters)]
