from NEMO.serializers import ModelSerializer
from NEMO.views.api import ModelViewSet, boolean_filters, datetime_filters, key_filters, number_filters, string_filters
from rest_flex_fields.serializers import FlexFieldsSerializerMixin

from NEMO_online_training.models import Training, Action, TrainingAttempt, TrainingRecord, TrainingUser


class TrainingSerializer(FlexFieldsSerializerMixin, ModelSerializer):
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
        "timestamp": datetime_filters,
        "score_percentage": number_filters,
        "responses": [],
        "passed": boolean_filters,
    }
