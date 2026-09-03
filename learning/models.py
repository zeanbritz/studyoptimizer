from django.conf import settings
from django.db import models


# ============================================================
# SUBJECT
# ============================================================

class Subject(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subjects",
    )

    name = models.CharField(
        max_length=100
    )

    colour = models.CharField(
        max_length=7,
        default="#2563EB",
    )

    created = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):

        return self.name


# ============================================================
# TOPIC
# ============================================================

class Topic(models.Model):

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="topics",
    )

    name = models.CharField(
        max_length=200
    )

    description = models.TextField(
        blank=True
    )

    created = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):

        return self.name


# ============================================================
# KNOWLEDGE UNIT
# ============================================================

class KnowledgeUnit(models.Model):

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="knowledge_units",
        null=True,
        blank=True,
    )

    # ========================================================
    # KNOWLEDGE TYPES
    # ========================================================

    class KnowledgeType(models.TextChoices):

        FORMULA = (
            "FORMULA",
            "Formula",
        )

        DEFINITION = (
            "DEFINITION",
            "Definition",
        )

        BULLET_LIST = (
            "BULLET_LIST",
            "Bullet List",
        )

        STEPS = (
            "STEPS",
            "Steps",
        )

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


# ============================================================
# FORMULA
# ============================================================

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

    book_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    chapter = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    def __str__(self):

        return self.knowledge_unit.title


# ============================================================
# FORMULA VARIABLE
# ============================================================

class FormulaVariable(models.Model):

    formula = models.ForeignKey(
        Formula,
        on_delete=models.CASCADE,
        related_name="variables",
    )

    symbol = models.CharField(
        max_length=50
    )

    meaning = models.CharField(
        max_length=255
    )

    order = models.PositiveIntegerField(
        default=1
    )

    def __str__(self):

        return (
            f"{self.symbol} - "
            f"{self.meaning}"
        )


# ============================================================
# FORMULA ELEMENT PERFORMANCE
# ============================================================

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
        blank=True,
    )

    correct_count = models.PositiveIntegerField(
        default=0
    )

    incorrect_count = models.PositiveIntegerField(
        default=0
    )

    last_reviewed = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):

        return (
            f"{self.value} "
            f"({self.element_type})"
        )


# ============================================================
# DEFINITION
# ============================================================

class Definition(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
        related_name="definition",
    )

    term = models.CharField(
        max_length=255
    )

    definition = models.TextField()

    def __str__(self):

        return self.term


# ============================================================
# BULLET LIST
# ============================================================

class BulletList(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
        related_name="bullet_list",
    )

    question = models.CharField(
        max_length=255
    )

    book_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    chapter = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    def __str__(self):

        return self.question


# ============================================================
# BULLET ITEM
# ============================================================

class BulletItem(models.Model):

    bullet_list = models.ForeignKey(
        BulletList,
        on_delete=models.CASCADE,
        related_name="items",
    )

    text = models.CharField(
        max_length=255
    )

    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    order = models.PositiveIntegerField(
        default=1
    )

    class Meta:

        ordering = [
            "order",
            "id",
        ]

    def __str__(self):

        return self.text


# ============================================================
# STEP LIST
# ============================================================

class StepList(models.Model):

    knowledge_unit = models.OneToOneField(
        KnowledgeUnit,
        on_delete=models.CASCADE,
        related_name="step_list",
    )

    question = models.CharField(
        max_length=255
    )

    book_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    chapter = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    def __str__(self):

        return self.question


# ============================================================
# STEP ITEM
# ============================================================

class StepItem(models.Model):

    step_list = models.ForeignKey(
        StepList,
        on_delete=models.CASCADE,
        related_name="steps",
    )

    text = models.CharField(
        max_length=255
    )

    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    order = models.PositiveIntegerField(
        default=1
    )

    class Meta:

        ordering = [
            "order",
            "id",
        ]

    def __str__(self):

        return (
            f"{self.order}. "
            f"{self.text}"
        )


# ============================================================
# STUDENT KNOWLEDGE
# ============================================================

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
        blank=True,
    )

    next_review = models.DateTimeField(
        null=True,
        blank=True,
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
                name=(
                    "unique_student_knowledge_unit"
                ),
            )
        ]

    def __str__(self):

        return (
            f"{self.student} - "
            f"{self.knowledge_unit.title}"
        )