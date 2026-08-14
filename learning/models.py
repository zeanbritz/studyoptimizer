from django.db import models
from django.conf import settings

class Subject(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subjects",
    )

    name = models.CharField(max_length=100)

    colour = models.CharField(
        max_length=7,
        default="#2563EB"
    )

    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Topic(models.Model):

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="topics",
    )

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class KnowledgeUnit(models.Model):

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="knowledge_units",
    )

    class KnowledgeType(models.TextChoices):

        FORMULA = "FORMULA", "Formula"

        DEFINITION = "DEFINITION", "Definition"

        BULLET_LIST = "BULLET_LIST", "Bullet List"


    title = models.CharField(
        max_length=255
    )

    knowledge_type = models.CharField(
        max_length=20,
        choices=KnowledgeType.choices,
    )

    difficulty = models.PositiveSmallIntegerField(
        default=1
    )

    estimated_minutes = models.PositiveSmallIntegerField(
        default=2
    )

    active = models.BooleanField(
        default=True
    )

    created = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):

        return self.title


class Formula(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
        related_name="formula",
    )

    structure = models.TextField(
        default="[]"
    )

    purpose = models.TextField(
        blank=True
    )

    when_to_use = models.TextField(
        blank=True
    )

    def __str__(self):
        return self.knowledge_unit.title

class FormulaVariable(models.Model):

    formula = models.ForeignKey(
        Formula,
        on_delete=models.CASCADE,
        related_name="variables",
    )

    symbol = models.CharField(max_length=50)

    meaning = models.CharField(max_length=255)

    order = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.symbol} - {self.meaning}"

class FormulaElementPerformance(models.Model):

    formula = models.ForeignKey(
        Formula,
        on_delete=models.CASCADE,
        related_name="element_performance",
    )

    element_id = models.CharField(
        max_length=100
    )

    element_type = models.CharField(
        max_length=50
    )

    value = models.CharField(
        max_length=255,
        blank=True
    )

    correct_count = models.PositiveIntegerField(
        default=0
    )

    incorrect_count = models.PositiveIntegerField(
        default=0
    )

    last_reviewed = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return (
            f"{self.value} "
            f"({self.element_type})"
        )


class Definition(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
    )

    term = models.CharField(max_length=255)

    definition = models.TextField()

    def __str__(self):
        return self.term


class BulletList(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
    )

    question = models.CharField(max_length=255)

    def __str__(self):
        return self.question


class BulletItem(models.Model):

    bullet_list = models.ForeignKey(
        BulletList,
        on_delete=models.CASCADE,
        related_name="items",
    )

    text = models.CharField(max_length=255)

    order = models.PositiveIntegerField(default=1)

    def __str__(self):
        return self.text


class StudentKnowledge(models.Model):

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="knowledge_progress",
    )

    knowledge_unit = models.ForeignKey(
        KnowledgeUnit,
        on_delete=models.CASCADE,
        related_name="student_progress",
    )

    mastery_level = models.PositiveSmallIntegerField(
        default=0
    )

    review_count = models.PositiveIntegerField(
        default=0
    )

    correct_count = models.PositiveIntegerField(
        default=0
    )

    incorrect_count = models.PositiveIntegerField(
        default=0
    )

    last_reviewed = models.DateTimeField(
        null=True,
        blank=True
    )

    next_review = models.DateTimeField(
        null=True,
        blank=True
    )

    created = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "knowledge_unit",
                ],
                name="unique_student_knowledge_unit",
            )
        ]

    def __str__(self):

        return (
            f"{self.student} - "
            f"{self.knowledge_unit.title}"
        )