from abc import ABC, abstractmethod
from http import HTTPStatus
from logging import getLogger
from typing import Dict

import requests
from NEMO.utilities import render_email_template
from NEMO.views.customization import ApplicationCustomization
from NEMO.views.users import get_identity_service
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from NEMO_online_training.fields import UserTypeFilterField
from NEMO_online_training.utilities import (
    ONLINE_TRAINING_ACTION_EXTEND_ACCESS,
    ONLINE_TRAINING_ACTION_GRANT_PHYSICAL_ACCESS,
    ONLINE_TRAINING_ACTION_QUALIFY_TOOL,
    ONLINE_TRAINING_ACTION_REMOVE_TRAINING_REQUIRED,
    ONLINE_TRAINING_ACTION_SEND_EMAIL,
)

training_action_logger = getLogger(__name__)


def has_new_user_filter(user_filter: list[str]) -> bool:
    """
    Helper function to check if user filter includes new users (unlinked to NEMO).
    """
    return UserTypeFilterField.ALL_NEW_USERS in user_filter or any(uf.startswith("n|") for uf in user_filter)


class OnlineTrainingActionHandler(ABC):
    """
    Base class for all online training action handlers.
    Similar to NEMO's interlock pattern.
    """

    @abstractmethod
    def validate(self, action):
        """
        Validate the action configuration and user filter.
        Raise ValidationError if the configuration or user filter is invalid.

        Args:
            action: The Action instance to validate
        """
        if not isinstance(action.configuration, dict):
            raise ValidationError(_("Configuration must be a dictionary"))
        if action.trigger_condition not in self.allowed_trigger_conditions:
            raise ValidationError(
                _(f"the {action.get_trigger_condition_display()} trigger condition is not allowed for this action")
            )

    def perform(self, action, user_training) -> None:
        if action.applies_to_record(user_training):
            self.do_perform(action, user_training)

    @abstractmethod
    def do_perform(self, action, user_training) -> None:
        """
        Perform the action.

        Args:
            action: The Action
            user_training: The TrainingRecord
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Return the name of the action to be saved in the database.
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Return a description of the action to be shown to the user.
        """
        pass

    @property
    @abstractmethod
    def allowed_trigger_conditions(self) -> list:
        """
        Return a list of allowed trigger conditions for this action.
        """
        pass


class ExtendAccessOnlineTrainingHandler(OnlineTrainingActionHandler):
    """Handler for extending user access expiration"""

    @property
    def name(self) -> str:
        return ONLINE_TRAINING_ACTION_EXTEND_ACCESS

    @property
    def description(self) -> str:
        return _("Extend User Access Expiration")

    @property
    def allowed_trigger_conditions(self) -> list:
        from NEMO_online_training.models import Action

        return [Action.TriggerCondition.ON_PASS]

    def validate(self, action) -> None:
        super().validate(action)

        if has_new_user_filter(action.user_filter):
            raise ValidationError({"user_filter": _("New users cannot have their access extended")})

        if "extend_by_days" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'extend_by_days' field")})

        extend_by_days = action.configuration.get("extend_by_days")
        if not isinstance(extend_by_days, (int, float)) or extend_by_days <= 0:
            raise ValidationError({"configuration": _("'extend_by_days' must be a positive number")})

    def do_perform(self, action, user_training) -> None:
        from datetime import timedelta
        from django.utils import timezone

        extend_by_days = action.configuration["extend_by_days"]

        # If the user is linked to a NEMO user
        if user_training.training_user.nemo_user:
            nemo_user = user_training.training_user.nemo_user
            nemo_user.access_expiration = timezone.now() + timedelta(days=extend_by_days)
            nemo_user.save(update_fields=["access_expiration"])
            self._send_update_to_identity_service(nemo_user)

    def _send_update_to_identity_service(self, user):
        identity_service = get_identity_service()
        if identity_service.get("available", False):
            parameters = {
                "username": user.username,
                "domain": user.domain,
                "access_expiration": user.access_expiration,
            }
            try:
                timeout = identity_service.get("timeout", 3)
                result = requests.put(identity_service["url"], data=parameters, timeout=timeout)
                if result.status_code == HTTPStatus.NOT_FOUND:
                    training_action_logger.warning(
                        "The username was not found on this domain. Did you spell the username correctly in this form and did you select the correct domain? Ensure the user exists on the domain in order to proceed."
                    )
                if result.status_code != HTTPStatus.OK:
                    training_action_logger.error(
                        "The identity service encountered a problem while attempting to modify a user. The HTTP error is {}: {}".format(
                            result.status_code, result.text
                        )
                    )
                    training_action_logger.warning(
                        "The user information was not modified because the identity service encountered a problem while creating the corresponding domain account. The administrator has been notified to resolve the problem."
                    )
            except Exception as e:
                training_action_logger.error(
                    "There was a problem communicating with the identity service while attempting to modify a user. An exception was encountered: "
                    + type(e).__name__
                    + " - "
                    + str(e)
                )


class RemoveTrainingRequiredOnlineTrainingHandler(OnlineTrainingActionHandler):
    """Handler for removing training requirement on user"""

    @property
    def name(self) -> str:
        return ONLINE_TRAINING_ACTION_REMOVE_TRAINING_REQUIRED

    @property
    def description(self) -> str:
        return _("Remove training required on user account")

    @property
    def allowed_trigger_conditions(self) -> list:
        from NEMO_online_training.models import Action

        return [Action.TriggerCondition.ON_PASS]

    def validate(self, action) -> None:
        super().validate(action)

        if has_new_user_filter(action.user_filter):
            raise ValidationError(
                {
                    "user_filter": _(
                        f"New users cannot have their {ApplicationCustomization.get('facility_rules_name')} requirement removed"
                    )
                }
            )

    def do_perform(self, action, user_training) -> None:
        # If the user is linked to a NEMO user and has training required
        if user_training.training_user.nemo_user and user_training.training_user.training_required:
            nemo_user = user_training.training_user.nemo_user
            nemo_user.training_required = False
            nemo_user.save(update_fields=["training_required"])


class SendEmailOnlineTrainingHandler(OnlineTrainingActionHandler):
    """Handler for sending notification emails"""

    @property
    def name(self) -> str:
        return ONLINE_TRAINING_ACTION_SEND_EMAIL

    @property
    def description(self) -> str:
        return _("Send Notification Email")

    @property
    def allowed_trigger_conditions(self) -> list:
        from NEMO_online_training.models import Action

        return [Action.TriggerCondition.ON_PASS, Action.TriggerCondition.ON_FAIL]

    def validate(self, action) -> None:
        super().validate(action)

        if "subject" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'subject' field")})

        if "message" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'message' field")})

        if "recipients" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'recipients' field")})

        recipients = action.configuration.get("recipients")
        if not isinstance(recipients, list) or not recipients:
            raise ValidationError({"configuration": _("'recipients' must be a non-empty list")})

        valid_recipient_types = ["user"]
        for recipient in recipients:
            if not isinstance(recipient, str):
                raise ValidationError({"configuration": _("Each recipient must be a string")})
            # Check if it's a valid type or an email
            if recipient not in valid_recipient_types and "@" not in recipient:
                raise ValidationError(
                    {"configuration": _(f"Invalid recipient '{recipient}'. Must be 'user', or a valid email address")}
                )

    def do_perform(self, action, training_record) -> None:
        from NEMO.utilities import send_mail

        from NEMO_online_training.utilities import ONLINE_TRAINING_EMAIL_CATEGORY

        subject = action.configuration["subject"]
        message = action.configuration["message"]
        recipients = action.configuration["recipients"]

        # Format message with available context
        context = {
            "training_user": training_record.training_user,
            "training": training_record.training,
            "record": training_record,
            "action": action,
        }
        formatted_message = render_email_template(message, context)
        formatted_subject = render_email_template(subject, context)

        # Build recipient list
        recipient_emails = []
        for recipient in recipients:
            if recipient == "user":
                recipient_emails.append(training_record.training_user.email)
            else:
                # Assume it's an email address
                recipient_emails.append(recipient)

        if recipient_emails:
            send_mail(
                formatted_subject,
                formatted_message,
                from_email=None,
                to=recipient_emails,
                email_category=ONLINE_TRAINING_EMAIL_CATEGORY,
            )


class GrantPhysicalAccessLevelOnlineTrainingHandler(OnlineTrainingActionHandler):
    """Handler for granting physical access levels to a user"""

    @property
    def name(self) -> str:
        return ONLINE_TRAINING_ACTION_GRANT_PHYSICAL_ACCESS

    @property
    def description(self) -> str:
        return _("Grant Physical Access Level(s)")

    @property
    def allowed_trigger_conditions(self) -> list:
        from NEMO_online_training.models import Action

        return [Action.TriggerCondition.ON_PASS]

    def validate(self, action) -> None:
        super().validate(action)

        if has_new_user_filter(action.user_filter):
            raise ValidationError(
                {"user_filter": _("New users cannot be granted physical access levels. They must be NEMO users first.")}
            )

        if "physical_access_level_ids" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'physical_access_level_ids' field")})

        pal_ids = action.configuration.get("physical_access_level_ids")
        if not isinstance(pal_ids, list) or not pal_ids:
            raise ValidationError(
                {"configuration": _("'physical_access_level_ids' must be a non-empty list of integers")}
            )

        if not all(isinstance(p_id, int) for p_id in pal_ids):
            raise ValidationError({"configuration": _("All items in 'physical_access_level_ids' must be integer IDs")})

        # Verify all requested physical access levels exist in the database
        from NEMO.models import PhysicalAccessLevel

        existing_pal_ids = set(PhysicalAccessLevel.objects.filter(id__in=pal_ids).values_list("id", flat=True))
        missing_pal_ids = set(pal_ids) - existing_pal_ids
        if missing_pal_ids:
            missing_str = ", ".join(str(pid) for pid in missing_pal_ids)
            raise ValidationError(
                {
                    "configuration": _(
                        f"The following physical access level IDs do not exist in the system: {missing_str}"
                    )
                }
            )

    def do_perform(self, action, user_training) -> None:
        from NEMO.models import PhysicalAccessLevel

        # Only applies if they have an established NEMO user account
        nemo_user = user_training.training_user.nemo_user
        if not nemo_user:
            return

        pal_ids = action.configuration.get("physical_access_level_ids", [])
        access_levels = PhysicalAccessLevel.objects.filter(id__in=pal_ids)

        if access_levels.exists():
            nemo_user.physical_access_levels.add(*access_levels)


class QualifyUserOnToolOnlineTrainingHandler(OnlineTrainingActionHandler):
    """Handler for automatically qualifying a user on specific tools"""

    @property
    def name(self) -> str:
        return ONLINE_TRAINING_ACTION_QUALIFY_TOOL

    @property
    def description(self) -> str:
        return _("Qualify User on Tool(s)")

    @property
    def allowed_trigger_conditions(self) -> list:
        from NEMO_online_training.models import Action

        return [Action.TriggerCondition.ON_PASS]

    def validate(self, action) -> None:
        super().validate(action)

        if has_new_user_filter(action.user_filter):
            raise ValidationError(
                {"user_filter": _("New users cannot be qualified on tools. They must be NEMO users first")}
            )

        if "tool_ids" not in action.configuration:
            raise ValidationError({"configuration": _("Configuration must include 'tool_ids' field")})

        tool_ids = action.configuration.get("tool_ids")
        if not isinstance(tool_ids, list) or not tool_ids:
            raise ValidationError({"configuration": _("'tool_ids' must be a non-empty list of integers")})

        if not all(isinstance(t_id, int) for t_id in tool_ids):
            raise ValidationError({"configuration": _("All items in 'tool_ids' must be integer IDs")})

        # Verify all requested tools exist in the database
        from NEMO.models import Tool

        existing_tool_ids = set(Tool.objects.filter(id__in=tool_ids).values_list("id", flat=True))
        missing_tool_ids = set(tool_ids) - existing_tool_ids
        if missing_tool_ids:
            missing_str = ", ".join(str(tid) for tid in missing_tool_ids)
            raise ValidationError(
                {"configuration": _(f"The following tool IDs do not exist in the system: {missing_str}")}
            )

        # Check if qualification levels are supported in this version of NEMO
        if "qualification_level_id" in action.configuration:
            try:
                from NEMO.models import QualificationLevel
            except ImportError:
                raise ValidationError(
                    {
                        "configuration": _(
                            "This version of NEMO does not support qualification levels. Please remove 'qualification_level_id' from your configuration."
                        )
                    }
                )

            qual_level_id = action.configuration["qualification_level_id"]
            if not QualificationLevel.objects.filter(id=qual_level_id).exists():
                raise ValidationError(
                    {"configuration": _(f"Qualification level ID {qual_level_id} does not exist in the system.")}
                )

    def do_perform(self, action, user_training) -> None:
        from NEMO.models import Tool
        from NEMO.views.qualifications import qualify

        # Only applies if they have an established NEMO user account
        nemo_user = user_training.training_user.nemo_user
        if not nemo_user:
            return

        tool_ids = action.configuration.get("tool_ids", [])
        qualification_level_id = action.configuration.get("qualification_level_id")

        tools = Tool.objects.filter(id__in=tool_ids)

        for tool in tools:
            kwargs = {"request_user": nemo_user, "tool": tool, "user": nemo_user}
            if qualification_level_id:
                kwargs["qualification_level_id"] = qualification_level_id
            qualify(**kwargs)


# Registry of all action handlers
action_handlers: Dict[str, OnlineTrainingActionHandler] = {
    ONLINE_TRAINING_ACTION_EXTEND_ACCESS: ExtendAccessOnlineTrainingHandler(),
    ONLINE_TRAINING_ACTION_REMOVE_TRAINING_REQUIRED: RemoveTrainingRequiredOnlineTrainingHandler(),
    ONLINE_TRAINING_ACTION_SEND_EMAIL: SendEmailOnlineTrainingHandler(),
    ONLINE_TRAINING_ACTION_QUALIFY_TOOL: QualifyUserOnToolOnlineTrainingHandler(),
    ONLINE_TRAINING_ACTION_GRANT_PHYSICAL_ACCESS: GrantPhysicalAccessLevelOnlineTrainingHandler(),
}
