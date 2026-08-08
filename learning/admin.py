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
)


admin.site.register(Subject)
admin.site.register(Topic)
admin.site.register(KnowledgeUnit)
admin.site.register(Formula)
admin.site.register(FormulaVariable)
admin.site.register(Definition)
admin.site.register(BulletList)
admin.site.register(BulletItem)