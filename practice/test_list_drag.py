from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import BulletItem, BulletList, KnowledgeUnit, StudentKnowledge, Subject


class ListDragReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="list_drag_student",
            password="Safe-test-password-123!",
        )
        self.subject = Subject.objects.create(user=self.user, name="Economics")
        self.unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Market assumptions",
            knowledge_type=KnowledgeUnit.KnowledgeType.BULLET_LIST,
            active=True,
        )
        self.bullet_list = BulletList.objects.create(
            knowledge_unit=self.unit,
            question="Market assumptions",
        )
        for order, text in enumerate(("Many buyers", "Free entry", "Perfect information"), 1):
            BulletItem.objects.create(
                bullet_list=self.bullet_list,
                text=text,
                order=order,
            )
        self.client.force_login(self.user)
        self.url = reverse("review_list", args=[self.bullet_list.pk])

    def test_review_uses_drag_tokens_instead_of_typed_answers(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="list-answer-token"')
        self.assertContains(response, 'data-list-drop-slot')
        self.assertNotContains(response, 'name="answer_')

    def test_correct_dragged_items_update_mastery(self):
        question = self.client.get(self.url)
        hidden_ids = [
            item["item"].pk
            for item in question.context["review_items"]
            if item["hidden"]
        ]
        response = self.client.post(
            self.url,
            {
                "hidden_item_id": hidden_ids,
                **{
                    f"placed_item_id_{item_id}": item_id
                    for item_id in hidden_ids
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"], "correct")
        progress = StudentKnowledge.objects.get(
            student=self.user,
            knowledge_unit=self.unit,
        )
        self.assertEqual(progress.review_count, 1)
        self.assertEqual(progress.mastery_level, 1)
