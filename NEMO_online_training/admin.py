from NEMO.actions import has_perm
from NEMO.typing import QuerySetType
from NEMO.utilities import new_model_copy
from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.safestring import mark_safe

from NEMO_online_training.models import Action, Training, TrainingAttempt, TrainingRecord, TrainingUser
from NEMO_online_training.training_actions import action_handlers
from NEMO_online_training.utilities import validate_training_user


@admin.action(description="Duplicate selected training")
def duplicate_online_training(model_admin, request, queryset: QuerySetType[Training]):
    if not has_perm(request, queryset, "add") or not has_perm(request, queryset, "change"):
        model_admin.message_user(request, "You do not have permission to run this action.", level=messages.ERROR)
    for online_training in queryset:
        original_name = online_training.name
        new_name = "Copy of " + online_training.name
        try:
            if Training.objects.filter(name=new_name).exists():
                messages.error(
                    request,
                    mark_safe(
                        f'There is already a copy of {original_name} as <a href="{reverse("admin:NEMO_online_training_training_change", args=[online_training.id])}">{new_name}</a>. Change the copy\'s name and try again'
                    ),
                )
                continue
            else:
                old_actions = online_training.action_set.all()
                new_training = new_model_copy(online_training)
                new_training.name = new_name
                new_training.save()
                for action in old_actions:
                    new_action = new_model_copy(action)
                    new_action.training = new_training
                    new_action.save()
                messages.success(
                    request,
                    mark_safe(
                        f'A duplicate of {original_name} has been made as <a href="{reverse("admin:NEMO_online_training_training_change", args=[new_training.id])}">{new_training.name}</a>'
                    ),
                )
        except Exception as error:
            messages.error(
                request, f"{original_name} could not be duplicated because of the following error: {str(error)}"
            )


class TrainingUserAdminForm(forms.ModelForm):
    class Meta:
        model = TrainingUser
        fields = "__all__"
        widgets = {
            "notes": forms.Textarea(),
        }

    def clean(self):
        cleaned_data = super().clean()
        validate_training_user(cleaned_data, self.instance.pk, admin_form=True)
        return cleaned_data


@admin.register(TrainingUser)
class TrainingUserAdmin(admin.ModelAdmin):
    list_display = [
        "first_name",
        "last_name",
        "email",
        "user_type",
        "get_all_blocking_trainings_completed",
        "get_all_trainings_completed",
        "last_accessed",
        "creation_time",
        "id",
    ]
    date_hierarchy = "creation_time"
    autocomplete_fields = ["nemo_user"]
    readonly_fields = ["creation_time", "last_updated", "last_accessed"]
    form = TrainingUserAdminForm

    @admin.display(boolean=True, description="All Trainings Completed")
    def get_all_trainings_completed(self, obj: TrainingUser) -> bool:
        return obj.all_trainings_completed()

    @admin.display(boolean=True, description="All Blocking Trainings Completed")
    def get_all_blocking_trainings_completed(self, obj: TrainingUser) -> bool:
        return obj.all_blocking_trainings_completed()


class OnlineTrainingActionInlineForm(forms.ModelForm):
    action_type = forms.ChoiceField(choices=[])  # Start empty

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action_type"].choices = [(action.name, action.description) for action in action_handlers.values()]

    class Meta:
        model = Action
        fields = "__all__"


class OnlineTrainingActionInline(admin.TabularInline):
    model = Action
    extra = 0
    verbose_name = "After training is completed"
    verbose_name_plural = "After training is completed"
    form = OnlineTrainingActionInlineForm


@admin.register(Training)
class OnlineTrainingAdmin(admin.ModelAdmin):
    inlines = [OnlineTrainingActionInline]
    list_display = [
        "name",
        "enabled",
        "is_blocking",
        "completion_time_limit",
        "passing_score_percentage",
        "max_attempts",
        "creation_time",
        "id",
    ]
    date_hierarchy = "creation_time"
    list_filter = ["enabled", "is_blocking"]
    actions = [duplicate_online_training]


class TrainingAttemptInline(admin.TabularInline):
    model = TrainingAttempt
    extra = 0
    readonly_fields = ["timestamp", "score_percentage", "passed", "responses"]
    can_delete = False

    # Make the entire inline un-editable so history cannot be altered
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TrainingRecord)
class TrainingRecordAdmin(admin.ModelAdmin):
    list_display = [
        "training_user",
        "training",
        "get_status",
        "due_date",
        "completion_time",
        "start",
        "end",
        "creation_time",
        "last_updated",
        "id",
    ]
    list_filter = ["training", "status"]
    date_hierarchy = "creation_time"
    readonly_fields = ["creation_time", "last_updated"]
    inlines = [TrainingAttemptInline]
    search_fields = [
        "training_user___first_name",
        "training_user___last_name",
        "training_user___email",
        "training_user__nemo_user__first_name",
        "training_user__nemo_user__last_name",
        "training_user__nemo_user__email",
    ]

    @admin.display(description="Status")
    def get_status(self, obj: TrainingRecord) -> str:
        if obj.has_training_expired():
            return "Expired"
        return obj.get_status_display()


@admin.register(TrainingAttempt)
class TrainingAttemptAdmin(admin.ModelAdmin):
    list_display = ["training_record", "score_percentage", "passed", "timestamp"]
    list_filter = ["passed", "timestamp", "training_record__training"]
    readonly_fields = ["timestamp", "score_percentage", "passed", "responses", "training_record"]
    search_fields = [
        "training_record__training_user___first_name",
        "training_record__training_user___last_name",
    ]

    # Prevent direct creation/editing of attempts
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
