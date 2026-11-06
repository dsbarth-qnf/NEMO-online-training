from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from NEMO_online_training.models import TrainingRecord, TrainingUser
from NEMO_online_training.utilities import validate_training_user


# Using non-underscore fields here since django Forms don't like variables starting with _
class TrainingUserForm(forms.ModelForm):
    first_name = forms.CharField(label="First name", required=True)
    last_name = forms.CharField(label="Last name", required=True)
    email = forms.EmailField(label="Email", required=True)
    user_type_id = forms.IntegerField(label="User type", required=False)

    class Meta:
        model = TrainingUser
        exclude = ["_first_name", "_last_name", "_email", "_user_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["first_name"].initial = self.instance._first_name
            self.fields["last_name"].initial = self.instance._last_name
            self.fields["email"].initial = self.instance._email
            self.fields["user_type_id"].initial = self.instance._user_type_id

    def clean(self):
        cleaned_data = super().clean()
        self.instance._first_name = cleaned_data.get("first_name", "").strip()
        self.instance._last_name = cleaned_data.get("last_name", "").strip()
        self.instance._email = cleaned_data.get("email", "").strip()
        self.instance._user_type_id = cleaned_data.get("user_type_id", None)
        validate_training_user(cleaned_data, self.instance.pk)
        return cleaned_data


class TrainingRecordDueDateForm(forms.ModelForm):
    class Meta:
        model = TrainingRecord
        fields = ["due_date"]

    def clean_due_date(self):
        due_date = self.cleaned_data.get("due_date")
        if due_date and due_date < timezone.now():
            raise ValidationError(_("Due date must be in the future."))
        return due_date
