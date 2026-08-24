from django.conf import settings
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