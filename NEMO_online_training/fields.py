from typing import List, Tuple

from NEMO.fields import (
    CommaSeparatedListConverter,
    CommaSeparatedTextMultipleChoiceField,
    DynamicChoicesTextField,
    WrappedFilteredSelectMultiple,
)
from NEMO.models import UserType
from NEMO.utilities import safe_lazy_queryset_evaluation
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserTypeFilterField(DynamicChoicesTextField):
    """
    A field for filtering users by type, similar to NEMO's MultiRoleGroupPermissionChoiceField.

    Allows selection of:
    - "all_nemo_users" - All NEMO users regardless of type
    - "all_new_users" - All new users without NEMO accounts
    - User type IDs - Specific NEMO user types

    Storage format: Comma-separated string (e.g., ["all_nemo_users", "all_new_users", "1", "3", "n|1", "n|3"])
    """

    # Special filter values
    ALL_NEMO_USERS = "all_nemo_users"
    ALL_NEW_USERS = "all_new_users"

    # Display labels
    LABEL_ALL_NEMO = _("All NEMO users")
    LABEL_ALL_NEW = _("All New users")

    @classmethod
    def user_type_choices(cls) -> List[Tuple[str, str]]:
        """
        Generate the list of choices for the field.

        Returns:
            List of (value, label) tuples for the dropdown/checkboxes
        """
        choices = [
            (cls.ALL_NEMO_USERS, str(cls.LABEL_ALL_NEMO)),
            (cls.ALL_NEW_USERS, str(cls.LABEL_ALL_NEW)),
        ]

        user_types, error = safe_lazy_queryset_evaluation(UserType.objects.all().order_by("name"))
        for user_type in user_types:
            choices.append((str(user_type.id), user_type.name + " (NEMO user)"))
            choices.append(("n|" + str(user_type.id), user_type.name + " (New user)"))
        return choices

    def formfield(self, **kwargs):
        """
        Override to provide custom widget (WrappedFilteredSelectMultiple) for admin interface.
        """
        choices = kwargs.pop("choices", self.user_type_choices())
        is_stacked = kwargs.pop("is_stacked", False)
        kwargs["widget"] = WrappedFilteredSelectMultiple(_("User Types"), is_stacked=is_stacked)
        return super(models.TextField, self).formfield(
            choices=choices, form_class=CommaSeparatedTextMultipleChoiceField, **kwargs
        )

    def to_python(self, value) -> List:
        """Convert stored CSV string to Python list."""
        return CommaSeparatedListConverter.to_list(value)

    def from_db_value(self, value, *args, **kwargs) -> List:
        """Convert database value to Python list."""
        return self.to_python(value)

    def get_prep_value(self, value) -> str:
        """Convert Python list to CSV string for database storage."""
        return CommaSeparatedListConverter.to_string(value)

    def value_from_object(self, obj):
        """Get the value from the object and prepare it for forms."""
        value = super().value_from_object(obj)
        return self.get_prep_value(value)

    @classmethod
    def applies_to_user(cls, filter_values: List[str], training_user) -> bool:
        """
        Check if this filter applies to the given training user.

        Args:
            filter_values: List of filter values (e.g., ["all_nemo_users", "all_new_users", "1", "3", "n|1", "n|3"])
            training_user: TrainingUser instance to check

        Returns:
            True if the filter applies to this user, False otherwise
        """
        if not filter_values:
            # Empty filter = applies to nobody
            return False

        # Check if the user has NEMO account
        if training_user.nemo_user:
            # User has NEMO account
            # Check if "all_nemo" is in the filter
            if cls.ALL_NEMO_USERS in filter_values:
                return True

            # Check if the user's type ID is in the filter
            user_type_id = str(training_user.nemo_user.type_id)
            if user_type_id in filter_values:
                return True

            return False
        else:
            # User doesn't have NEMO account
            # Check if "all_new_users" is in the filter
            if cls.ALL_NEW_USERS in filter_values:
                return True

            # Check if the user's type ID is in the filter
            user_type_id = str(training_user.user_type_id)
            if f"n|{user_type_id}" in filter_values:
                return True

            return False

    @classmethod
    def user_types_display(cls, filter_values: List[str]) -> str:
        """
        Convert the list of selected filter values to a readable string for display.

        Args:
            filter_values: List of filter values

        Returns:
            Comma-separated string of labels
        """
        if not filter_values:
            return _("None")

        choices_dict = dict(cls.user_type_choices())
        labels = []

        for value in filter_values:
            label = choices_dict.get(value, value)
            labels.append(label)

        return ", ".join(labels)

    def get_choices(self, *args, **kwargs):
        """Override to ensure blank is not included."""
        kwargs["include_blank"] = False
        return super().get_choices(*args, **kwargs)
