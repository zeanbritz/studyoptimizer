from datetime import timedelta

from django.core.validators import MaxValueValidator
from django.db import models

from learning.models import Subject


class AssessmentEvent(models.Model):
    class Kind(models.TextChoices):
        ASSESSMENT = "assessment", "Assessment"
        EXAM = "exam", "Exam"

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="assessment_events",
    )
    date = models.DateField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=160, blank=True)
    reminder_days = models.PositiveSmallIntegerField(
        default=3,
        validators=[MaxValueValidator(365)],
        help_text="Days before the event to start showing reminders.",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.subject.name} {self.get_kind_display()} — {self.date}"

    @property
    def reminder_date(self):
        return self.date - timedelta(days=self.reminder_days)
