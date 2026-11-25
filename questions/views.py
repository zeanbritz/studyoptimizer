import uuid
from datetime import timedelta
from math import ceil
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.entitlements import accessible_subjects
from learning.review_navigation import subject_index
from .forms import QuestionForm, QuizSetupForm
from .models import Question, QuizRun


def _chapters(questions):
    return questions.exclude(chapter="").order_by("chapter").values_list("chapter", flat=True).distinct()


def _setup_url(subject_id):
    return reverse("questions:setup") + "?" + urlencode({"subject": subject_id})


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
    form = QuizSetupForm(
        request.POST if request.method == "POST" else None,
        chapters=_chapters(questions),
    )
    if request.method == "POST" and form.is_valid():
        chapter = form.cleaned_data["chapter"]
        pool = questions.filter(chapter=chapter) if chapter else questions
        snapshot = list(pool.values("prompt", "choices", "correct_index"))
        if snapshot:
            minutes = form.cleaned_data["minutes"]
            run, _ = QuizRun.objects.update_or_create(
                student=request.user,
                defaults={
                    "subject": subject,
                    "token": uuid.uuid4(),
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
            try:
                answer = int(request.POST.get("answer", ""))
            except ValueError:
                return HttpResponseBadRequest("Choose one of the answers.")
            if request.POST.get("position") != str(position):
                return redirect("questions:quiz", token=token)
            if not 0 <= answer < len(run.questions[position]["choices"]):
                return HttpResponseBadRequest("Choose one of the answers.")

            run.answers.append(answer)
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
    options = []
    if feedback or outcome is None:
        index = position - 1 if feedback else position
        saved = run.questions[index]
        question = saved["prompt"]
        for number, label in enumerate(saved["choices"]):
            options.append({
                "index": number,
                "label": label,
                "selected": feedback and number == run.answers[index],
                "correct": feedback and number == saved["correct_index"],
            })
    return render(request, "questions/quiz.html", {
        "active_page": "questions",
        "run": run,
        "position": position,
        "question_number": position if feedback else position + 1,
        "question": question,
        "options": options,
        "feedback": feedback,
        "answered_correctly": feedback and run.answers[-1] == run.questions[position - 1]["correct_index"],
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
    question = get_object_or_404(questions, pk=question_id) if question_id else Question(subject=subject)
    form = QuestionForm(request.POST if request.method == "POST" else None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("questions:manage", subject_id=subject.pk)

    index = subject_index(request, subject)
    return render(request, "questions/manage.html", {
        "active_page": "subjects",
        "subject": subject,
        "subject_url": reverse("subject_detail", args=[index]) if index is not None else reverse("goals"),
        "editing": question_id is not None,
        "questions": questions,
        "form": form,
        "setup_url": _setup_url(subject.pk),
    })


@login_required
@require_POST
def delete(request, subject_id, question_id):
    question = get_object_or_404(
        Question, pk=question_id, subject_id=subject_id,
        subject__in=accessible_subjects(request.user),
    )
    question.delete()
    return redirect("questions:manage", subject_id=subject_id)
