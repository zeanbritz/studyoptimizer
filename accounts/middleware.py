from copy import deepcopy
from datetime import date, datetime


class WorkspaceSessionPersistenceMiddleware:
    """
    Bridge the existing session-based views to persistent database records.

    StudyProfile and Subject are the source of truth. The session remains a
    compatibility layer while the older views are progressively simplified.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        was_authenticated = request.user.is_authenticated

        if was_authenticated:
            self._restore_workspace(request)

            # Persist before LogoutView securely flushes the session.
            self._save_workspace(request)

        response = self.get_response(request)

        # LoginView changes request.user during the request. Only a newly
        # authenticated request needs restoring here; restoring a normal POST
        # would overwrite the edits that its view just placed in the session.
        if request.user.is_authenticated:
            if not was_authenticated:
                self._restore_workspace(request)

            self._save_workspace(request)

        return response

    @staticmethod
    def _parse_integer(value, minimum, maximum):
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            return None

        if minimum <= parsed_value <= maximum:
            return parsed_value

        return None

    @staticmethod
    def _parse_date(value):
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        if not value:
            return None

        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    @classmethod
    def _restore_workspace(cls, request):
        from dashboard.models import StudyProfile
        from learning.models import Subject

        profile_record = StudyProfile.objects.filter(
            user=request.user
        ).first()
        database_subjects = list(
            Subject.objects.filter(user=request.user).order_by(
                "created",
                "id",
            )
        )
        session_changed = False

        if profile_record is not None:
            restored_profile = {
                "workspace_name": profile_record.workspace_name,
                "target_grade": (
                    profile_record.target_grade
                    if profile_record.target_grade is not None
                    else ""
                ),
                "study_hours": (
                    profile_record.study_hours
                    if profile_record.study_hours is not None
                    else ""
                ),
                "subject_count": max(
                    profile_record.subject_count,
                    len(database_subjects),
                ),
            }

            if request.session.get("onboarding_profile") != restored_profile:
                request.session["onboarding_profile"] = restored_profile
                session_changed = True
        elif (
            database_subjects
            and "onboarding_profile" not in request.session
        ):
            request.session["onboarding_profile"] = {
                "workspace_name": "My studies",
                "target_grade": "",
                "study_hours": "",
                "subject_count": len(database_subjects),
            }
            session_changed = True

        session_subjects = [
            {
                "name": subject.name,
                "target_grade": (
                    subject.target_grade
                    if subject.target_grade is not None
                    else ""
                ),
                "exam_date": (
                    subject.exam_date.isoformat()
                    if subject.exam_date is not None
                    else ""
                ),
                "definitions": [],
                "formulas": [],
                "database_id": subject.id,
            }
            for subject in database_subjects
        ]

        planned_count = len(session_subjects)

        if profile_record is not None:
            planned_count = max(
                planned_count,
                profile_record.subject_count,
            )

        while len(session_subjects) < planned_count:
            session_subjects.append(
                {
                    "name": "",
                    "target_grade": "",
                    "exam_date": "",
                    "definitions": [],
                    "formulas": [],
                    "database_id": None,
                }
            )

        if profile_record is not None or database_subjects:
            if request.session.get("onboarding_subjects") != session_subjects:
                request.session["onboarding_subjects"] = session_subjects
                session_changed = True

        if profile_record is not None:
            restored_complete = profile_record.onboarding_complete

            if (
                request.session.get("onboarding_complete")
                != restored_complete
            ):
                request.session["onboarding_complete"] = restored_complete
                session_changed = True
        elif (
            database_subjects
            and "onboarding_complete" not in request.session
        ):
            request.session["onboarding_complete"] = True
            session_changed = True

        subjects = request.session.get("onboarding_subjects")
        profile = request.session.get("onboarding_profile")

        if isinstance(subjects, list) and isinstance(profile, dict):
            subject_count = len(subjects)

            if profile.get("subject_count") != subject_count:
                profile = deepcopy(profile)
                profile["subject_count"] = subject_count
                request.session["onboarding_profile"] = profile
                session_changed = True

        if session_changed:
            request.session.modified = True

    @classmethod
    def _save_workspace(cls, request):
        from dashboard.models import StudyProfile
        from learning.models import Subject

        profile_data = request.session.get("onboarding_profile")
        subject_entries = request.session.get("onboarding_subjects")
        onboarding_complete = bool(
            request.session.get("onboarding_complete", False)
        )

        if not isinstance(profile_data, dict):
            profile_data = None

        if not isinstance(subject_entries, list):
            subject_entries = None

        if profile_data is None and subject_entries is None:
            return

        subject_count = (
            len(subject_entries)
            if subject_entries is not None
            else cls._parse_integer(
                profile_data.get("subject_count"),
                0,
                20,
            ) or 0
        )

        if profile_data is not None:
            profile_record, created = StudyProfile.objects.get_or_create(
                user=request.user
            )
            profile_values = {
                "workspace_name": str(
                    profile_data.get("workspace_name", "")
                ).strip()[:150],
                "target_grade": cls._parse_integer(
                    profile_data.get("target_grade"),
                    0,
                    100,
                ),
                "study_hours": cls._parse_integer(
                    profile_data.get("study_hours"),
                    1,
                    168,
                ),
                "subject_count": min(subject_count, 20),
                "onboarding_complete": onboarding_complete,
            }
            profile_changed = created

            for field_name, field_value in profile_values.items():
                if getattr(profile_record, field_name) != field_value:
                    setattr(profile_record, field_name, field_value)
                    profile_changed = True

            if profile_changed:
                profile_record.save()

        if subject_entries is None:
            return

        session_changed = False

        for index, entry in enumerate(subject_entries):
            if not isinstance(entry, dict):
                continue

            subject_name = str(entry.get("name", "")).strip()[:100]

            if not subject_name:
                continue

            subject = None
            database_id = entry.get("database_id")

            try:
                database_id = int(database_id)
            except (TypeError, ValueError):
                database_id = None

            if database_id is not None:
                subject = Subject.objects.filter(
                    pk=database_id,
                    user=request.user,
                ).first()

            if subject is None:
                subject = Subject.objects.filter(
                    user=request.user,
                    name=subject_name,
                ).order_by("created", "id").first()

            if subject is None:
                subject = Subject.objects.create(
                    user=request.user,
                    name=subject_name,
                )

            target_grade = cls._parse_integer(
                entry.get("target_grade"),
                0,
                100,
            )
            exam_date = cls._parse_date(entry.get("exam_date"))
            subject_changed = False

            if subject.name != subject_name:
                subject.name = subject_name
                subject_changed = True

            if subject.target_grade != target_grade:
                subject.target_grade = target_grade
                subject_changed = True

            if subject.exam_date != exam_date:
                subject.exam_date = exam_date
                subject_changed = True

            if subject_changed:
                subject.save()

            if entry.get("database_id") != subject.id:
                updated_entry = deepcopy(entry)
                updated_entry["database_id"] = subject.id
                subject_entries[index] = updated_entry
                session_changed = True

        if session_changed:
            request.session["onboarding_subjects"] = subject_entries
            request.session.modified = True
