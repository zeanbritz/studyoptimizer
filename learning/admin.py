from django.contrib import admin
from .models import Subject, Topic, LearningItem

admin.site.register(Subject)
admin.site.register(Topic)
admin.site.register(LearningItem)