from datetime import timedelta
import random
import re

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseBadRequest
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.urls import reverse
from django.utils import timezone

from accounts.entitlements import accessible_subjects

from learning.models import (
    Definition,
    KnowledgeUnit,
    StudentKnowledge,
)
from dashboard.review_planner import get_daily_review_plan, remaining_review_ids


# ============================================================
# DEFINITION MASTERY -> HIDDEN PERCENTAGE
# ============================================================

def get_definition_hidden_percentage(
    mastery_level
):

    percentages = {
        0: 10,
        1: 15,
        2: 30,
        3: 45,
        4: 60,
        5: 80,
        6: 100,
    }

    return percentages.get(
        mastery_level,
        10
    )


# ============================================================
# REVIEW INTERVAL
# ============================================================

def get_definition_review_interval(
    mastery_level
):

    intervals = {
        0: 0,
        1: 1,
        2: 2,
        3: 4,
        4: 7,
        5: 14,
        6: 30,
    }

    return intervals.get(
        mastery_level,
        0
    )


# ============================================================
# CREATE HIDDEN DEFINITION SECTION
# ============================================================

# These words help a sentence read naturally but are not useful recall targets.
# Keep this deliberately limited to function words: short scientific terms such
# as "DNA", "pH", "ion", and "per" remain eligible to be tested.
DEFINITION_COMMON_WORDS = {
    "a", "an", "the",
    "and", "or", "but", "if", "then", "than", "as",
    "at", "by", "for", "from", "in", "into", "of", "on", "onto",
    "to", "with", "without", "within", "through", "during", "before",
    "after", "above", "below", "between", "among", "under", "over",
    "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had",
    "can", "could", "may", "might", "will", "would", "should", "must",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "their", "we", "our", "you", "your", "he", "she", "him", "her",
    "which", "who", "whom", "whose", "what", "when", "where", "why",
    "how", "not", "no", "yes", "each", "every", "any", "some", "such",
    "other", "only", "also", "very", "more", "most", "less", "least",
    "etc",
}


def is_testable_definition_word(word):
    """Return whether a displayed definition word is worth recalling."""
    normalized_word = re.sub(
        r"(^[^\w]+|[^\w]+$)",
        "",
        word,
    ).casefold()
    return bool(normalized_word) and normalized_word not in DEFINITION_COMMON_WORDS

def create_definition_question(
    definition_text,
    mastery_level,
    missing_indices=None,
    rng=None,
):

    definition_text = (
        definition_text.strip()
    )

    words = definition_text.split()


    # --------------------------------------------------------
    # EMPTY DEFINITION
    # --------------------------------------------------------

    if not words:

        return {
            "before_text": "",
            "missing_text": "",
            "after_text": "",
            "hidden_percentage": 0,
            "has_testable_words": False,
            "missing_indices": [],
            "missing_answers": [],
            "question_parts": [],
        }


    # --------------------------------------------------------
    # HIDDEN PERCENTAGE
    # --------------------------------------------------------

    hidden_percentage = (
        get_definition_hidden_percentage(
            mastery_level
        )
    )


    # --------------------------------------------------------
    # NUMBER OF MEANINGFUL WORDS TO HIDE
    #
    # Articles, conjunctions, prepositions, and similar filler
    # words stay visible. The percentage is therefore calculated
    # from the words that are actually useful to recall.
    # --------------------------------------------------------

    testable_indices = [
        index
        for index, word in enumerate(words)
        if is_testable_definition_word(word)
    ]

    # A definition made only of filler words is not useful study material,
    # but returning an empty question keeps this helper predictable and avoids
    # making one of those filler words a surprise test target.
    if not testable_indices:
        return {
            "before_text": definition_text,
            "missing_text": "",
            "after_text": "",
            "hidden_percentage": hidden_percentage,
            "has_testable_words": False,
            "missing_indices": [],
            "missing_answers": [],
            "question_parts": [
                {
                    "text": word,
                    "is_missing": False,
                    "input_name": f"answer_{index}",
                    "width_ch": max(1, len(word)),
                    "blank_number": None,
                }
                for index, word in enumerate(words)
            ],
        }

    number_to_hide = round(
        len(testable_indices)
        * hidden_percentage
        / 100
    )

    number_to_hide = max(
        1,
        number_to_hide
    )

    number_to_hide = min(
        number_to_hide,
        len(testable_indices)
    )


    # Pick individual words instead of one fixed middle phrase. At higher
    # mastery levels this naturally creates a mix of adjacent and separated
    # blanks while keeping every answer field word-sized.
    if missing_indices is None:
        chooser = rng or random.SystemRandom()
        missing_indices = chooser.sample(
            testable_indices,
            number_to_hide,
        )

    valid_missing_indices = set()
    for raw_index in missing_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index in testable_indices:
            valid_missing_indices.add(index)

    missing_indices = sorted(valid_missing_indices)

    if not missing_indices:
        missing_indices = [testable_indices[0]]

    missing_index_set = set(missing_indices)
    missing_answers = [words[index] for index in missing_indices]
    question_parts = []
    blank_number = 0

    for index, word in enumerate(words):
        is_missing = index in missing_index_set
        if is_missing:
            blank_number += 1
        question_parts.append({
            "text": word,
            "is_missing": is_missing,
            "input_name": f"answer_{index}",
            "width_ch": max(1, len(word)),
            "blank_number": blank_number if is_missing else None,
        })

    first_missing = missing_indices[0]
    last_missing = missing_indices[-1]
    before_text = " ".join(words[:first_missing])
    after_text = " ".join(words[last_missing + 1:])
    missing_text = " ".join(missing_answers)


    return {
        "before_text":
            before_text,

        "missing_text":
            missing_text,

        "after_text":
            after_text,

        "hidden_percentage":
            hidden_percentage,

        "has_testable_words":
            True,

        "missing_indices":
            missing_indices,

        "missing_answers":
            missing_answers,

        "question_parts":
            question_parts,
    }


# ============================================================
# SIGNED QUESTION STATE
# ============================================================

DEFINITION_QUESTION_SALT = "studigarden.definition-question.v2"


def create_definition_question_token(definition, question, progress):
    return signing.dumps(
        {
            "definition_id": definition.pk,
            "missing_indices": question["missing_indices"],
            "mastery_level": progress.mastery_level,
            "review_count": progress.review_count,
        },
        salt=DEFINITION_QUESTION_SALT,
    )


def read_definition_question_token(token, definition, progress):
    state = signing.loads(
        token,
        salt=DEFINITION_QUESTION_SALT,
        max_age=60 * 60 * 24,
    )
    if state.get("definition_id") != definition.pk:
        raise signing.BadSignature("Question does not match definition")
    if (
        state.get("mastery_level") != progress.mastery_level
        or state.get("review_count") != progress.review_count
    ):
        raise signing.BadSignature("Question has already been answered")
    indices = state.get("missing_indices")
    if not isinstance(indices, list) or not indices:
        raise signing.BadSignature("Question has no blanks")
    try:
        return [int(index) for index in indices]
    except (TypeError, ValueError):
        raise signing.BadSignature("Question contains invalid blanks")


# ============================================================
# NORMALIZE ANSWER
# ============================================================

def normalize_definition_answer(
    text
):

    return " ".join(
        text.split()
    ).casefold()


# ============================================================
# GET SUBJECT INDEX
# ============================================================

def get_subject_index(
    request,
    subject
):

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )


    # --------------------------------------------------------
    # DATABASE ID
    # --------------------------------------------------------

    for index, subject_data in enumerate(
        subjects
    ):

        if (
            subject_data.get(
                "database_id"
            )
            == subject.id
        ):

            return index


    # --------------------------------------------------------
    # FALLBACK TO SUBJECT NAME
    # --------------------------------------------------------

    for index, subject_data in enumerate(
        subjects
    ):

        if (
            subject_data.get(
                "name",
                ""
            ).strip()
            == subject.name
        ):

            return index


    return 0


# ============================================================
# CHECK WHETHER DEFINITION IS DUE
# ============================================================

def definition_is_due(
    user,
    definition,
    now=None,
):

    if now is None:

        now = timezone.now()


    progress = (
        StudentKnowledge.objects
        .filter(
            student=user,
            knowledge_unit=(
                definition.knowledge_unit
            ),
        )
        .first()
    )


    # --------------------------------------------------------
    # NEVER REVIEWED
    # --------------------------------------------------------

    if progress is None:

        return True


    # --------------------------------------------------------
    # PROGRESS EXISTS BUT NEVER REVIEWED
    # --------------------------------------------------------

    if progress.review_count == 0:

        return True


    # --------------------------------------------------------
    # REVIEW DATE HAS ARRIVED
    # --------------------------------------------------------

    if (
        progress.next_review
        is not None
        and
        progress.next_review
        <= now
    ):

        return True


    return False


# ============================================================
# GET NEXT SUBJECT DEFINITION
# ============================================================

def get_next_subject_definition(
    user,
    current_definition,
):

    """
    Find the next definition due for the same subject.

    Subject review does NOT wrap around.

    Once all definitions due for this subject have been
    reviewed, return None.
    """

    subject = (
        current_definition
        .knowledge_unit
        .subject
    )

    planned_ids = remaining_review_ids(user, get_daily_review_plan(user))

    now = timezone.now()


    definitions = (
        Definition.objects
        .filter(
            knowledge_unit_id__in=planned_ids,
            knowledge_unit__subject=subject,

            knowledge_unit__subject__in=accessible_subjects(user),

            knowledge_unit__knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .DEFINITION
            ),

            knowledge_unit__active=True,
        )
        .exclude(
            id=current_definition.id
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "id"
        )
    )


    # --------------------------------------------------------
    # RETURN FIRST DEFINITION STILL DUE
    # --------------------------------------------------------

    for definition in definitions:

        if definition_is_due(
            user,
            definition,
            now,
        ):

            return definition


    # --------------------------------------------------------
    # FINISHED THIS SUBJECT'S DAILY REVIEW
    # --------------------------------------------------------

    return None


# ============================================================
# GET NEXT GLOBAL DEFINITION
# ============================================================

def get_next_global_definition(
    user,
    current_definition,
):

    """
    Global manual review.

    Global review may move between subjects
    and may wrap around.
    """

    definitions = (
        Definition.objects
        .filter(
            knowledge_unit__subject__in=accessible_subjects(user),

            knowledge_unit__knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .DEFINITION
            ),

            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "id"
        )
    )


    # --------------------------------------------------------
    # NEXT DEFINITION
    # --------------------------------------------------------

    next_definition = (
        definitions
        .filter(
            id__gt=current_definition.id
        )
        .first()
    )


    if next_definition is not None:

        return next_definition


    # --------------------------------------------------------
    # GLOBAL REVIEW MAY WRAP
    # --------------------------------------------------------

    return (
        definitions
        .exclude(
            id=current_definition.id
        )
        .first()
    )


# ============================================================
# GET NEXT DEFINITION
# ============================================================

def get_next_definition_for_review(
    user,
    current_definition,
    review_scope="global",
):

    # --------------------------------------------------------
    # SUBJECT REVIEW
    # --------------------------------------------------------

    if review_scope == "subject":

        return (
            get_next_subject_definition(
                user,
                current_definition,
            )
        )


    # --------------------------------------------------------
    # GLOBAL REVIEW
    # --------------------------------------------------------

    return (
        get_next_global_definition(
            user,
            current_definition,
        )
    )


# ============================================================
# BUILD NEXT REVIEW URL
# ============================================================

def build_definition_review_url(
    definition,
    review_scope,
    subject_index,
):

    url = reverse(
        "practice_definition_review",
        kwargs={
            "definition_id":
                definition.id,
        }
    )


    # --------------------------------------------------------
    # SUBJECT REVIEW
    # --------------------------------------------------------

    if review_scope == "subject":

        return (
            f"{url}"
            f"?review_scope=subject"
            f"&subject_index={subject_index}"
        )


    # --------------------------------------------------------
    # GLOBAL REVIEW
    # --------------------------------------------------------

    return url


# ============================================================
# PRACTICE DEFINITION
# ============================================================

@login_required
def practice_definition(
    request,
    definition_id
):

    # ========================================================
    # GET DEFINITION
    # ========================================================

    definition = get_object_or_404(
        Definition,
        id=definition_id,
        knowledge_unit__subject__in=accessible_subjects(request.user)
    )

    knowledge_unit = (
        definition.knowledge_unit
    )

    subject = (
        knowledge_unit.subject
    )


    # ========================================================
    # DETERMINE REVIEW SCOPE
    # ========================================================

    review_scope = (
        request.POST.get(
            "review_scope"
        )
        or request.GET.get(
            "review_scope"
        )
        or "global"
    )


    if review_scope not in (
        "global",
        "subject",
    ):

        review_scope = "global"


    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = (
        request.POST.get(
            "subject_index"
        )
        or request.GET.get(
            "subject_index"
        )
    )


    if subject_index is None:

        subject_index = (
            get_subject_index(
                request,
                subject
            )
        )


    try:

        subject_index = int(
            subject_index
        )

    except (
        TypeError,
        ValueError,
    ):

        subject_index = (
            get_subject_index(
                request,
                subject
            )
        )


    # ========================================================
    # GET OR CREATE PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects.get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )


    # ========================================================
    # CREATE QUESTION
    # ========================================================

    missing_indices = None
    is_answer_submission = (
        request.method == "POST"
        and request.POST.get("action") != "continue"
    )

    if is_answer_submission and request.POST.get("question_token"):
        try:
            missing_indices = read_definition_question_token(
                request.POST["question_token"],
                definition,
                progress,
            )
        except signing.BadSignature:
            return HttpResponseBadRequest(
                "This definition question has expired. Please reopen it and try again."
            )

    question = (
        create_definition_question(
            definition.definition,
            progress.mastery_level,
            missing_indices=missing_indices,
        )
    )


    before_text = question[
        "before_text"
    ]

    missing_text = question[
        "missing_text"
    ]

    after_text = question[
        "after_text"
    ]

    hidden_percentage = question[
        "hidden_percentage"
    ]

    question_parts = question[
        "question_parts"
    ]

    missing_answers = question[
        "missing_answers"
    ]

    has_testable_words = question["has_testable_words"]

    question_token = None
    if has_testable_words:
        question_token = create_definition_question_token(
            definition,
            question,
            progress,
        )


    # ========================================================
    # NEXT BUTTON
    # ========================================================

    if (
        request.method == "POST"
        and request.POST.get(
            "action"
        ) == "continue"
    ):

        next_definition = (
            get_next_definition_for_review(
                request.user,
                definition,
                review_scope,
            )
        )


        # ----------------------------------------------------
        # ANOTHER DEFINITION EXISTS
        # ----------------------------------------------------

        if next_definition is not None:

            return redirect(
                build_definition_review_url(
                    next_definition,
                    review_scope,
                    subject_index,
                )
            )


        # ----------------------------------------------------
        # SUBJECT REVIEW FINISHED
        #
        # Return directly to this subject's page.
        # ----------------------------------------------------

        if review_scope == "subject":

            return redirect(
                "subject_detail",
                subject_index=subject_index
            )


        # ----------------------------------------------------
        # GLOBAL REVIEW FINISHED
        # ----------------------------------------------------

        return redirect(
            "review_definitions"
        )


    # ========================================================
    # SUBMIT ANSWER
    # ========================================================

    if request.method == "POST":

        if not has_testable_words:
            return HttpResponseBadRequest(
                "This definition has no meaningful words to test."
            )

        answers = []

        for index in question["missing_indices"]:
            field_name = f"answer_{index}"
            value = request.POST.get(field_name)
            if value is None and len(question["missing_indices"]) == 1:
                # Keep older clients and tests compatible with the former
                # single answer field.
                value = request.POST.get("answer", "")
            answers.append((value or "").strip())

        answer = " ".join(answers)


        # ----------------------------------------------------
        # NORMALIZE ANSWERS
        # ----------------------------------------------------

        is_correct = all(
            normalize_definition_answer(given)
            == normalize_definition_answer(expected)
            for given, expected in zip(answers, missing_answers)
        )


        # ====================================================
        # UPDATE REVIEW DATA
        # ====================================================

        progress.review_count += 1

        progress.last_reviewed = (
            timezone.now()
        )


        # ====================================================
        # CORRECT
        # ====================================================

        if is_correct:

            progress.correct_count += 1


            if progress.mastery_level < 6:

                progress.mastery_level += 1


            interval = (
                get_definition_review_interval(
                    progress.mastery_level
                )
            )


            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=interval
                )
            )


            result = "correct"


        # ====================================================
        # INCORRECT
        # ====================================================

        else:

            progress.incorrect_count += 1


            if progress.mastery_level > 0:

                progress.mastery_level -= 1


            # ------------------------------------------------
            # Incorrect definitions return tomorrow.
            # ------------------------------------------------

            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=1
                )
            )


            result = "incorrect"


        progress.save()


        # ====================================================
        # FIND NEXT DEFINITION
        # ====================================================

        next_definition = (
            get_next_definition_for_review(
                request.user,
                definition,
                review_scope,
            )
        )


        # ====================================================
        # DETERMINE WHETHER SUBJECT REVIEW IS FINISHED
        # ====================================================

        subject_review_finished = (
            review_scope == "subject"
            and next_definition is None
        )


        # ====================================================
        # SHOW RESULT
        # ====================================================

        return render(
            request,
            "practice/practice_definition.html",
            {
                "definition":
                    definition,

                "progress":
                    progress,

                "before_text":
                    before_text,

                "missing_text":
                    missing_text,

                "after_text":
                    after_text,

                "hidden_percentage":
                    hidden_percentage,

                "question_parts":
                    question_parts,

                "question_token":
                    question_token,

                "no_testable_words":
                    False,

                "answer":
                    answer,

                "is_correct":
                    is_correct,

                "result":
                    result,

                "submitted":
                    True,

                "subject_index":
                    subject_index,

                "next_definition":
                    next_definition,

                "review_scope":
                    review_scope,

                "subject_review_finished":
                    subject_review_finished,
            }
        )


    # ========================================================
    # FIRST DISPLAY
    # ========================================================

    return render(
        request,
        "practice/practice_definition.html",
        {
            "definition":
                definition,

            "progress":
                progress,

            "before_text":
                before_text,

            "missing_text":
                missing_text,

            "after_text":
                after_text,

            "hidden_percentage":
                hidden_percentage,

            "question_parts":
                question_parts,

            "question_token":
                question_token,

            "no_testable_words":
                not has_testable_words,

            "submitted":
                False,

            "subject_index":
                subject_index,

            "review_scope":
                review_scope,

            "subject_review_finished":
                False,
        }
    )
