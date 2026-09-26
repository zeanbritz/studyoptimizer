from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


# ============================================================
# STUDY PROFILE
# ============================================================

class StudyProfile(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_profile",
    )

    workspace_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    target_grade = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    study_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(168),
        ],
    )

    subject_count = models.PositiveSmallIntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(20),
        ],
    )

    onboarding_complete = models.BooleanField(
        default=False
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):

        return (
            f"Study profile - "
            f"{self.user}"
        )


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



class BetaFeedback(models.Model):
    class Category(models.TextChoices):
        IDEA = "idea", "Idea"
        BUG = "bug", "Bug"
        CONFUSING = "confusing", "Confusing"

    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWING = "reviewing", "Reviewing"
        RESOLVED = "resolved", "Resolved"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="beta_feedback",
    )
    category = models.CharField(
        max_length=10,
        choices=Category.choices,
    )
    message = models.CharField(max_length=2000)
    page_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_category_display()} from {self.user}"
