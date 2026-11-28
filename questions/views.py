import uuid
from datetime import timedelta
from math import ceil
from random import Random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from accounts.entitlements import accessible_subjects
from learning.review_navigation import subject_index
from .bulk_import import MAX_BATCH_QUESTIONS, parse_quiz_text
from .forms import BulkQuestionFormSet, BulkQuizNameForm, BulkQuizPasteForm, QuestionForm, QuizSetupForm
from .models import Question, QuestionImage, QuizRun


def _chapters(questions):
    return questions.exclude(chapter="").order_by("chapter").values_list("chapter", flat=True).distinct()


def _setup_url(subject_id, chapter=""):
    query = {"subject": subject_id}
    if chapter:
        query["chapter"] = chapter
    return reverse("questions:setup", query=query)


def _requested_chapter(request):
    chapter = request.GET.get("chapter", "").strip()
    return chapter if len(chapter) <= Question._meta.get_field("chapter").max_length else ""


def _library_url(subject_id, chapter, page=None):
    query = {}
    if chapter:
        query["chapter"] = chapter
    if page and str(page) != "1":
        query["page"] = page
    return reverse("questions:manage", args=[subject_id], query=query)


@login_required
@require_http_methods(["GET", "POST"])
def setup(request):
    subjects = list(accessible_subjects(request.user).order_by("name", "pk"))
    selected_id = request.GET.get("subject")
    subject = next((item for item in subjects if str(item.pk) == selected_id), None)
    if request.method == "POST" and subject is None:
        return HttpResponseBadRequest("Choose an available subject.")
    if subject is None and subjects:
        subject = subjects[0]

    questions = Question.objects.filter(subject=subject) if subject else Question.objects.none()
    chapters = list(_chapters(questions))
    chapter = _requested_chapter(request)
    form = QuizSetupForm(
        request.POST if request.method == "POST" else None,
        chapters=chapters,
        initial={"chapter": chapter} if chapter in chapters else None,
    )
    if request.method == "POST" and form.is_valid():
        chapter = form.cleaned_data["chapter"]
        pool = questions.filter(chapter=chapter) if chapter else questions
        snapshot = list(pool.values("id", "prompt", "choices", "correct_indices"))
        if snapshot:
            token = uuid.uuid4()
            Random(f"{token}:questions").shuffle(snapshot)
            minutes = form.cleaned_data["minutes"]
            run, _ = QuizRun.objects.update_or_create(
                student=request.user,
                defaults={
                    "subject": subject,
                    "token": token,
                    "chapter": chapter,
                    "questions": snapshot,
                    "answers": [],
                    "deadline": timezone.now() + timedelta(minutes=minutes) if minutes else None,
                    "stopped": False,
                },
            )
            return redirect("questions:quiz", token=run.token)
        form.add_error("chapter", "There are no questions in this selection yet.")

    current_run = QuizRun.objects.filter(
        student=request.user, subject_id__in=[item.pk for item in subjects]
    ).select_related("subject").first()
    return render(request, "questions/setup.html", {
        "active_page": "questions",
        "subjects": subjects,
        "subject": subject,
        "form": form,
        "setup_url": _setup_url(subject.pk) if subject else None,
        "question_count": questions.count(),
        "current_run": current_run if current_run and not current_run.outcome(timezone.now()) else None,
    })


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def quiz(request, token):
    runs = QuizRun.objects.filter(
        student=request.user, subject__in=accessible_subjects(request.user),
    )
    if request.method == "POST":
        with transaction.atomic():
            run = get_object_or_404(runs.select_for_update(), token=token)
            if run.outcome(timezone.now()):
                return redirect("questions:quiz", token=token)
            action = request.POST.get("action")
            if action == "stop":
                run.stopped = True
                run.save(update_fields=["stopped"])
                return redirect("questions:quiz", token=token)
            if action != "answer":
                return HttpResponseBadRequest("Choose an answer or stop the quiz.")

            position = len(run.answers)
            if request.POST.get("position") != str(position):
                return redirect("questions:quiz", token=token)
            submitted = request.POST.getlist("answer")
            choice_count = len(run.questions[position]["choices"])
            max_answers = 1 if len(run.correct_choices(position)) == 1 else choice_count
            if not 1 <= len(submitted) <= max_answers:
                return HttpResponseBadRequest("Choose from the answers shown.")
            try:
                selected = {int(value) for value in submitted}
            except ValueError:
                return HttpResponseBadRequest("Choose from the answers shown.")
            if len(selected) != len(submitted) or any(not 0 <= n < choice_count for n in selected):
                return HttpResponseBadRequest("Choose from the answers shown.")

            run.answers.append(sorted(selected))
            run.save(update_fields=["answers"])
        return redirect(reverse("questions:quiz", args=[token]) + "?feedback=1")

    run = get_object_or_404(runs.select_related("subject"), token=token)
    now = timezone.now()
    outcome = run.outcome(now)
    score = run.score if outcome else None
    feedback = request.GET.get("feedback") == "1" and bool(run.answers)
    feedback = feedback and outcome in (None, "complete")
    position = len(run.answers)
    question = None
    illustration = None
    options = []
    multiple_answers = False
    if feedback or outcome is None:
        index = position - 1 if feedback else position
        saved = run.questions[index]
        question = saved["prompt"]
        if question_id := saved.get("id"):
            illustration = QuestionImage.objects.filter(
                question_id=question_id, question__subject_id=run.subject_id,
            ).values("question_id", "description").first()
        correct_choices = run.correct_choices(index)
        multiple_answers = len(correct_choices) > 1
        selected_choices = run.selected_choices(index) if feedback else set()
        ordered_choices = list(enumerate(saved["choices"]))
        # Keep the same order on refresh and feedback while grading by saved index.
        Random(f"{run.token}:{index}").shuffle(ordered_choices)
        for number, label in ordered_choices:
            options.append({
                "index": number,
                "label": label,
                "selected": number in selected_choices,
                "correct": feedback and number in correct_choices,
            })
    return render(request, "questions/quiz.html", {
        "active_page": "questions",
        "run": run,
        "position": position,
        "question_number": position if feedback else position + 1,
        "question": question,
        "illustration": illustration,
        "options": options,
        "multiple_answers": multiple_answers,
        "feedback": feedback,
        "answered_correctly": feedback and run.answered_correctly(position - 1),
        "outcome": outcome,
        "score": score,
        "percentage": 100 * score / len(run.questions) if outcome else None,
        "seconds_left": ceil((run.deadline - now).total_seconds()) if run.deadline and outcome is None else None,
    })


@login_required
@require_http_methods(["GET", "POST"])
def manage(request, subject_id, question_id=None):
    subject = get_object_or_404(accessible_subjects(request.user), pk=subject_id)
    questions = Question.objects.filter(subject=subject)
    chapter = _requested_chapter(request)
    page = request.GET.get("page")
    question = (
        get_object_or_404(questions, pk=question_id)
        if question_id else Question(subject=subject, chapter=chapter)
    )
    illustration = (
        QuestionImage.objects.filter(question=question).values("question_id", "description").first()
        if question_id else None
    )
    form = QuestionForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=question,
        current_image=illustration,
    )
    form.fields["chapter"].disabled = bool(chapter and not question_id)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            form.save_illustration()
        if question_id:
            return redirect(_library_url(subject.pk, chapter, page))
        return redirect(_library_url(subject.pk, saved.chapter))

    index = subject_index(request, subject)
    if request.FILES:
        messages.warning(request, "Reselect your image after correcting the errors below.")
    chapters = list(_chapters(questions))
    if chapter and chapter not in chapters:
        chapters.append(chapter)
    library = questions.filter(chapter=chapter) if chapter else questions
    return render(request, "questions/manage.html", {
        "active_page": "subjects",
        "subject": subject,
        "subject_url": reverse("subject_detail", args=[index]) if index is not None else reverse("goals"),
        "editing": question_id is not None,
        "chapters": chapters,
        "selected_chapter": chapter,
        "questions_page": Paginator(library.order_by("-pk"), 10).get_page(page),
        "form": form,
        "illustration": illustration,
        "setup_url": _setup_url(subject.pk, chapter),
        "library_url": _library_url(subject.pk, chapter, page),
    })


@login_required
@require_http_methods(["GET", "POST"])
def bulk_add(request, subject_id):
    subject = get_object_or_404(accessible_subjects(request.user), pk=subject_id)
    chapter = _requested_chapter(request)
    form = BulkQuizPasteForm(initial={"chapter": chapter})
    drafts = None

    if request.method == "POST":
        if request.POST.get("action") == "preview":
            form = BulkQuizPasteForm(request.POST)
            if form.is_valid():
                try:
                    initial = parse_quiz_text(form.cleaned_data["source"])
                except ValueError as error:
                    form.add_error("source", str(error))
                else:
                    form = BulkQuizNameForm(initial={"chapter": form.cleaned_data["chapter"]})
                    drafts = BulkQuestionFormSet(initial=initial, prefix="questions")
        elif request.POST.get("action") == "save":
            form = BulkQuizNameForm(request.POST)
            drafts = BulkQuestionFormSet(request.POST, request.FILES, prefix="questions")
            name_valid = form.is_valid()
            drafts_valid = drafts.is_valid()
            if name_valid and drafts_valid:
                name = form.cleaned_data["chapter"]
                kept = [
                    draft for draft in drafts
                    if draft.cleaned_data and not draft.cleaned_data.get("DELETE")
                ]
                rows = []
                for draft in kept:
                    question = draft.save(commit=False)
                    question.subject = subject
                    question.chapter = name
                    rows.append(question)
                with transaction.atomic():
                    Question.objects.bulk_create(rows)
                    for draft in kept:
                        draft.save_illustration()
                messages.success(request, f"Saved {len(rows)} question{'s' if len(rows) != 1 else ''} to {name}.")
                return redirect(_library_url(subject.pk, name))
            if request.FILES:
                messages.warning(request, "Reselect any question images after correcting the errors below.")
        else:
            return HttpResponseBadRequest("Choose whether to preview or save questions.")

    return render(request, "questions/bulk_add.html", {
        "active_page": "questions",
        "subject": subject,
        "form": form,
        "drafts": drafts,
        "max_questions": MAX_BATCH_QUESTIONS,
        "library_url": _library_url(subject.pk, chapter),
    })


@login_required
@require_safe
@never_cache
def question_image(request, question_id):
    image = get_object_or_404(
        QuestionImage, question_id=question_id,
        question__subject__in=accessible_subjects(request.user),
    )
    response = HttpResponse(bytes(image.content), content_type="image/webp")
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def delete(request, subject_id, question_id):
    question = get_object_or_404(
        Question, pk=question_id, subject_id=subject_id,
        subject__in=accessible_subjects(request.user),
    )
    question.delete()
    return redirect(_library_url(subject_id, _requested_chapter(request), request.GET.get("page")))
