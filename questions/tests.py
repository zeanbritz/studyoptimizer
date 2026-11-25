from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from learning.models import Subject
from .models import Question, QuizRun


class QuestionQuizTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user(username="questions-student")
        cls.subject = Subject.objects.create(user=cls.student, name="Physics")
        cls.other_student = get_user_model().objects.create_user(username="other-learner")
        cls.other_subject = Subject.objects.create(user=cls.other_student, name="Private subject")

    def setUp(self):
        self.client.force_login(self.student)
        self.setup_url = reverse("questions:setup") + f"?subject={self.subject.pk}"
        self.manage_url = reverse("questions:manage", args=[self.subject.pk])

    def add_question(self, prompt, chapter=""):
        return Question.objects.create(
            subject=self.subject, chapter=chapter, prompt=prompt,
            choices=["First choice", "Second choice"], correct_indices=[1],
        )

    def start_quiz(self, **data):
        response = self.client.post(self.setup_url, data)
        self.assertEqual(response.status_code, 302)
        return response["Location"]

    def answer(self, url, position, choice):
        return self.client.post(url, {"action": "answer", "position": position, "answer": choice})

    def test_create_edit_and_validate_answer_limits(self):
        management_page = self.client.get(self.manage_url)
        self.assertContains(management_page, "Upload Question")
        self.assertContains(management_page, "data-question-upload-form")
        self.assertContains(management_page, 'type="checkbox" name="correct"', count=6)
        form = {"prompt": "Which quantity is a vector?", "chapter": "Motion",
                "answer_count": "6", "correct": ["2", "6"]}
        form.update({f"answer_{n}": f"Choice {n}" for n in range(1, 7)})
        for invalid in ({"answer_count": "1"}, {"answer_count": "7"}, {"answer_count": "2"}, {"correct": ""},
                        {"answer_6": " "}, {"answer_6": "Choice 1"}):
            with self.subTest(invalid=invalid):
                response = self.client.post(self.manage_url, {**form, **invalid})
                self.assertTrue(response.context["form"].errors)
                self.assertFalse(Question.objects.exists())

        self.assertRedirects(self.client.post(self.manage_url, form), self.manage_url + "?chapter=Motion")
        question = Question.objects.get()
        self.assertEqual(question.choices, [form[f"answer_{n}"] for n in range(1, 7)])
        self.assertEqual(question.correct_indices, [1, 5])

        edit_url = reverse("questions:edit", args=[self.subject.pk, question.pk])
        edit_page = self.client.get(edit_url)
        self.assertEqual(edit_page.context["form"].initial["correct"], [2, 6])
        self.assertContains(edit_page, 'value="6" id="id_correct_5" checked')
        self.assertRedirects(
            self.client.post(edit_url, {**form, "answer_count": 2, "correct": 1}),
            self.manage_url,
        )
        question.refresh_from_db()
        self.assertEqual(question.choices, ["Choice 1", "Choice 2"])
        self.assertEqual(question.correct_indices, [0])

    def test_saved_questions_show_ten_newest_then_older_questions(self):
        saved = [self.add_question(f"Motion question {n}", "Motion") for n in range(13)]
        self.add_question("Energy question", "Energy")
        scope_url = self.manage_url + "?chapter=Motion"

        newest = self.client.get(scope_url)
        self.assertEqual(list(newest.context["questions_page"]), list(reversed(saved[3:])))
        self.assertContains(newest, "Page 1 of 2")
        self.assertContains(newest, 'aria-label="Next page"')
        self.assertNotContains(newest, 'aria-label="Previous page"')

        older = self.client.get(scope_url + "&page=2")
        self.assertEqual(list(older.context["questions_page"]), list(reversed(saved[:3])))
        self.assertContains(older, "Page 2 of 2")
        self.assertContains(older, 'aria-label="Previous page"')
        self.assertNotContains(older, "Energy question")

    def test_named_group_is_reused_for_new_questions_and_quiz_setup(self):
        question = {
            "prompt": "First question", "chapter": "Forces & Motion", "answer_count": 2,
            "answer_1": "First choice", "answer_2": "Second choice", "correct": 2,
        }
        created = self.client.post(self.manage_url, question)
        group_url = self.manage_url + "?chapter=Forces+%26+Motion"
        self.assertRedirects(created, group_url)
        group = self.client.get(group_url)
        self.assertTrue(group.context["form"].fields["chapter"].disabled)
        self.assertEqual(group.context["form"]["chapter"].value(), "Forces & Motion")

        question.pop("chapter")
        question["prompt"] = "Second question"
        self.assertRedirects(self.client.post(group_url, question), group_url)
        self.assertEqual(Question.objects.get(prompt="Second question").chapter, "Forces & Motion")

        setup = self.client.get(group.context["setup_url"])
        self.assertEqual(setup.context["form"]["chapter"].value(), "Forces & Motion")

    def test_chapter_quiz_scores_every_question_once(self):
        self.add_question("Chapter question one", "Motion")
        self.add_question("Chapter question two", "Motion")
        self.add_question("Unfiled question")
        self.add_question("Another chapter", "Energy")
        url = self.start_quiz(chapter="Motion")

        first = self.client.get(url)
        self.assertContains(first, "Chapter question one")
        self.assertNotContains(first, "Correct answer")
        self.assertNotContains(first, "Unfiled question")
        self.assertNotContains(first, "Chapter question two")

        response = self.answer(url, 0, 1)
        self.assertContains(self.client.get(response["Location"]), "Correct answer")
        self.answer(url, 0, 1)
        self.assertEqual(QuizRun.objects.get(student=self.student).answers, [[1]])

        self.assertContains(self.client.get(url), "Chapter question two")
        result = self.answer(url, 1, 0)
        page = self.client.get(result["Location"])
        self.assertContains(page, "Quiz complete")
        self.assertContains(page, "1 / 2")
        self.assertContains(page, "50%")
        self.assertContains(page, "2 of 2 answered")
        self.assertContains(page, f'href="{reverse("dashboard")}#today-plan"')

    def test_multiple_correct_answers_require_the_exact_set_in_any_order(self):
        for prompt in ("Exact match", "Partial match", "Extra choice"):
            Question.objects.create(
                subject=self.subject, prompt=prompt, choices=["One", "Two", "Three"],
                correct_indices=[0, 2],
            )
        url = self.start_quiz()
        first = self.client.get(url)
        self.assertContains(first, "Select all correct answers.")
        self.assertContains(first, 'type="checkbox" name="answer"', count=3)
        self.assertEqual(self.answer(url, 0, []).status_code, 400)
        self.assertEqual(self.answer(url, 0, [0, 3]).status_code, 400)

        for position, choices, expected in ((0, [2, 0], True), (1, [0], False), (2, [0, 1, 2], False)):
            with self.subTest(choices=choices):
                result = self.answer(url, position, choices)
                page = self.client.get(result["Location"])
                self.assertEqual(page.context["answered_correctly"], expected)
                self.assertContains(page, "Correct answer", count=2)
        self.assertContains(page, "1 / 3")
        self.assertContains(page, "33.3%")

    def test_existing_single_answer_quiz_can_resume_and_keep_its_score(self):
        snapshot = {"prompt": "Legacy question", "choices": ["One", "Two"], "correct_index": 1}
        run = QuizRun.objects.create(
            student=self.student, subject=self.subject, questions=[snapshot, snapshot], answers=[1],
        )
        url = reverse("questions:quiz", args=[run.token])
        self.assertContains(self.client.get(url + "?feedback=1"), "Correct answer")
        self.assertContains(self.client.get(url), 'type="radio" name="answer"', count=2)
        response = self.answer(url, 1, 1)
        self.assertContains(self.client.get(response["Location"]), "2 / 2")

    def test_all_chapters_includes_unfiled_questions_and_can_stop(self):
        self.add_question("First question", "Motion")
        self.add_question("Unfiled question")
        url = self.start_quiz()
        run = QuizRun.objects.get(student=self.student)
        self.assertEqual(len(run.questions), 2)
        self.assertIsNone(run.deadline)
        self.answer(url, 0, 1)
        self.assertRedirects(self.client.post(url, {"action": "stop"}), url)
        self.assertContains(self.client.get(url), "Quiz stopped")
        self.assertContains(self.client.get(url), "1 of 2 answered")
        self.assertContains(self.client.get(url), "50%")

    def test_timer_survives_reload_and_rejects_late_answers(self):
        self.add_question("Timed question")
        url = self.start_quiz(minutes="5")
        run = QuizRun.objects.get(student=self.student)
        self.assertContains(self.client.get(url), "data-quiz-timer")
        self.assertContains(self.client.get(url), "data-quiz-timer")
        run.refresh_from_db()
        self.assertLessEqual(run.deadline, timezone.now() + timedelta(minutes=5))
        run.deadline = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["deadline"])
        self.assertRedirects(self.answer(url, 0, 1), url)
        self.assertContains(self.client.get(url), "Time’s up")
        run.refresh_from_db()
        self.assertEqual(run.answers, [])

    def test_questions_and_quiz_are_private(self):
        question = self.add_question("Private question")
        url = self.start_quiz()
        self.client.force_login(self.other_student)
        self.assertNotContains(self.client.get(reverse("questions:setup")), self.subject.name)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(self.manage_url).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("questions:delete", args=[self.subject.pk, question.pk])).status_code,
            404,
        )
        self.assertTrue(Question.objects.filter(pk=question.pk).exists())
