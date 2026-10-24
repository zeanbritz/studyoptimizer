import json
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import StudyAvailability, StudyProfile
from learning.models import (
    BulletItem, BulletList, Comparison, ComparisonCell, ComparisonColumn,
    ComparisonRow, Definition, Formula, KnowledgeUnit, Note, StepItem, StepList,
    StudentKnowledge, Subject,
)


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


class ReviewNavigationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="review-navigator", beta_lifetime_access=True)
        self.subject = Subject.objects.create(user=self.user, name="Chemistry")
        StudyProfile.objects.create(user=self.user, onboarding_complete=True, subject_count=1)
        StudyAvailability.objects.create(user=self.user, **{
            f"{day}_{field}": value
            for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            for field, value in (("enabled", True), ("time", "08:00"))
        })
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_subjects"] = [{"name": self.subject.name, "database_id": self.subject.pk}]
        session.save()

        def unit(kind):
            return KnowledgeUnit.objects.create(subject=self.subject, title=kind, knowledge_type=kind, estimated_minutes=1)

        self.definition = Definition.objects.create(knowledge_unit=unit("DEFINITION"), term="Atom", definition="A unit of matter")
        self.formula = Formula.objects.create(knowledge_unit=unit("FORMULA"), structure=json.dumps([
            {"id": "f", "type": "variable", "value": "F"},
            {"id": "eq", "type": "operator", "value": "="},
            {"id": "m", "type": "variable", "value": "m"},
        ]))
        self.bullet = BulletList.objects.create(knowledge_unit=unit("BULLET_LIST"), question="Cell parts")
        self.bullet_item = BulletItem.objects.create(bullet_list=self.bullet, text="Nucleus")
        self.steps = StepList.objects.create(knowledge_unit=unit("STEPS"), question="Experiment")
        self.step = StepItem.objects.create(step_list=self.steps, text="Measure")
        self.comparison = Comparison.objects.create(knowledge_unit=unit("COMPARISON"), name="States")
        column = ComparisonColumn.objects.create(comparison=self.comparison, name="Gas")
        row = ComparisonRow.objects.create(comparison=self.comparison, name="Volume")
        self.cell = ComparisonCell.objects.create(row=row, column=column, content="Variable")
        self.note = Note.objects.create(subject=self.subject, title="Lab note", content="A short laboratory note.")
        self.cases = [
            ("definitions", "definition_review_list", "practice_definition_review", self.definition),
            ("formulas", "formula_review_list", "practice_formula", self.formula),
            ("lists", "list_review_list", "review_list", self.bullet),
            ("steps", "step_review_list", "practice_step_review", self.steps),
            ("comparisons", "comparison_review_list", "practice_comparison_review", self.comparison),
            ("notes", "note_list", "note_detail", self.note),
        ]

    def expected(self, origin):
        if origin in {"garden", "standard"}:
            return reverse("dashboard") + f"?view={origin}&review_return=1#today-plan"
        return reverse("subject_detail", args=[0]) + "?review_return=1"

    def assert_back(self, response, origin):
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.expected(origin), [a.get("href") for a in Links(response.content.decode()).links])

    def test_all_six_lists_keep_the_origin_in_back_and_task_links(self):
        for origin in ("standard", "garden", "subject"):
            for kind, list_route, task_route, item in self.cases:
                with self.subTest(origin=origin, kind=kind):
                    kwargs = {"review_origin": origin}
                    if kind == "notes":
                        kwargs.update(mode="subject_review", subject_index=0)
                    url = reverse(list_route, args=[self.subject.pk if kind == "notes" else 0])
                    response = self.client.get(url, kwargs)
                    self.assert_back(response, origin)
                    task_links = [a["href"] for a in Links(response.content.decode()).links if urlsplit(a.get("href", "")).path == reverse(task_route if kind != "formulas" else "review_formula", args=[item.pk])]
                    self.assertTrue(task_links, kind)
                    self.assertTrue(all(parse_qs(urlsplit(link).query).get("review_origin") == [origin] for link in task_links))

    def test_all_six_task_pages_keep_the_origin_after_submission(self):
        for origin in ("standard", "garden", "subject"):
            for kind, _, task_route, item in self.cases:
                with self.subTest(origin=origin, kind=kind):
                    params = {"review_origin": origin, "subject_index": 0, "review_scope": "subject", "review_mode": "normal", "scope": "subject"}
                    if kind == "notes":
                        params["mode"] = "subject_review"
                    url = reverse(task_route, args=[item.pk])
                    question = self.client.get(url, params)
                    self.assert_back(question, origin)
                    self.assertContains(question, f'name="review_origin" value="{origin}"')
                    # Even a POST without its GET query must retain this tab's origin.
                    response = self.client.post(url, {**params, "answer": "A unit of matter", "placements": "{}"})
                    self.assert_back(response, origin)

    def test_definition_finish_and_next_keep_origin_through_server_redirects(self):
        url = reverse("practice_definition_review", args=[self.definition.pk])
        for origin in ("standard", "garden"):
            response = self.client.post(url, {"action": "continue", "review_scope": "subject", "subject_index": 0, "review_origin": origin})
            self.assertEqual(response["Location"], self.expected(origin))
        second_unit = KnowledgeUnit.objects.create(subject=self.subject, title="Molecule", knowledge_type="DEFINITION")
        second = Definition.objects.create(knowledge_unit=second_unit, term="Molecule", definition="Bonded atoms")
        response = self.client.post(url, {"action": "continue", "review_scope": "subject", "subject_index": 0, "review_origin": "garden"})
        self.assertEqual(urlsplit(response["Location"]).path, reverse("practice_definition_review", args=[second.pk]))
        self.assertEqual(parse_qs(urlsplit(response["Location"]).query)["review_origin"], ["garden"])

    def test_formula_handoff_and_finish_keep_origin(self):
        handoff = reverse("review_formula", args=[self.formula.pk])
        for origin in ("standard", "garden"):
            response = self.client.get(handoff, {"review_origin": origin, "subject_index": 0, "review_mode": "normal"})
            self.assertEqual(parse_qs(urlsplit(response["Location"]).query)["review_origin"], [origin])
            practice = self.client.get(response["Location"])
            self.assert_back(practice, origin)
            done = self.client.post(reverse("practice_formula", args=[self.formula.pk]), {"action": "continue", "subject_index": 0, "review_origin": origin})
            self.assertEqual(parse_qs(urlsplit(done["Location"]).query)["review_origin"], [origin])
            self.assert_back(self.client.get(done["Location"]), origin)

    def test_notes_next_and_finish_keep_origin_and_mark_studied(self):
        second = Note.objects.create(subject=self.subject, title="Second note", content="More notes")
        url = reverse("note_detail", args=[self.note.pk])
        self.client.get(url, {"mode": "subject_review", "start": 1, "review_origin": "garden"})
        response = self.client.post(url, {"action": "next_note", "mode": "subject_review", "review_origin": "garden"})
        self.assertEqual(urlsplit(response["Location"]).path, reverse("note_detail", args=[second.pk]))
        self.assert_back(self.client.get(response["Location"]), "garden")
        response = self.client.post(response["Location"], {"action": "next_note", "mode": "subject_review"})
        self.assertEqual(response["Location"], self.expected("garden"))
        self.note.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(self.note.last_studied_date)
        self.assertIsNotNone(second.last_studied_date)

    def test_direct_and_untrusted_origins_fall_back_to_the_owned_subject(self):
        for _, _, task_route, item in self.cases:
            for origin in ("", "https://evil.example/", "//evil.example", "/admin/", "GARDEN"):
                with self.subTest(task=task_route, origin=origin):
                    self.assert_back(self.client.get(reverse(task_route, args=[item.pk]), {"review_origin": origin}), "subject")
                    self.assert_back(self.client.get(reverse(task_route, args=[item.pk]), {"review_origin": origin, "subject_index": 999}), "subject")

    def test_parallel_flows_do_not_overwrite_each_other(self):
        url = reverse("practice_definition_review", args=[self.definition.pk])
        self.assert_back(self.client.get(url, {"review_origin": "garden"}), "garden")
        self.assert_back(self.client.get(url, {"review_origin": "standard"}), "standard")
        response = self.client.post(url, {"review_origin": "garden", "review_scope": "subject", "answer": "A unit of matter"})
        self.assert_back(response, "garden")

    def test_dashboard_links_distinguish_views_and_library_links_keep_their_home(self):
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "review_origin=standard")
        for category in page.context["garden_state"]["categories"]:
            self.assertTrue(all(parse_qs(urlsplit(leaf["url"]).query)["review_origin"] == ["garden"] for leaf in category["leaves"]))
        library = self.client.get(reverse("review_definitions"), {"mode": "test"})
        self.assertContains(library, "review_origin=library")
        task = self.client.get(reverse("practice_definition_review", args=[self.definition.pk]), {"review_origin": "library"})
        self.assertIn(reverse("review_definitions"), [a.get("href") for a in Links(task.content.decode()).links])

    def test_all_six_library_cards_keep_library_origin_after_filtering(self):
        library_cases = [
            ("review_definitions", reverse("read_definition", args=[self.definition.pk])),
            ("review_formulas", reverse("read_review_item", args=["formula", self.formula.pk])),
            ("review_lists", reverse("read_review_item", args=["list", self.bullet.pk])),
            ("review_steps", reverse("read_review_item", args=["step", self.steps.pk])),
            ("review_comparisons", reverse("read_review_item", args=["comparison", self.comparison.pk])),
            ("review_notes", reverse("note_detail", args=[self.note.pk])),
        ]
        for list_route, item_path in library_cases:
            with self.subTest(list_route=list_route):
                response = self.client.get(reverse(list_route), {"mode": "review"})
                cards = [
                    link for link in Links(response.content.decode()).links
                    if "data-review-card" in link and urlsplit(link.get("href", "")).path == item_path
                ]
                self.assertTrue(cards)
                for attribute in ("href", "data-global-url", "data-subject-url"):
                    self.assertEqual(
                        parse_qs(urlsplit(cards[0][attribute]).query).get("review_origin"),
                        ["library"],
                    )

    def test_reading_from_each_library_returns_to_that_library(self):
        reading_cases = [
            ("review_definitions", reverse("read_definition", args=[self.definition.pk])),
            ("review_formulas", reverse("read_review_item", args=["formula", self.formula.pk])),
            ("review_lists", reverse("read_review_item", args=["list", self.bullet.pk])),
            ("review_steps", reverse("read_review_item", args=["step", self.steps.pk])),
            ("review_comparisons", reverse("read_review_item", args=["comparison", self.comparison.pk])),
            ("review_notes", reverse("note_detail", args=[self.note.pk]) + "?mode=global_review"),
        ]
        for list_route, item_url in reading_cases:
            with self.subTest(list_route=list_route):
                separator = "&" if "?" in item_url else "?"
                response = self.client.get(item_url + separator + "review_origin=library")
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    reverse(list_route),
                    [link.get("href") for link in Links(response.content.decode()).links],
                )

    def test_testing_from_each_testable_library_returns_to_that_library(self):
        testing_cases = [
            ("review_definitions", "practice_definition_review", self.definition),
            ("review_formulas", "practice_formula", self.formula),
            ("review_lists", "review_list", self.bullet),
            ("review_steps", "practice_step_review", self.steps),
            ("review_comparisons", "practice_comparison_review", self.comparison),
        ]
        for list_route, task_route, item in testing_cases:
            with self.subTest(list_route=list_route):
                response = self.client.get(
                    reverse(task_route, args=[item.pk]),
                    {"review_origin": "library"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    reverse(list_route),
                    [link.get("href") for link in Links(response.content.decode()).links],
                )

    def test_private_items_are_not_accessible_with_a_valid_origin(self):
        owner = get_user_model().objects.create_user(username="private-owner")
        subject = Subject.objects.create(user=owner, name="Private")
        unit = KnowledgeUnit.objects.create(subject=subject, title="Private", knowledge_type="DEFINITION")
        item = Definition.objects.create(knowledge_unit=unit, term="Private", definition="Private")
        self.assertEqual(self.client.get(reverse("practice_definition_review", args=[item.pk]), {"review_origin": "garden"}).status_code, 404)

    def test_formula_details_and_read_only_browsing_retain_origin(self):
        for origin in ("standard", "garden", "subject"):
            self.assert_back(self.client.get(reverse("formula_detail", args=[self.formula.pk]), {"review_origin": origin}), origin)
            self.assert_back(self.client.get(reverse("read_definition", args=[self.definition.pk]), {"review_origin": origin}), origin)
            for kind, item in (("formula", self.formula), ("list", self.bullet), ("step", self.steps), ("comparison", self.comparison)):
                self.assert_back(self.client.get(reverse("read_review_item", args=[kind, item.pk]), {"review_origin": origin}), origin)
