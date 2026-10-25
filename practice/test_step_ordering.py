import json
import math
import random

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from learning.models import KnowledgeUnit, StepItem, StepList, StudentKnowledge, Subject
from practice.views.steps import (
    build_step_question,
    choose_required_positions,
    get_step_hidden_count,
)


class StepDifficultyTests(SimpleTestCase):
    def test_difficulty_uses_the_requested_mastery_formula(self):
        self.assertEqual(get_step_hidden_count(10, 0), 2)
        self.assertEqual(get_step_hidden_count(10, 1), 2)
        self.assertEqual(get_step_hidden_count(10, 3), 5)
        self.assertEqual(get_step_hidden_count(10, 6), 10)

    def test_fractional_mastery_is_not_rounded_before_calculation(self):
        self.assertEqual(
            get_step_hidden_count(10, 2.5),
            min(10, max(2, math.ceil(10 * 2.5 / 6))),
        )

    def test_one_and_two_step_sets_always_place_every_step(self):
        self.assertEqual(get_step_hidden_count(1, 0), 1)
        self.assertEqual(get_step_hidden_count(2, 0), 2)
        self.assertEqual(get_step_hidden_count(2, 6), 2)

    def test_prefilled_positions_are_distributed_across_the_process(self):
        positions = choose_required_positions(12, 4, rng=random.Random(12))
        self.assertEqual(len(positions), 4)
        self.assertEqual(len(set(positions)), 4)
        self.assertTrue(any(position < 4 for position in positions))
        self.assertTrue(any(4 <= position < 8 for position in positions))
        self.assertTrue(any(position >= 8 for position in positions))


class StepOrderingReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="step-orderer",
            password="test-pass",
            beta_lifetime_access=True,
        )
        self.subject = Subject.objects.create(user=self.user, name="Chemistry")
        self.unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Titration process",
            knowledge_type="STEPS",
        )
        self.step_list = StepList.objects.create(
            knowledge_unit=self.unit,
            question="How do you perform a titration?",
        )
        self.steps = [
            StepItem.objects.create(
                step_list=self.step_list,
                text=f"Complete stage {number}",
                description=f"Details for stage {number}",
                order=number,
            )
            for number in range(1, 7)
        ]
        self.progress = StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit=self.unit,
            mastery_level=0,
        )
        self.client.force_login(self.user)
        self.url = reverse("practice_step_review", args=[self.step_list.pk])

    def _question(self):
        response = self.client.get(self.url, {"scope": "all", "review_origin": "library"})
        self.assertEqual(response.status_code, 200)
        return response

    def _post_order(self, response, order):
        return self.client.post(
            self.url,
            {
                "scope": "all",
                "review_origin": "library",
                "question_token": response.context["question_token"],
                "ordered_step_ids": json.dumps(order),
            },
        )

    def test_new_review_prefills_four_steps_and_offers_two(self):
        response = self._question()
        self.assertEqual(response.context["steps_to_place"], 2)
        self.assertEqual(response.context["steps_already_added"], 4)
        self.assertEqual(len(response.context["available_steps"]), 2)
        self.assertEqual(len(response.context["ordering_slots"]), 6)
        self.assertContains(response, "Drag the steps into the correct order.")
        self.assertContains(response, "step_ordering.")
        self.assertNotContains(response, 'name="answer_')

    def test_mastery_six_requires_the_complete_sequence(self):
        self.progress.mastery_level = 6
        self.progress.save(update_fields=["mastery_level"])
        response = self._question()
        self.assertEqual(response.context["steps_to_place"], 6)
        self.assertEqual(response.context["steps_already_added"], 0)
        self.assertTrue(all(not slot["locked"] for slot in response.context["ordering_slots"]))

    def test_correct_order_updates_mastery_and_attempt_counts(self):
        question = self._question()
        response = self._post_order(question, [step.id for step in self.steps])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"], "correct")
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.mastery_level, 1)
        self.assertEqual(self.progress.review_count, 1)
        self.assertEqual(self.progress.correct_count, 1)

    def test_wrong_required_positions_are_scored_as_incorrect(self):
        self.progress.mastery_level = 3
        self.progress.save(update_fields=["mastery_level"])
        question = self._question()
        available_ids = [step.id for step in question.context["available_steps"]]
        self.assertGreaterEqual(len(available_ids), 2)
        order = [step.id for step in self.steps]
        left = order.index(available_ids[0])
        right = order.index(available_ids[1])
        order[left], order[right] = order[right], order[left]

        response = self._post_order(question, order)
        self.assertEqual(response.context["result"], "incorrect")
        self.assertTrue(any(not item["correct"] for item in response.context["result_steps"] if item["required"]))
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.mastery_level, 2)
        self.assertEqual(self.progress.incorrect_count, 1)

    def test_incomplete_sequence_cannot_update_progress(self):
        question = self._question()
        response = self._post_order(question, [step.id for step in self.steps[:-1]])
        self.assertContains(response, "Place every available step")
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.review_count, 0)

    def test_prefilled_step_cannot_be_moved_by_a_tampered_submission(self):
        question = self._question()
        locked_ids = [
            slot["step"].id
            for slot in question.context["ordering_slots"]
            if slot["locked"]
        ]
        available_ids = [step.id for step in question.context["available_steps"]]
        order = [step.id for step in self.steps]
        locked_position = order.index(locked_ids[0])
        available_position = order.index(available_ids[0])
        order[locked_position], order[available_position] = order[available_position], order[locked_position]

        response = self._post_order(question, order)
        self.assertContains(response, "Place every available step")
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.review_count, 0)

    def test_answered_question_cannot_be_replayed(self):
        question = self._question()
        order = [step.id for step in self.steps]
        first = self._post_order(question, order)
        self.assertEqual(first.context["result"], "correct")
        second = self._post_order(question, order)
        self.assertContains(second, "review changed unexpectedly")
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.review_count, 1)

    def test_question_state_contains_each_step_exactly_once(self):
        state, _ = build_step_question(
            self.step_list,
            self.steps,
            self.progress,
            rng=random.Random(7),
        )
        combined = state["required_ids"] + state["prefilled_ids"]
        self.assertCountEqual(combined, [step.id for step in self.steps])
        self.assertEqual(len(combined), len(set(combined)))
