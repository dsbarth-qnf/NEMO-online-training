from NEMO.serializers import ModelSerializer
from NEMO.views.api import ModelViewSet, boolean_filters, datetime_filters, key_filters, number_filters, string_filters
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_flex_fields.serializers import FlexFieldsSerializerMixin
from rest_framework.exceptions import ValidationError

from NEMO_online_training.models import Training, Action, TrainingAttempt, TrainingRecord, TrainingUser


class TrainingSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance or Training()
        # PATCH may omit either relation, so validate the resulting configuration.
        tools = attrs.get("blocking_tools")
        if tools is None:
            tools = instance.blocking_tools.all() if instance.pk else []
        areas = attrs.get("blocking_areas")
        if areas is None:
            areas = instance.blocking_areas.all() if instance.pk else []
        try:
            Training.validate_blocking_targets(
                attrs.get("is_blocking", instance.is_blocking),
                attrs.get("blocking_scope", instance.blocking_scope),
                tools,
                areas,
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict)
        return attrs

    class Meta:
        model = Training
        fields = "__all__"


class TrainingUserSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TrainingUser
        fields = "__all__"
        expandable_fields = {
            "nemo_user": "NEMO.serializers.UserSerializer",
        }


class TrainingRecordSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TrainingRecord
        fields = "__all__"
        expandable_fields = {
            "training": "NEMO_online_training.api.TrainingSerializer",
            "training_user": "NEMO_online_training.api.TrainingUserSerializer",
        }


class ActionSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Action
        fields = "__all__"
        expandable_fields = {
            "online_training": "NEMO_online_training.api.TrainingSerializer",
        }


class TrainingAttemptSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TrainingAttempt
        fields = "__all__"
        expandable_fields = {
            "training_record": "NEMO_online_training.api.TrainingRecordSerializer",
        }


class TrainingViewSet(ModelViewSet):
    filename = "online_trainings"
    queryset = Training.objects.all()
    serializer_class = TrainingSerializer
    filterset_fields = {
        "id": key_filters,
        "name": string_filters,
        "enabled": boolean_filters,
        "user_filter": string_filters,
        "completion_time_limit": number_filters,
        "default_due_date_days": number_filters,
        "allow_self_enrollment": boolean_filters,
        "is_blocking": boolean_filters,
        "blocking_scope": string_filters,
        "blocking_tools": key_filters,
        "blocking_areas": key_filters,
        "html_content": string_filters,
        "answer_key": [],
        "passing_score_percentage": number_filters,
        "max_attempts": number_filters,
        "retry_cooldown_minutes": number_filters,
        "creation_time": datetime_filters,
    }


class TrainingUserViewSet(ModelViewSet):
    filename = "training_users"
    queryset = TrainingUser.objects.all()
    serializer_class = TrainingUserSerializer
    filterset_fields = {
        "id": key_filters,
        "creation_time": datetime_filters,
        "last_updated": datetime_filters,
        "last_accessed": datetime_filters,
        "_first_name": string_filters,
        "_last_name": string_filters,
        "_email": string_filters,
        "nemo_user": key_filters,
    }


class TrainingRecordViewSet(ModelViewSet):
    filename = "training_records"
    queryset = TrainingRecord.objects.all()
    serializer_class = TrainingRecordSerializer
    filterset_fields = {
        "id": key_filters,
        "training": key_filters,
        "training_user": key_filters,
        "status": string_filters,
        "due_date": datetime_filters,
        "start": datetime_filters,
        "end": datetime_filters,
        "completion_data": [],
        "creation_time": datetime_filters,
        "last_updated": datetime_filters,
    }


class ActionViewSet(ModelViewSet):
    filename = "training_actions"
    queryset = Action.objects.all()
    serializer_class = ActionSerializer
    filterset_fields = {
        "id": key_filters,
        "training": key_filters,
        "action_type": string_filters,
        "trigger_condition": string_filters,
        "configuration": [],
        "user_filter": string_filters,
    }


class TrainingAttemptViewSet(ModelViewSet):
    filename = "training_attempts"
    queryset = TrainingAttempt.objects.all()
    serializer_class = TrainingAttemptSerializer
    filterset_fields = {
        "id": key_filters,
        "training_record": key_filters,
        "start": datetime_filters,
        "end": datetime_filters,
        "score_percentage": number_filters,
        "responses": [],
        "passed": boolean_filters,
    }
