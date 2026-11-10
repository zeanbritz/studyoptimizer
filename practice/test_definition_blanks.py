import random

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from learning.models import Definition, KnowledgeUnit, StudentKnowledge, Subject
from practice.views.definitions import (
    DEFINITION_COMMON_WORDS,
    create_definition_question,
    is_testable_definition_word,
)


class DefinitionQuestionBuilderTests(SimpleTestCase):
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"

    def test_low_mastery_blank_is_not_fixed_to_the_middle(self):
        positions = {
            tuple(create_definition_question(
                self.text,
                0,
                rng=random.Random(seed),
            )["missing_indices"])
            for seed in range(20)
        }
        self.assertGreater(len(positions), 1)
        self.assertTrue(any(position != (len(self.text.split()) // 2,) for position in positions))

    def test_higher_mastery_can_create_non_consecutive_word_blanks(self):
        questions = [
            create_definition_question(
                self.text,
                4,
                rng=random.Random(seed),
            )
            for seed in range(10)
        ]
        self.assertTrue(any(
            any(right - left > 1 for left, right in zip(
                question["missing_indices"],
                question["missing_indices"][1:],
            ))
            for question in questions
        ))

    def test_each_hidden_word_has_its_own_matching_width(self):
        question = create_definition_question(
            self.text,
            3,
            missing_indices=[0, 3, 4, 8],
        )
        hidden_parts = [part for part in question["question_parts"] if part["is_missing"]]
        self.assertEqual([part["text"] for part in hidden_parts], [
            "alpha", "delta", "epsilon", "iota",
        ])
        self.assertEqual(
            [part["width_ch"] for part in hidden_parts],
            [len(part["text"]) for part in hidden_parts],
        )

    def test_common_words_are_never_selected_as_definition_blanks(self):
        text = (
            "The cell is an important unit of life and it carries out "
            "specialised functions in an organism"
        )

        for seed in range(20):
            question = create_definition_question(
                text,
                6,
                rng=random.Random(seed),
            )
            for missing_index in question["missing_indices"]:
                word = text.split()[missing_index]
                self.assertTrue(is_testable_definition_word(word))
                self.assertNotIn(word.casefold(), DEFINITION_COMMON_WORDS)

    def test_explicit_common_word_indices_are_not_used_as_blanks(self):
        question = create_definition_question(
            "The cell is an important unit of life",
            3,
            missing_indices=[0, 1, 2, 3, 4, 5, 6, 7],
        )
        self.assertEqual(question["missing_answers"], ["cell", "important", "unit", "life"])

    def test_common_words_with_punctuation_are_not_testable(self):
        self.assertFalse(is_testable_definition_word("The,"))
        self.assertFalse(is_testable_definition_word("an."))

    def test_filler_only_definition_does_not_create_a_blank(self):
        question = create_definition_question("The and an of", 6)
        self.assertFalse(question["has_testable_words"])
        self.assertEqual(question["missing_indices"], [])


class DefinitionQuestionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="definition-blanks",
            beta_lifetime_access=True,
        )
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Cell membrane",
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
        )
        self.definition = Definition.objects.create(
            knowledge_unit=self.unit,
            term="Cell membrane",
            definition="The selective membrane controls movement into and out of every living cell",
        )
        self.client.force_login(self.user)
        self.url = reverse("practice_definition_review", args=[self.definition.pk])

    def test_question_renders_word_sized_inline_inputs(self):
        response = self.client.get(self.url, {"review_origin": "library"})
        self.assertEqual(response.status_code, 200)
        missing_parts = [
            part for part in response.context["question_parts"]
            if part["is_missing"]
        ]
        self.assertEqual(len(missing_parts), 1)
        self.assertContains(response, 'class="missing-input"', count=1)
        self.assertContains(
            response,
            f'--answer-width: {missing_parts[0]["width_ch"]}ch;',
        )
        self.assertNotContains(response, "<textarea")

    def test_signed_question_keeps_the_same_blanks_when_answer_is_checked(self):
        question = self.client.get(self.url, {"review_origin": "library"})
        data = {
            "question_token": question.context["question_token"],
            "review_origin": "library",
        }
        for part in question.context["question_parts"]:
            if part["is_missing"]:
                data[part["input_name"]] = part["text"]

        result = self.client.post(self.url, data)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.context["is_correct"])
        progress = StudentKnowledge.objects.get(
            student=self.user,
            knowledge_unit=self.unit,
        )
        self.assertEqual(progress.mastery_level, 1)
        self.assertEqual(progress.correct_count, 1)

    def test_tampered_question_state_is_rejected(self):
        question = self.client.get(self.url)
        response = self.client.post(self.url, {
            "question_token": question.context["question_token"] + "tampered",
            "answer_0": "anything",
        })
        self.assertEqual(response.status_code, 400)

    def test_filler_only_definition_is_not_given_an_unanswerable_test(self):
        filler_definition = Definition.objects.create(
            knowledge_unit=self.unit,
            term="Filler example",
            definition="The and an of",
        )

        response = self.client.get(
            reverse("practice_definition_review", args=[filler_definition.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["no_testable_words"])
        self.assertIsNone(response.context["question_token"])
        self.assertNotContains(response, "Check Answer")
