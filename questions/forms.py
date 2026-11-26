from django import forms
from django.forms import formset_factory

from .bulk_import import MAX_BATCH_QUESTIONS, MAX_PASTE_LENGTH
from .illustrations import prepare_image
from .models import Question, QuestionImage


ANSWER_NUMBERS = range(1, 7)


class QuestionForm(forms.ModelForm):
    image = forms.FileField(
        label="Image (optional)", required=False,
        help_text="PNG, JPEG or WebP, up to 5 MB.",
        widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
    )
    image_description = forms.CharField(
        label="Image description (optional)", max_length=250, required=False,
        help_text="Describe the key details for students using a screen reader.",
    )
    remove_image = forms.BooleanField(label="Remove image", required=False)
    answer_count = forms.TypedChoiceField(
        label="Number of answers", choices=[(n, n) for n in range(2, 7)], coerce=int,
        initial=2,
    )
    correct = forms.TypedMultipleChoiceField(
        label="Correct answers",
        choices=[(n, f"Answer {n}") for n in ANSWER_NUMBERS],
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Mark at least one answer as correct."},
    )

    class Meta:
        model = Question
        fields = ("prompt", "chapter")
        labels = {"prompt": "Question", "chapter": "Quiz / Chapter (optional)"}
        widgets = {
            "prompt": forms.Textarea(attrs={"rows": 3}),
            "chapter": forms.TextInput(attrs={"list": "question-chapter-names"}),
        }

    def __init__(self, *args, current_image=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_image = current_image
        if current_image is not None:
            self.initial["image_description"] = current_image["description"]
        for number in ANSWER_NUMBERS:
            self.fields[f"answer_{number}"] = forms.CharField(
                label=f"Answer {number}", max_length=1000, required=False,
                widget=forms.Textarea(attrs={"rows": 2}),
            )
        if self.instance.pk:
            self.initial["answer_count"] = len(self.instance.choices)
            self.initial["correct"] = [index + 1 for index in self.instance.correct_indices]
            for number, answer in enumerate(self.instance.choices, start=1):
                self.initial[f"answer_{number}"] = answer

    @property
    def answer_rows(self):
        return zip((self[f"answer_{number}"] for number in ANSWER_NUMBERS), self["correct"])

    def clean_image(self):
        upload = self.cleaned_data["image"]
        return prepare_image(upload) if upload else None

    def save_illustration(self):
        content = self.cleaned_data["image"]
        description = self.cleaned_data["image_description"]
        if content:
            QuestionImage.objects.update_or_create(
                question=self.instance, defaults={"content": content, "description": description},
            )
        elif self.current_image is not None:
            existing = QuestionImage.objects.filter(question=self.instance)
            if self.cleaned_data["remove_image"]:
                existing.delete()
            elif "image_description" in self.changed_data:
                existing.update(description=description)

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

        correct = set(data.get("correct", []))
        if any(number > count for number in correct):
            self.add_error("correct", "Mark only answers that are shown.")
        self.instance.choices = choices
        self.instance.correct_indices = sorted(number - 1 for number in correct)
        return data


class BulkQuizNameForm(forms.Form):
    chapter = forms.CharField(label="Quiz name", max_length=Question._meta.get_field("chapter").max_length)


class BulkQuizPasteForm(BulkQuizNameForm):
    source = forms.CharField(
        label="Quiz text", max_length=MAX_PASTE_LENGTH,
        widget=forms.Textarea(attrs={
            "rows": 14,
            "placeholder": "1. Which planet is closest to the Sun?\nA. Venus\nB. Mercury\nC. Earth\nAnswer: B",
        }),
    )


class BulkQuestionForm(QuestionForm):
    class Meta(QuestionForm.Meta):
        fields = ("prompt",)


BulkQuestionFormSet = formset_factory(
    BulkQuestionForm, extra=0, can_delete=True,
    min_num=1, validate_min=True, max_num=MAX_BATCH_QUESTIONS,
    validate_max=True, absolute_max=MAX_BATCH_QUESTIONS,
)


class QuizSetupForm(forms.Form):
    chapter = forms.ChoiceField(label="Quiz / Chapter", required=False)
    minutes = forms.IntegerField(
        label="Time limit in minutes (optional)", required=False, min_value=1,
        max_value=1440, widget=forms.NumberInput(attrs={"placeholder": "No time limit"}),
    )

    def __init__(self, *args, chapters, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chapter"].choices = [("", "All questions"), *((name, name) for name in chapters)]
