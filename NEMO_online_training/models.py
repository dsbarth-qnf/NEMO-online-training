from datetime import timedelta

from NEMO.constants import CHAR_FIELD_MEDIUM_LENGTH, CHAR_FIELD_SMALL_LENGTH
from NEMO.models import BaseModel, Notification, SerializationByNameModel, User, UserType
from NEMO.utilities import format_datetime, format_timedelta, get_full_url, render_email_template, send_mail
from NEMO.views.customization import get_media_file_contents
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.signing import TimestampSigner
from django.db import models, transaction
from django.db.models import BooleanField, Case, Count, F, Q, When
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from NEMO_online_training.fields import UserTypeFilterField
from NEMO_online_training.utilities import ONLINE_TRAINING_EMAIL_CATEGORY, ONLINE_TRAINING_NOTIFICATION_TYPE


class TrainingUser(BaseModel):
    creation_time = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    last_accessed = models.DateTimeField(null=True, blank=True)
    _first_name = models.CharField(
        verbose_name="First name", db_column="first_name", null=True, blank=True, max_length=CHAR_FIELD_SMALL_LENGTH
    )
    _last_name = models.CharField(
        verbose_name="Last name", db_column="last_name", null=True, blank=True, max_length=CHAR_FIELD_SMALL_LENGTH
    )
    _email = models.EmailField(verbose_name="Email address", db_column="email", null=True, blank=True)
    _user_type = models.ForeignKey(UserType, verbose_name="User type", null=True, blank=True, on_delete=models.SET_NULL)
    nemo_user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)

    class Meta:
        ordering = ["_first_name", "_last_name", "nemo_user__first_name", "nemo_user__last_name"]

    @property
    def first_name(self) -> str:
        return self._first_name or (self.nemo_user.first_name if self.nemo_user_id else "")

    @first_name.setter
    def first_name(self, value: str):
        self._first_name = value

    @property
    def last_name(self) -> str:
        return self._last_name or (self.nemo_user.last_name if self.nemo_user_id else "")

    @last_name.setter
    def last_name(self, value: str):
        self._last_name = value

    @property
    def email(self) -> str:
        return self._email or (self.nemo_user.email if self.nemo_user_id else "")

    @email.setter
    def email(self, value: str):
        self._email = value

    @property
    def user_type(self) -> UserType | None:
        return self._user_type or (self.nemo_user.type if self.nemo_user_id else None)

    @user_type.setter
    def user_type(self, value: UserType):
        self._user_type = value

    @property
    def user_type_id(self) -> int | None:
        return (
            self._user_type_id
            if self._user_type_id is not None
            else (self.nemo_user.type_id if self.nemo_user_id else None)
        )

    @user_type_id.setter
    def user_type_id(self, value: int):
        self._user_type_id = value

    def all_trainings_completed(self):
        return not self.trainingrecord_set.filter(end__isnull=True).exists()

    def all_blocking_trainings_completed(self):
        """
        Blocking trainings are those that are marked as blocking and have a due date in the past.
        """
        now = timezone.now()
        return not self.trainingrecord_set.filter(
            training__is_blocking=True, due_date__lt=now, end__isnull=True
        ).exists()

    def all_blocking_trainings_due(self):
        return self.trainingrecord_set.filter(training__is_blocking=True, due_date__lt=timezone.now(), end__isnull=True)

    def get_name(self):
        return self.first_name + " " + self.last_name

    def all_incomplete_training_ids(self):
        return list(self.trainingrecord_set.filter(end__isnull=True).values_list("id", flat=True))

    @staticmethod
    def objects_with_trainings():
        return (
            TrainingUser.objects.annotate(
                # Count all trainings linked to this user
                total_trainings=Count("trainingrecord"),
                # Count only the trainings that have a completed date
                completed_trainings=Count("trainingrecord", filter=Q(trainingrecord__end__isnull=False)),
            )
            .annotate(
                # Compare the two counts to create the boolean
                # Logic: total == completed AND total > 0
                all_trainings_completed=Case(
                    When(Q(total_trainings=F("completed_trainings")) & Q(total_trainings__gt=0), then=True),
                    default=False,
                    output_field=BooleanField(),
                )
            )
            .prefetch_related("trainingrecord_set")
        )

    @staticmethod
    def create_from_nemo_user(nemo_user: User):
        training_user, created = TrainingUser.objects.get_or_create(nemo_user=nemo_user)
        if created:
            # force save to set the fields
            training_user.save()
        return training_user

    def save(self, *args, **kwargs):
        if self.nemo_user:
            self._first_name = None
            self._last_name = None
            self._email = None
            self._user_type = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Training(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True)
    enabled = models.BooleanField(
        default=True, help_text=_("If unchecked, this training will not be available to users")
    )
    user_filter = UserTypeFilterField(
        help_text=_(
            "Select which users this training should be available to. You can select 'All NEMO users', "
            "'All new users' (without NEMO accounts), and/or specific user types."
        ),
        default=f"{UserTypeFilterField.ALL_NEMO_USERS},{UserTypeFilterField.ALL_NEW_USERS}",
    )
    completion_time_limit = models.PositiveIntegerField(
        default=120, help_text=_("The maximum time the user can take to complete the training on the page (in minutes)")
    )
    default_due_date_days = models.PositiveIntegerField(
        help_text=_("The default number of days before this training is due")
    )
    allow_self_enrollment = models.BooleanField(
        default=False, help_text=_("Allow users to take this training without prior assignment.")
    )
    is_blocking = models.BooleanField(
        default=False,
        help_text=_(
            "If checked, prevents the linked NEMO user from performing other actions until this training is completed"
        ),
    )
    html_content = models.TextField(
        null=True,
        blank=True,
        help_text=mark_safe(
            _(
                "<p>The HTML content of the training. The following context variables are available:</p>"
                "<ul style='padding-left: 35px;'>"
                "<li style='list-style: initial'><b>training_user</b>: the user who is completing the training</li>"
                "<li style='list-style: initial'><b>training</b>: the training being completed</li>"
                "<li style='list-style: initial'><b>record</b>: the completion record</li>"
                "<li style='list-style: initial'><b>completion_token</b>: the completion token</li>"
                "</ul>"
                "<p>Media files can be used with <code>{% url 'public_online_training_media' completion_token 'media_file_path' %}</code></p>"
                "<p>Upon completion, call the JS function: <code>complete_training(button, data, event)</code> to complete the training</p>"
                "<p>The legacy JS function will also still work: <code>training_completed(dict_data)</code></p>"
                "<p>To display user responses in the View Responses popup: Ensure that the keys in your <code>dataToSave</code> JSON object exactly match the id or name attributes of the input elements in your HTML</p>"
            )
        ),
    )
    creation_time = models.DateTimeField(auto_now_add=True)
    answer_key = models.JSONField(
        blank=True,
        null=True,
        help_text=mark_safe(
            (
                "<p>JSON mapping of inputs to correct answers. Leave blank to only require completion.</p>"
                "<p>Entries starting with "
                "_"
                " are ignored during grading. This can be used to pass an email address or list to send quiz results</p>"
            )
        ),
    )
    passing_score_percentage = models.IntegerField(
        blank=True, null=True, help_text=_("Required score to pass (e.g. 80). Leave blank if no quiz is required.")
    )
    max_attempts = models.IntegerField(
        blank=True,
        null=True,
        default=0,
        help_text=_("Maximum allowed attempts. Set to 0 or leave blank for unlimited."),
    )
    retry_cooldown_minutes = models.IntegerField(
        blank=True, null=True, default=0, help_text=_("Wait time in minutes between failed attempts.")
    )

    class Meta:
        ordering = ["name"]

    def applies_to_user(self, training_user: TrainingUser) -> bool:
        return UserTypeFilterField.applies_to_user(self.user_filter, training_user)

    def default_due_date_from_now(self):
        return timezone.now() + timedelta(days=self.default_due_date_days)

    def __str__(self):
        return self.name


class Action(BaseModel):
    class TriggerCondition(models.TextChoices):
        ON_PASS = "on_pass", _("On Pass")
        ON_FAIL = "on_fail", _("On Failure")
        ALWAYS = "always", _("Always")

    training = models.ForeignKey(Training, on_delete=models.CASCADE)
    action_type = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    trigger_condition = models.CharField(
        max_length=10,
        choices=TriggerCondition.choices,
        default=TriggerCondition.ON_PASS,
        help_text=_("Select when this action should execute."),
    )
    training = models.ForeignKey(Training, on_delete=models.CASCADE)
    action_type = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    configuration = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Enter configuration as JSON. See <a href='https://github.com/usnistgov/NEMO-online-training?tab=readme-ov-file#usage' target='_blank'>this link</a> for more information."
        ),
    )
    user_filter = UserTypeFilterField(
        help_text=_(
            "Select which users this action applies to. You can select 'All NEMO users', "
            "'All new users' (without NEMO accounts), and/or specific user types."
        ),
        default=f"{UserTypeFilterField.ALL_NEMO_USERS},{UserTypeFilterField.ALL_NEW_USERS}",
    )

    class Meta:
        ordering = ["action_type"]

    def clean(self):
        from NEMO_online_training.training_actions import action_handlers

        if self.action_type not in action_handlers:
            raise ValidationError(_(f"Invalid action type: {self.action_type}"))

        handler = action_handlers[self.action_type]
        handler.validate(self.configuration, self.user_filter)

    def applies_to_user(self, training_user) -> bool:
        return UserTypeFilterField.applies_to_user(self.user_filter, training_user)

    def applies_to_record(self, training_record) -> bool:
        """Checks if the action applies to user type and the record's failed status."""
        if not self.applies_to_user(training_record.training_user):
            return False

        if self.trigger_condition == self.TriggerCondition.ON_PASS and training_record.failed:
            return False
        if self.trigger_condition == self.TriggerCondition.ON_FAIL and not training_record.failed:
            return False

        return True

    def __str__(self):
        return f"{self.action_type} for {self.training.name}"


class TrainingRecord(BaseModel):
    training = models.ForeignKey(Training, on_delete=models.CASCADE)
    training_user = models.ForeignKey(TrainingUser, on_delete=models.CASCADE)
    due_date = models.DateTimeField(null=True, blank=True, help_text=_("The due date/time for the training"))
    start = models.DateTimeField(null=True, blank=True, help_text=_("The date/time the training was started"))
    end = models.DateTimeField(null=True, blank=True, help_text=_("The date/time the training was completed"))
    completion_data = models.JSONField(
        null=True, blank=True, help_text=_("Completion data to be stored for the training, like answers to questions")
    )
    creation_time = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    failed = models.BooleanField(
        default=False, help_text=_("Indicates if the user has exhausted all attempts and failed.")
    )
    cleared_for_retake = models.BooleanField(
        default=False, help_text="If True, the user is permitted to attempt this training again after failing."
    )

    class Meta:
        ordering = ["-end", "-due_date"]

    def has_training_expired(self) -> bool:
        return bool(self.due_date and self.due_date < timezone.now())

    def generate_link(self) -> str:
        return get_full_url(
            reverse("public_online_training_user_training", args=[TimestampSigner().sign(str(self.id))])
        )

    def generate_and_send_new_email(self):
        new_link_template = get_media_file_contents("online_training_send_new_link_email.html")
        if not new_link_template:
            new_link_template = "Dear {{ training_user.first_name }},<br><br>Please click on the following unique link to complete your assigned training: <br><a href='{{ record.generate_link }}'>complete training</a>."
        message = render_email_template(
            new_link_template,
            {"training_user": self.training_user, "training": self.training, "record": self},
        )
        send_mail(
            subject=f"Link to complete {self.training.name}",
            content=message,
            from_email=None,
            to=[self.training_user.email],
            email_category=ONLINE_TRAINING_EMAIL_CATEGORY,
        )

    def completed(self):
        return self.end is not None

    def completion_time(self) -> timedelta | str | None:
        if self.start and self.end:
            return format_timedelta(self.end - self.start, "{H:02}h {M:02}m {S:02}s")
        elif self.start:
            return "ongoing"
        return None

    def complete(self, data: dict = None):
        from NEMO_online_training.training_actions import action_handlers

        self.end = timezone.now()
        self.completion_data = data
        self.save()
        for action in self.training.action_set.all():
            handler = action_handlers[action.action_type]
            handler.perform(action, self)

    def clean(self):
        if self.training_user and self.training:
            # Check for duplicate incomplete trainings
            if (
                TrainingRecord.objects.filter(
                    training_user=self.training_user,
                    training=self.training,
                    end__isnull=True,
                    due_date__gte=timezone.now(),
                    failed=False,
                )
                .exclude(id=self.id)
                .exists()
            ):
                raise ValidationError(
                    {
                        NON_FIELD_ERRORS: _(
                            "This user already has an incomplete training of this type. Please complete or remove it first."
                        )
                    }
                )
            if not self.pk:
                if not UserTypeFilterField.applies_to_user(self.training.user_filter, self.training_user):
                    user_type = f"{'New user' if not self.training_user.nemo_user_id else 'NEMO user'}{' and ' + self.training_user.user_type.name if self.training_user.user_type else ''}"
                    raise ValidationError(
                        {
                            NON_FIELD_ERRORS: _(
                                f"This training is restricted to the following user types: {UserTypeFilterField.user_types_display(self.training.user_filter)}. {self.training_user} is a {user_type}"
                            )
                        }
                    )

    def __str__(self):
        due_date = f", due {format_datetime(self.due_date, 'SHORT_DATETIME_FORMAT')}" if self.due_date else ""
        return f"{self.training.name} - {self.training_user.get_name()}{due_date}"


class TrainingAttempt(models.Model):
    training_record = models.ForeignKey("TrainingRecord", on_delete=models.CASCADE, related_name="attempts")
    timestamp = models.DateTimeField(auto_now_add=True)
    score_percentage = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(default=False)
    responses = models.JSONField(null=True, blank=True, help_text=_("The exact payload submitted by the user."))


def notification_qs_for_training(training: TrainingRecord):
    ct = ContentType.objects.get_for_model(TrainingRecord)
    return Notification.objects.filter(
        notification_type=ONLINE_TRAINING_NOTIFICATION_TYPE, content_type=ct, object_id=training.pk
    )


@receiver(post_save, sender=TrainingRecord)
def online_training_user_training_notification_on_save(sender, instance: TrainingRecord, created: bool, **kwargs):
    # always remove any previous notifications
    def _delete():
        notification_qs_for_training(instance).delete()

    transaction.on_commit(_delete)

    if instance.training_user.nemo_user and not instance.end:
        # Create/Recreate a notification when the training is created or updated (except when it's completed).
        def _update():
            Notification.objects.get_or_create(
                user=instance.training_user.nemo_user,
                notification_type=ONLINE_TRAINING_NOTIFICATION_TYPE,
                content_type=ContentType.objects.get_for_model(TrainingRecord),
                object_id=instance.id,
                defaults={"expiration": (instance.due_date or timezone.now()) + timedelta(days=30)},
            )

        transaction.on_commit(_update)
        return


@receiver(pre_delete, sender=TrainingRecord)
def online_training_user_training_notification_on_delete(sender, instance: TrainingRecord, **kwargs):
    def _delete():
        notification_qs_for_training(instance).delete()

    transaction.on_commit(_delete)


@receiver(post_save, sender=User)
def finalize_training_user_to_nemo_user_conversion(sender, instance, created, **kwargs):
    # Look for the temporary attribute we set in the view
    corr_id = getattr(instance, "_correlation_id", None)

    if created and corr_id:
        # Link the TrainingUser to this new actual User
        training_user = TrainingUser.objects.filter(id=corr_id).first()
        if training_user:
            training_user.nemo_user = instance
            training_user.save()
