import uuid

from django.conf import settings
from django.db import models

from .text_limits import MAX_PROMPT_LENGTH


class Question(models.Model):
    subject = models.ForeignKey("learning.Subject", on_delete=models.CASCADE)
    chapter = models.CharField(max_length=120, blank=True)
    prompt = models.TextField(max_length=MAX_PROMPT_LENGTH)
    choices = models.JSONField()
    correct_indices = models.JSONField()

    class Meta:
        ordering = ("pk",)
        indexes = [models.Index(fields=["subject", "chapter"])]

    def __str__(self):
        return self.prompt[:80]


class QuestionImage(models.Model):
    question = models.OneToOneField(
        Question, on_delete=models.CASCADE, primary_key=True, related_name="illustration",
    )
    # Keep uploads on the persistent database alongside their questions.
    content = models.BinaryField()
    description = models.CharField(max_length=250, blank=True)


class QuizRun(models.Model):
    """Keep the latest quiz per student, with the questions as they were at Start."""

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subject = models.ForeignKey("learning.Subject", on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    chapter = models.CharField(max_length=120, blank=True)
    questions = models.JSONField()
    answers = models.JSONField(default=list)
    deadline = models.DateTimeField(null=True, blank=True)
    stopped = models.BooleanField(default=False)

    def outcome(self, now):
        if len(self.answers) == len(self.questions):
            return "complete"
        if self.stopped:
            return "stopped"
        if self.deadline and now >= self.deadline:
            return "expired"
        return None

    def correct_choices(self, position):
        question = self.questions[position]
        # Quiz snapshots created before multiple answers had a single index.
        if "correct_index" in question:
            return {question["correct_index"]}
        return set(question["correct_indices"])

    def selected_choices(self, position):
        answer = self.answers[position]
        return {answer} if isinstance(answer, int) else set(answer)

    def answered_correctly(self, position):
        return self.selected_choices(position) == self.correct_choices(position)

    @property
    def score(self):
        return sum(self.answered_correctly(position) for position in range(len(self.answers)))
