from typing import Any

from NEMO_online_training.apps import OnlineTrainingConfig

ONLINE_TRAINING_NOTIFICATION_TYPE = "online_trainings"
ONLINE_TRAINING_EMAIL_CATEGORY = OnlineTrainingConfig.get_plugin_id() + 1

ONLINE_TRAINING_ACTION_EXTEND_ACCESS = "EXTEND_ACCESS"
ONLINE_TRAINING_ACTION_REMOVE_TRAINING_REQUIRED = "REMOVE_TRAINING_REQUIRED"
ONLINE_TRAINING_ACTION_SEND_EMAIL = "SEND_EMAIL"
ONLINE_TRAINING_ACTION_GRANT_PHYSICAL_ACCESS = "GRANT_PHYSICAL_ACCESS"
ONLINE_TRAINING_ACTION_QUALIFY_TOOL = "QUALIFY_USER_ON_TOOL"


def validate_training_user(cleaned_data: dict[str, Any] | None, pk: int, admin_form: bool = False):
    from NEMO.models import User
    from NEMO_online_training.models import TrainingUser
    from NEMO_online_training.customization import OnlineTrainingCustomization
    from django.core.exceptions import ValidationError
    from django.utils.translation import gettext_lazy as _

    if not cleaned_data:
        return

    prefix = "_" if admin_form else ""

    errors = {}
    if OnlineTrainingCustomization.get_bool("online_training_user_unique_email"):
        email = cleaned_data.get(prefix + "email", None)
        # Check if the email is already used by another user
        if email:
            if TrainingUser.objects.filter(_email=email).exclude(pk=pk).exists():
                errors[prefix + "email"] = _("This email is already used by another user.")
            if User.objects.filter(email=email).exists():
                errors[prefix + "email"] = _("This email is already used by another NEMO user.")
    if OnlineTrainingCustomization.get_bool("online_training_user_type_required"):
        user_type_field_name = "user_type" if admin_form else "user_type_id"
        if cleaned_data.get(prefix + user_type_field_name, None) is None:
            errors[prefix + user_type_field_name] = _("This field is required.")
    if not cleaned_data.get("nemo_user", None) and admin_form:
        for field in ["_first_name", "_last_name", "_email"]:
            if not cleaned_data.get(field, None):
                errors[field] = _("This field is required.")
    if errors:
        raise ValidationError(errors)
