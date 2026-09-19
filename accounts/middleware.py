from copy import deepcopy
import json

from django.contrib.auth import get_user_model


WORKSPACE_SESSION_KEYS = (
    "onboarding_profile",
    "onboarding_subjects",
    "onboarding_complete",
)


class WorkspaceSessionPersistenceMiddleware:
    """
    Keep the user's subject workspace in the database.

    Django flushes the session on logout for security. The Subjects area used
    to depend entirely on that session, so it appeared empty after the next
    login even though the learning records still existed in the database.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            self._restore_workspace(request)

            # Save before the view runs so LogoutView cannot discard the last
            # copy when it flushes the session.
            self._save_workspace(request)

        response = self.get_response(request)

        # LoginView changes request.user during the request. Running this check
        # again restores the workspace immediately after a successful login.
        if request.user.is_authenticated:
            self._restore_workspace(request)
            self._save_workspace(request)

        return response

    @staticmethod
    def _restore_workspace(request):
        try:
            stored_workspace = json.loads(
                request.user.workspace_data or "{}"
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            stored_workspace = {}

        if not isinstance(stored_workspace, dict):
            stored_workspace = {}

        session_changed = False

        for key in WORKSPACE_SESSION_KEYS:
            if key not in request.session and key in stored_workspace:
                request.session[key] = deepcopy(stored_workspace[key])
                session_changed = True

        # Older accounts may not have workspace_data yet. Their Subject rows
        # still exist, so use them to rebuild the visible Subjects list once.
        if "onboarding_subjects" not in request.session:
            from learning.models import Subject

            database_subjects = list(
                Subject.objects.filter(user=request.user).order_by(
                    "created",
                    "id",
                )
            )

            if database_subjects:
                request.session["onboarding_subjects"] = [
                    {
                        "name": subject.name,
                        "target_grade": "",
                        "exam_date": "",
                        "definitions": [],
                        "formulas": [],
                        "database_id": subject.id,
                    }
                    for subject in database_subjects
                ]
                session_changed = True

                if "onboarding_profile" not in request.session:
                    request.session["onboarding_profile"] = {
                        "workspace_name": "My studies",
                        "target_grade": "",
                        "study_hours": "",
                        "subject_count": len(database_subjects),
                    }
                    session_changed = True

                if "onboarding_complete" not in request.session:
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

    @staticmethod
    def _save_workspace(request):
        workspace = {
            key: deepcopy(request.session[key])
            for key in WORKSPACE_SESSION_KEYS
            if key in request.session
        }

        if not workspace:
            return

        serialized_workspace = json.dumps(
            workspace,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        try:
            stored_workspace = json.loads(
                request.user.workspace_data or "{}"
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            stored_workspace = {}

        if workspace == stored_workspace:
            return

        get_user_model().objects.filter(pk=request.user.pk).update(
            workspace_data=serialized_workspace
        )
        request.user.workspace_data = serialized_workspace
