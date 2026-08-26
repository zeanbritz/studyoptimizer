from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


# ============================================================
# STUDY AVAILABILITY
# ============================================================

class StudyAvailability(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_availability",
    )

    # --------------------------------------------------------
    # MONDAY
    # --------------------------------------------------------

    monday_enabled = models.BooleanField(
        default=False
    )

    monday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # TUESDAY
    # --------------------------------------------------------

    tuesday_enabled = models.BooleanField(
        default=False
    )

    tuesday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # WEDNESDAY
    # --------------------------------------------------------

    wednesday_enabled = models.BooleanField(
        default=False
    )

    wednesday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # THURSDAY
    # --------------------------------------------------------

    thursday_enabled = models.BooleanField(
        default=False
    )

    thursday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # FRIDAY
    # --------------------------------------------------------

    friday_enabled = models.BooleanField(
        default=False
    )

    friday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # SATURDAY
    # --------------------------------------------------------

    saturday_enabled = models.BooleanField(
        default=False
    )

    saturday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # SUNDAY
    # --------------------------------------------------------

    sunday_enabled = models.BooleanField(
        default=False
    )

    sunday_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
    )

    # --------------------------------------------------------
    # UPDATED
    # --------------------------------------------------------

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):

        return (
            f"Study availability - "
            f"{self.user}"
        )


# ============================================================
# SUBJECT TEXTBOOK
# ============================================================

class SubjectTextbook(models.Model):

    subject = models.ForeignKey(
        "learning.Subject",
        on_delete=models.CASCADE,
        related_name="study_textbooks",
    )

    name = models.CharField(
        max_length=255
    )

    page_count = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1)
        ]
    )

    # ========================================================
    # SUMMARY PROGRESS
    # ========================================================

    pages_summarized = models.PositiveIntegerField(
        default=0
    )

    last_summary_date = models.DateField(
        null=True,
        blank=True,
    )

    created = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):

        return (
            f"{self.name} "
            f"({self.page_count} pages)"
        )

# ============================================================
# SUBJECT REVISION PLAN
# ============================================================

class SubjectRevisionPlan(models.Model):

    subject = models.OneToOneField(
        "learning.Subject",
        on_delete=models.CASCADE,
        related_name="revision_plan",
    )

    revision_days = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):

        return (
            f"{self.subject.name} - "
            f"{self.revision_days} revision days"
        )