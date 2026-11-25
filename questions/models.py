import uuid

from django.conf import settings
from django.db import models


class Question(models.Model):
    subject = models.ForeignKey("learning.Subject", on_delete=models.CASCADE)
    chapter = models.CharField(max_length=120, blank=True)
    prompt = models.TextField(max_length=2000)
    choices = models.JSONField()
    correct_index = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("pk",)
        indexes = [models.Index(fields=["subject", "chapter"])]

    def __str__(self):
        return self.prompt[:80]


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

    @property
    def score(self):
        return sum(
            answer == question["correct_index"]
            for answer, question in zip(self.answers, self.questions)
        )
