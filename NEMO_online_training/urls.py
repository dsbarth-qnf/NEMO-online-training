from NEMO.urls import router, sort_urls
from django.urls import include, path

from NEMO_online_training import api
from NEMO_online_training.views import online_training

# Rest API URLs
router.register(r"online_training/actions", api.ActionViewSet)
router.register(r"online_training/trainings", api.TrainingViewSet)
router.register(r"online_training/training_records", api.TrainingRecordViewSet)
router.register(r"online_training/training_users", api.TrainingUserViewSet)
router.registry.sort(key=sort_urls)

urlpatterns = [
    path(
        "online_training/",
        include(
            [
                path("user_trainings/", online_training.user_online_trainings, name="online_user_trainings"),
                path(
                    "user_trainings/user/<int:training_user_id>/",
                    online_training.user_online_trainings,
                    name="online_user_trainings",
                ),
                path(
                    "user_trainings/search_users/",
                    online_training.search_training_users,
                    name="online_training_search_users",
                ),
                path(
                    "user_trainings/search_results/",
                    online_training.training_users_search_results,
                    name="online_training_search_users_results",
                ),
                path(
                    "users/create_from_nemo_user/<int:nemo_user_id>/",
                    online_training.create_training_user_from_nemo_user,
                    name="online_training_create_training_user_from_nemo_user",
                ),
                path(
                    "users/create_nemo_user/<int:training_user_id>/",
                    online_training.create_nemo_user_from_new_user,
                    name="online_training_create_nemo_user_from_new_user",
                ),
                path(
                    "users/create_user/",
                    online_training.create_training_user,
                    name="online_training_create_training_user",
                ),
                path(
                    "user_trainings/<int:user_training_id>/",
                    online_training.training,
                    name="online_training_user_training",
                ),
                path(
                    "trainings/<int:online_training_id>/",
                    online_training.training_without_assignment,
                    name="online_training_training",
                ),
                path(
                    "training_record/<int:record_id>/clear_for_retake/",
                    online_training.clear_for_retake,
                    name="online_training_clear_for_retake",
                ),
                path(
                    "user_trainings/<int:training_user_id>/<int:online_training_id>/add/",
                    online_training.add_training_to_user,
                    name="online_training_add_training_to_user",
                ),
                # Public URLs
                path(
                    "public/user_training/<str:signed_user_training_id>/",
                    online_training.public_user_training,
                    name="public_online_training_user_training",
                ),
                path(
                    "public/complete_user_training/",
                    online_training.public_complete_user_training,
                    name="public_online_training_complete_user_training",
                ),
                path(
                    "public/generate_user_training_email/<int:user_training_id>/",
                    online_training.public_generate_user_training_email,
                    name="public_online_training_generate_user_training_email",
                ),
                path(
                    "public/user_training/<str:signed_user_training_id>/media/<path:file_path>",
                    online_training.serve_training_media_file,
                    name="public_online_training_media",
                ),
            ]
        ),
    )
]
