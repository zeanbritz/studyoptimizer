from django.conf import settings
from django.db import models


class Subject(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    name = models.CharField(max_length=100)

    colour = models.CharField(max_length=20, default="#4F46E5")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Topic(models.Model):
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="topics"
    )

    name = models.CharField(max_length=200)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class LearningItem(models.Model):

    FORMULA = "FORMULA"
    DEFINITION = "DEFINITION"
    BULLET_LIST = "BULLET_LIST"

    ITEM_TYPES = [
        (FORMULA, "Formula"),
        (DEFINITION, "Definition"),
        (BULLET_LIST, "Bullet List"),
    ]

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="learning_items"
    )

    item_type = models.CharField(
        max_length=20,
        choices=ITEM_TYPES
    )

    title = models.CharField(max_length=255)

    content = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title