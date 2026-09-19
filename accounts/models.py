from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for StudyOptimizer.

    The workspace data field keeps the onboarding profile and subject workspace
    available after Django clears the browser session during logout.
    """

    workspace_data = models.TextField(
        default="{}",
        blank=True,
    )
