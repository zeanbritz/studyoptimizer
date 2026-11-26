from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from learning.models import Subject
from .bulk_import import parse_quiz_text
from .models import Question, QuestionImage, QuizRun


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

    def image_upload(self, color="green"):
        image = BytesIO()
        Image.new("RGB", (32, 16), color).save(image, format="PNG")
        return SimpleUploadedFile("diagram.png", image.getvalue(), content_type="image/png")

    def test_question_images_are_private_and_shown_during_the_quiz(self):
        data = {
            "prompt": "Which line is steeper?", "answer_count": 2,
            "answer_1": "Line A", "answer_2": "Line B", "correct": 2,
            "image": self.image_upload(),
            "image_description": "Two lines marked A and B.",
        }
        self.assertRedirects(self.client.post(self.manage_url, data), self.manage_url)
        question = Question.objects.get(prompt=data["prompt"])
        image_url = reverse("questions:image", args=[question.pk])
        image = self.client.get(image_url)
        self.assertEqual(image["Content-Type"], "image/webp")
        with Image.open(BytesIO(image.content)) as picture:
            self.assertEqual(picture.size, (32, 16))

        quiz_url = self.start_quiz()
        self.assertContains(self.client.get(quiz_url), f'src="{image_url}"')
        result = self.answer(quiz_url, 0, 1)
        feedback = self.client.get(result["Location"])
        self.assertContains(feedback, 'alt="Two lines marked A and B."')

        self.client.force_login(self.other_student)
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.client.force_login(self.student)

        edit_url = reverse("questions:edit", args=[self.subject.pk, question.pk])
        self.assertContains(self.client.get(edit_url), f'src="{image_url}"')
        data["image"] = self.image_upload("blue")
        self.assertRedirects(self.client.post(edit_url, data), self.manage_url)
        self.assertNotEqual(self.client.get(image_url).content, image.content)
        data.pop("image")
        data["remove_image"] = "on"
        self.assertRedirects(self.client.post(edit_url, data), self.manage_url)
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.assertTrue(Question.objects.filter(pk=question.pk).exists())

    def test_invalid_image_cannot_be_saved_as_an_attachment(self):
        response = self.client.post(self.manage_url, {
            "prompt": "Which line is steeper?", "answer_count": 2,
            "answer_1": "Line A", "answer_2": "Line B", "correct": 2,
            "image": SimpleUploadedFile("diagram.png", b"Not a PNG", content_type="image/png"),
        })
        self.assertContains(response, "Choose a valid PNG, JPEG, or WebP image.")
        self.assertFalse(Question.objects.exists())
        self.assertFalse(QuestionImage.objects.exists())

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

    def test_bulk_preview_can_edit_remove_and_save_to_one_quiz(self):
        url = reverse("questions:bulk_add", args=[self.subject.pk])
        self.assertContains(self.client.get(self.setup_url), url)
        self.assertContains(self.client.get(self.manage_url), url)

        preview = self.client.post(url, {
            "action": "preview", "chapter": "Practice Midterm",
            "source": (
                "1. Pick the even numbers.\nA. Two\nB. Three\nC. Four\n"
                "2. A question to remove.\nA. Yes\nB. No\n"
                "3. Find the slower object.\nA. Bicycle\nB. Train\n"
                "Answer key:\n1. A and C\n2. B"
            ),
        })
        self.assertContains(preview, "Review question drafts")
        drafts = preview.context["drafts"]
        self.assertEqual(drafts.total_form_count(), 3)
        self.assertEqual(drafts[0].initial["correct"], [1, 3])
        self.assertEqual(drafts[2].initial["correct"], [])
        self.assertFalse(Question.objects.exists())

        data = {
            "action": "save", "chapter": "Motion Midterm",
            "questions-TOTAL_FORMS": 3, "questions-INITIAL_FORMS": 3,
        }
        for index, draft in enumerate(drafts):
            data.update({f"questions-{index}-{key}": value for key, value in draft.initial.items()})
        data["questions-0-prompt"] = "Which numbers are even?"
        data["questions-0-answer_1"] = "2"
        for key in list(data):
            if key.startswith("questions-1-"):
                del data[key]
        data["questions-1-DELETE"] = "on"

        incomplete = self.client.post(url, data)
        self.assertContains(incomplete, "Mark at least one answer as correct.")
        self.assertFalse(Question.objects.exists())

        data["questions-2-correct"] = 1
        data["questions-0-image"] = self.image_upload()
        data["questions-0-image_description"] = "Three numbered tiles."
        data["questions-1-image"] = self.image_upload()
        result = self.client.post(url, data)
        self.assertRedirects(result, self.manage_url + "?chapter=Motion+Midterm")
        saved = list(Question.objects.filter(subject=self.subject, chapter="Motion Midterm"))
        self.assertEqual([question.prompt for question in saved], [
            "Which numbers are even?", "Find the slower object.",
        ])
        self.assertEqual(saved[0].choices, ["2", "Three", "Four"])
        self.assertEqual(saved[0].correct_indices, [0, 2])
        self.assertEqual(saved[1].correct_indices, [0])
        self.assertEqual(QuestionImage.objects.get().question_id, saved[0].pk)
        self.assertEqual(saved[0].illustration.description, "Three numbered tiles.")
        quiz = self.client.get(self.setup_url + "&chapter=Motion+Midterm")
        self.assertEqual(quiz.context["form"]["chapter"].value(), "Motion Midterm")

    def test_bulk_import_handles_separate_blocks_and_reports_invalid_drafts(self):
        drafts = parse_quiz_text(
            "Which survives a power cut?\n• Battery\n• Wired lamp\nAnswer: A\n\n"
            "What travels faster?\n1. Bicycle\n2. Car\nAnswer: 2"
        )
        self.assertEqual([draft["correct"] for draft in drafts], [[1], [2]])
        self.assertEqual(drafts[1]["prompt"], "What travels faster?")
        with self.assertRaisesRegex(ValueError, "Question 1 needs two to six"):
            parse_quiz_text("1. Seven options?\n" + "\n".join(f"{letter}. Choice {letter}" for letter in "ABCDEFG"))
        other_url = reverse("questions:bulk_add", args=[self.other_subject.pk])
        self.assertEqual(self.client.post(other_url, {"action": "preview"}).status_code, 404)

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

    def test_choices_shuffle_for_new_quizzes_and_keep_their_order_for_feedback(self):
        Question.objects.create(
            subject=self.subject, prompt="Choose two", choices=list("ABCDEF"),
            correct_indices=[0, 2],
        )

        def choice_indices(page):
            return [option["index"] for option in page.context["options"]]

        with patch("questions.views.uuid.uuid4", side_effect=[UUID(int=1), UUID(int=2)]):
            url = self.start_quiz()
            first = choice_indices(self.client.get(url))
            self.assertCountEqual(first, range(6))
            self.assertEqual(choice_indices(self.client.get(url)), first)

            result = self.answer(url, 0, [2, 0])
            feedback = self.client.get(result["Location"])
            self.assertEqual(choice_indices(feedback), first)
            self.assertTrue(feedback.context["answered_correctly"])

            second = choice_indices(self.client.get(self.start_quiz()))
            self.assertCountEqual(second, range(6))
            self.assertNotEqual(second, first)

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
