from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom User model.
    We'll add fields here later (XP, streaks, preferences, etc.).
    """
    pass