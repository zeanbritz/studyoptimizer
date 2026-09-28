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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.subject.name} {self.get_kind_display()} — {self.date}"
