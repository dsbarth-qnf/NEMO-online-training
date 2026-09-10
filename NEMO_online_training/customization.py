from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(key="online_training", title="Online training")
class OnlineTrainingCustomization(CustomizationBase):
    variables = {
        "online_training_feature_name": "Online trainings",
        "online_training_link_validity_minutes": "7200",  # 5 days
        "online_training_user_unique_email": "enabled",
        "online_training_user_type_required": "",
    }

    files = [
        ("online_training_send_new_link_email", ".html"),
    ]

    def __init__(self, key, title):
        super().__init__(key, title)
        self.title = self.get("online_training_feature_name", raise_exception=False, use_cache=False)
