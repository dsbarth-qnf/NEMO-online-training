import json
import os
import urllib.parse
from datetime import timedelta
from logging import getLogger
from typing import Optional

from NEMO.constants import MEDIA_PROTECTED
from NEMO.models import User, UserType
from NEMO.utilities import format_datetime, queryset_search_filter, render_email_template
from NEMO.views.pagination import SortedPaginator
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.views.static import serve

from NEMO_online_training.customization import OnlineTrainingCustomization
from NEMO_online_training.forms import TrainingRecordForm, TrainingUserForm
from NEMO_online_training.models import Training, TrainingAttempt, TrainingRecord, TrainingUser
from NEMO_online_training.utilities import ONLINE_TRAINING_ACTION_QUALIFY_TOOL

online_training_logger = getLogger(__name__)


def has_online_training_staff_permissions(user):
    # all staff except accounting officers, plus users who specifically have the permission
    return user.is_active and (
        user.is_facility_manager
        or user.is_staff
        or user.is_user_office
        or user.is_superuser
        or user.has_perm("NEMO-online-training.add_training")
    )


def has_online_training_full_permissions(user: User) -> bool:
    # everyone above except staff-only
    return (
        user.is_superuser
        or user.is_user_office
        or user.is_facility_manager
        or user.has_perm("NEMO-online-training.add_training")
    )


def can_staff_manage_training(user: User, training: Training) -> bool:
    """Checks if staff can manage a training based on role, permission, or tool ownership."""
    if has_online_training_full_permissions(user):
        return True

    if user.is_staff:
        # Restrict staff tools to the tools they are responsible for (and not all tools)
        user_tool_ids = {tool.id for tool in user.my_tools() or []}

        if user_tool_ids:
            training_tool_ids = get_qualification_tool_ids_for_training(training)
            if user_tool_ids.intersection(training_tool_ids):
                return True

    return False


def get_qualification_tool_ids_for_training(training: Training) -> set[int]:
    """Retrieves tool IDs configured under the 'tool_ids' key for qualification actions."""
    tool_ids: set[int] = set()

    for action in training.action_set.all():
        if action.action_type == ONLINE_TRAINING_ACTION_QUALIFY_TOOL:
            config = action.configuration or {}
            for tid in config.get("tool_ids", []):
                try:
                    tool_ids.add(int(tid))
                except (ValueError, TypeError):
                    online_training_logger.warning(
                        f"Invalid tool ID '{tid}' in {training} training action configuration."
                    )

    return tool_ids


@login_required
@require_GET
def user_online_trainings(request, training_user_id=None):
    user: User = request.user
    selected_status = request.GET.get("training_status", "incomplete")
    selected_user_type = request.GET.get("user_type", "")

    user_has_staff_permissions = has_online_training_staff_permissions(user)
    is_full_admin = has_online_training_full_permissions(user)

    single_user_view = training_user_id or not user_has_staff_permissions

    training_users = TrainingUser.objects_with_trainings()
    if not user_has_staff_permissions:
        training_users = training_users.filter(nemo_user=user)
    elif training_user_id:
        training_users = training_users.filter(id=training_user_id)

    available_trainings = Training.objects.filter(enabled=True)
    manageable_ids = None
    if user_has_staff_permissions and not is_full_admin:
        # Determine available/manageable training for staff who are not full admins
        user_tool_ids = {tool.id for tool in (user.my_tools() or [])}
        manageable_ids = {
            t.id
            for t in available_trainings.prefetch_related("action_set")
            if user_tool_ids.intersection(get_qualification_tool_ids_for_training(t))
        }
        available_trainings = available_trainings.filter(id__in=manageable_ids)

    if not single_user_view:
        # Filter out TrainingUsers who have no records for trainings this staff can manage
        if user_has_staff_permissions and not is_full_admin:
            training_users = training_users.filter(trainingrecord__training_id__in=manageable_ids).distinct()

        # Status and user type filters
        if selected_status == "complete":
            training_users = training_users.filter(all_trainings_completed=True)
        elif selected_status == "incomplete":
            training_users = training_users.filter(all_trainings_completed=False, total_trainings__gt=0)
        elif selected_status == "empty":
            training_users = training_users.filter(total_trainings=0)
        if selected_user_type == "new":
            training_users = training_users.filter(nemo_user__isnull=True)
        elif selected_user_type == "nemo":
            training_users = training_users.filter(nemo_user__isnull=False)

    page = SortedPaginator(training_users, request, order_by="-last_updated").get_current_page()

    for training_user in page:
        training_user.available_trainings = list()
        # filter out trainings that don't apply to the user
        for online_training in available_trainings:
            if online_training.applies_to_user(training_user):
                training_user.available_trainings.append(online_training)
        # filter out non-manageable training records
        training_user.training_records = [
            rec
            for rec in training_user.trainingrecord_set.all()
            if manageable_ids is None or rec.training_id in manageable_ids
        ]

    dictionary = {
        "page": page,
        "user_types": UserType.objects.all(),
        "user_is_staff": user_has_staff_permissions,
        "single_user_view": single_user_view,
        "selected_status": selected_status,
        "selected_user_type": selected_user_type,
    }
    return render(request, "NEMO_online_training/user_trainings/user_trainings.html", dictionary)


@require_GET
@user_passes_test(has_online_training_staff_permissions)
def search_training_users(request):
    return render(
        request,
        "NEMO_online_training/user_trainings/user_search.html",
        {"form": TrainingUserForm(), "user_types": UserType.objects.all()},
    )


@user_passes_test(has_online_training_staff_permissions)
@require_GET
def training_users_search_results(request):
    nemo_users: HttpResponse = queryset_search_filter(
        User.objects.all(), ["first_name", "last_name", "username", "email"], request
    )
    training_users: HttpResponse = queryset_search_filter(
        TrainingUser.objects.all(), ["_first_name", "_last_name", "_email"], request
    )
    return HttpResponse(
        json.dumps(json.loads(training_users.content) + json.loads(nemo_users.content)), "application/json"
    )


@user_passes_test(has_online_training_staff_permissions)
@require_GET
def create_training_user_from_nemo_user(request, nemo_user_id):
    nemo_user = get_object_or_404(User, pk=nemo_user_id)
    training_user = TrainingUser.create_from_nemo_user(nemo_user)
    return redirect("online_user_trainings", training_user_id=training_user.id)


@user_passes_test(has_online_training_staff_permissions)
@require_POST
def create_training_user(request):
    form = TrainingUserForm(request.POST or None)
    if form.is_valid():
        training_user = form.save()
        return redirect("online_user_trainings", training_user_id=training_user.id)
    return render(
        request,
        "NEMO_online_training/user_trainings/user_search.html",
        {"form": form, "user_types": UserType.objects.all()},
    )


@login_required
@require_GET
def create_nemo_user_from_new_user(request, training_user_id):
    training_user = get_object_or_404(TrainingUser, pk=training_user_id)
    nemo_new_user_url = reverse("create_or_modify_user", kwargs={"user_id": "new"})
    safe_notes = urllib.parse.quote(training_user.notes)
    return redirect(
        f"{nemo_new_user_url}?first_name={training_user.first_name}&last_name={training_user.last_name}&email={training_user.email}&type={training_user.user_type_id if training_user.user_type_id is not None else ''}&notes={safe_notes}&correlation_id={training_user_id}"
    )


@login_required
@require_GET
def training_without_assignment(request, online_training_id):
    online_training = get_object_or_404(Training, pk=online_training_id)
    if not online_training.allow_self_enrollment:
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {
                "title": "Error",
                "message": "This training is not available for self enrollment, contact staff to be assigned this training",
            },
        )
    if not online_training.enabled:
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {"title": "Error", "message": "This training is not available anymore"},
        )

    training_user = TrainingUser.create_from_nemo_user(request.user)
    if not online_training.applies_to_user(training_user):
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {"title": "Error", "message": "This training is not available for your user type"},
        )

    uncleared_failures = TrainingRecord.objects.filter(
        training_user=training_user, training=online_training, status=TrainingRecord.TrainingStatus.FAILED
    ).exists()
    if uncleared_failures:
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {
                "title": "Error",
                "message": "You have failed this training and have not been cleared to retake it. Please contact staff.",
            },
        )

    online_user_training, created = TrainingRecord.objects.filter(
        Q(due_date__gte=timezone.now()) | Q(due_date__isnull=True)
    ).get_or_create(training_user=training_user, training=online_training, end=None)

    return redirect("online_training_user_training", user_training_id=online_user_training.id)


@require_GET
@login_required
def user_training(request, user_training_id):
    online_training_user = get_object_or_404(TrainingRecord, pk=user_training_id)
    if not online_training_user.training_user.nemo_user or request.user != online_training_user.training_user.nemo_user:
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {"title": "Error", "message": "You do not have permission to complete this training"},
        )

    return redirect(online_training_user.generate_link())


@user_passes_test(has_online_training_staff_permissions)
@require_POST
def add_training_to_user(request, training_user_id, online_training_id):
    training_user = get_object_or_404(TrainingUser, pk=training_user_id)
    online_training = get_object_or_404(Training, pk=online_training_id)

    if not can_staff_manage_training(request.user, online_training):
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["You do not have permission to assign this training."]}},
            status=403,
        )

    form = TrainingRecordForm(request.POST)
    form.instance.training_user = training_user
    form.instance.training = online_training

    if form.is_valid():
        online_training_user = form.save()
        online_training_user.generate_and_send_new_email()
        return JsonResponse({"success": True})
    else:
        errors = {}
        for field, error_list in form.errors.items():
            errors[field] = error_list
        return JsonResponse({"success": False, "errors": errors}, status=400)


@require_GET
@ensure_csrf_cookie
def public_user_training(request, signed_user_training_id):
    user_training_id = None

    try:
        signer = TimestampSigner()
        max_age = OnlineTrainingCustomization.get_int("online_training_link_validity_minutes") * 60

        # Just check validity
        user_training_id = signer.unsign(signed_user_training_id)
        online_training_user = get_object_or_404(TrainingRecord, id=user_training_id)
        if online_training_user.status != TrainingRecord.TrainingStatus.IN_PROGRESS:
            return render(
                request,
                "NEMO_online_training/error_message.html",
                {
                    "title": online_training_user.get_status_display(),
                    "message": (
                        _("You have failed this training and exhausted all attempts. Please contact staff.")
                        if online_training_user.status == TrainingRecord.TrainingStatus.FAILED
                        else _("This training has been completed!")
                    ),
                },
            )

        # Now check the time limit
        user_training_id = signer.unsign(signed_user_training_id, max_age=max_age)
    except (BadSignature, SignatureExpired) as e:
        if isinstance(e, SignatureExpired) and request.user and request.user.is_authenticated:
            return redirect("online_training_user_training", user_training_id=user_training_id)
        return render(
            request,
            "NEMO_online_training/public/invalid_training_link.html",
            {"user_training_id": user_training_id},
        )

    online_training_user.training_user.last_accessed = timezone.now()
    online_training_user.training_user.save(update_fields=["last_accessed"])

    error = check_training_validity(online_training_user)
    if error:
        return render(request, "NEMO_online_training/error_message.html", {"title": "Error", "message": error})

    # --- QUIZ ENGINE: Verify attempt eligibility ---
    eligibility = check_attempt_eligibility(online_training_user)
    if not eligibility["allowed"]:
        return render(
            request,
            "NEMO_online_training/error_message.html",
            {"title": "Training Locked", "message": eligibility["message"]},
        )
    # -----------------------------------------------

    completion_token = TimestampSigner().sign(user_training_id)
    online_training_user.start = timezone.now()
    online_training_user.save(update_fields=["start"])

    training_context = {
        "training_user": online_training_user.training_user,
        "training": online_training_user.training,
        "record": online_training_user,
        "completion_token": completion_token,
    }

    online_training_rendered = render_email_template(
        online_training_user.training.html_content, training_context, request
    )
    return render(
        request,
        "NEMO_online_training/public/user_training.html",
        {
            "online_training_user": online_training_user,
            "online_training_rendered": online_training_rendered,
            "expires_at": online_training_user.start
            + timedelta(minutes=online_training_user.training.completion_time_limit),
            "completion_token": completion_token,
        },
    )


@require_POST
def public_generate_user_training_email(request, user_training_id):
    online_training_user = TrainingRecord.objects.filter(id=user_training_id).first()
    if not online_training_user:
        if request.POST.get("popup"):
            return HttpResponseBadRequest(_("Invalid link"))
        else:
            return render(
                request,
                "NEMO_online_training/error_message.html",
                {"title": "Error", "message": _("Invalid link")},
                status=400,
            )
    online_training_user.generate_and_send_new_email()
    return render(request, "NEMO_online_training/public/new_link_email_confirmation.html")


@require_POST
def public_complete_user_training(request):
    signed_user_training_id = request.POST.get("completion_token")
    user_training_id = None

    try:
        signer = TimestampSigner()
        user_training_id = signer.unsign(signed_user_training_id)
        online_training_user = get_object_or_404(TrainingRecord, pk=user_training_id)
        dynamic_limit_seconds = online_training_user.training.completion_time_limit * 60
        signer.unsign(signed_user_training_id, max_age=dynamic_limit_seconds)
    except (BadSignature, SignatureExpired):
        return render(
            request, "NEMO_online_training/public/invalid_training_link.html", {"user_training_id": user_training_id}
        )

    error = check_training_validity(online_training_user)
    if error:
        return render(request, "NEMO_online_training/error_message.html", {"title": "Error", "message": error})
    else:
        data = {}
        for key, values in request.POST.lists():
            # remove completion token and csrf token from the completion data
            if key in ["csrfmiddlewaretoken", "completion_token"]:
                continue
            if len(values) == 1:
                data[key] = values[0]
            else:
                data[key] = values

        # --- QUIZ ENGINE: Process submission and grading ---
        attempt = process_training_submission(online_training_user, data)
        max_attempts = online_training_user.training.max_attempts
        attempts_taken = TrainingAttempt.objects.filter(training_record=online_training_user).count()
        if not max_attempts:  # 0 or None means unlimited
            attempts_remaining = "unlimited"
        else:
            attempts_remaining = max_attempts - attempts_taken
        # Only finalize the record (mark completed/failed, fire actions) if they passed or ran out of attempts
        if attempt.passed or max_attempts and attempts_taken >= max_attempts:
            online_training_user.complete(data, attempt.passed)

        return JsonResponse(
            {
                "success": True,
                "passed": attempt.passed,
                "score": attempt.score_percentage,
                "attempts_remaining": attempts_remaining,
            }
        )


@xframe_options_sameorigin
def serve_training_media_file(request, signed_user_training_id, file_path):
    user_training_id = None
    try:
        signer = TimestampSigner()
        max_age = OnlineTrainingCustomization.get_int("online_training_link_validity_minutes") * 60

        user_training_id = signer.unsign(signed_user_training_id)
        online_training_user = get_object_or_404(TrainingRecord, id=user_training_id)
        if online_training_user.status == TrainingRecord.TrainingStatus.COMPLETED:
            return render(
                request,
                "NEMO_online_training/error_message.html",
                {"title": "Success", "message": _("This training has been completed!")},
            )

        user_training_id = signer.unsign(signed_user_training_id, max_age=max_age)
    except (BadSignature, SignatureExpired) as e:
        if isinstance(e, SignatureExpired) and request.user and request.user.is_authenticated:
            return redirect("online_training_user", user_training_id=user_training_id)
        return render(
            request,
            "NEMO_online_training/public/invalid_training_link.html",
            {"user_training_id": user_training_id},
        )

    if os.path.normpath(os.path.join(settings.MEDIA_ROOT, file_path)).startswith(MEDIA_PROTECTED):
        return HttpResponseForbidden()

    return serve(request, file_path, document_root=settings.MEDIA_ROOT)


def check_training_validity(online_user_training: TrainingRecord) -> Optional[Promise | str]:
    if not online_user_training.training.enabled:
        return _("This training is not available anymore!")
    if online_user_training.status == TrainingRecord.TrainingStatus.FAILED:
        return _("You have failed this training and exhausted all attempts. Please contact staff.")
    if online_user_training.has_training_expired():
        return _(f"This training expired on {format_datetime(online_user_training.due_date)}")
    if online_user_training.status == TrainingRecord.TrainingStatus.COMPLETED:
        return _("This training has been completed!")
    return None


def check_attempt_eligibility(training_record) -> dict:
    """
    Evaluates if a user is currently allowed to take/retake a quiz.
    Checks failure lockouts and cooldown periods.
    """
    if training_record.status == TrainingRecord.TrainingStatus.FAILED:
        return {
            "allowed": False,
            "message": _("You have exhausted all attempts. Please contact staff to reset your training."),
        }

    training = training_record.training
    attempts_taken = training_record.attempts.count()

    # Check cooldown if they have failed previously but still have attempts remaining
    if attempts_taken > 0 and not training_record.end:
        last_attempt = training_record.attempts.order_by("-timestamp").first()

        if training.retry_cooldown_minutes and last_attempt:
            next_allowed_time = last_attempt.timestamp + timedelta(minutes=training.retry_cooldown_minutes)

            if timezone.now() < next_allowed_time:
                return {
                    "allowed": False,
                    "message": _(f"You did not pass. You can try again on {format_datetime(next_allowed_time)}."),
                }

    return {"allowed": True}


def process_training_submission(training_record, user_responses) -> TrainingAttempt:
    """
    Grades the submission against the answer key.
    Creates a TrainingAttempt audit trail and handles failure logic.
    """
    graded_training = training_record.training

    # SCENARIO A: Simple Completion (No Quiz Configured)
    if not graded_training.answer_key or graded_training.passing_score_percentage is None:
        attempt = TrainingAttempt.objects.create(training_record=training_record, passed=True, responses=user_responses)
        return attempt

    # SCENARIO B: Grading Required
    correct_count = 0
    answer_key = graded_training.answer_key or {}
    total_questions = len(answer_key)
    for question_key, correct_answer in answer_key.items():
        user_answer = user_responses.get(question_key)
        if isinstance(correct_answer, list):
            if not isinstance(user_answer, list):
                user_answer = [user_answer] if user_answer else []

            if set(str(x).strip() for x in correct_answer) == set(str(x).strip() for x in user_answer):
                correct_count += 1
        else:
            if str(correct_answer).strip() == str(user_answer).strip():
                correct_count += 1

    score = (correct_count / total_questions) * 100 if total_questions > 0 else 100.0
    passed = score >= graded_training.passing_score_percentage

    attempt = TrainingAttempt.objects.create(
        training_record=training_record, score_percentage=score, passed=passed, responses=user_responses
    )

    return attempt


@user_passes_test(has_online_training_staff_permissions)
@require_POST
def clear_for_retake(request, record_id):
    # Retrieve the failed record
    record = get_object_or_404(TrainingRecord, id=record_id)
    if not can_staff_manage_training(request.user, record.training):
        return JsonResponse(
            {"success": False, "errors": "You do not have permission to clear this training."}, status=403
        )
    # Update the flag
    if record.status == TrainingRecord.TrainingStatus.FAILED:
        record.status = TrainingRecord.TrainingStatus.IN_PROGRESS
        record.save()

    return JsonResponse({"success": True})
