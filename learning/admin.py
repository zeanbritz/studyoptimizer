from django.contrib import admin
from .models import (
    Subject,
    Topic,
    KnowledgeUnit,
    Formula,
    FormulaVariable,
    Definition,
    BulletList,
    BulletItem,
    StudentKnowledge,
)

admin.site.register(Subject)
admin.site.register(Topic)
admin.site.register(KnowledgeUnit)
admin.site.register(Formula)
admin.site.register(FormulaVariable)
admin.site.register(Definition)
admin.site.register(BulletList)
admin.site.register(BulletItem)

@admin.register(StudentKnowledge)
class StudentKnowledgeAdmin(admin.ModelAdmin):

    list_display = (
        "student",
        "knowledge_unit",
        "mastery_level",
        "review_count",
        "correct_count",
        "incorrect_count",
        "next_review",
    )

    list_filter = (
        "mastery_level",
    )