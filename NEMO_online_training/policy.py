from typing import List, Optional, Tuple, Union

from NEMO.exceptions import NEMOException, ProjectChargeException, UserAccessError
from NEMO.models import (
    Area,
    AreaAccessRecord,
    Consumable,
    ConsumableWithdraw,
    Project,
    Reservation,
    StaffCharge,
    Tool,
    UsageEvent,
    User,
)
from NEMO.policy import BaseNEMOPolicy
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.html import format_html, format_html_join

from NEMO_online_training.models import TrainingRecord, TrainingUser


class BlockingTrainingDueException(NEMOException):
    pass


class ProjectBlockingTrainingDueException(ProjectChargeException):
    pass


class AccessBlockingTrainingDueException(UserAccessError):
    pass


class NEMOOnlineTrainingPolicy(BaseNEMOPolicy):

    def check_to_save_reservation(
        self,
        cancelled_reservation: Optional[Reservation],
        new_reservation: Reservation,
        user_creating_reservation: User,
        explicit_policy_override: bool,
    ) -> Tuple[List[str], bool]:
        policy_problems = []

        if new_reservation.user.is_staff_on_tool(new_reservation.tool) or explicit_policy_override:
            return policy_problems, False

        trainings = blocking_trainings_for_user(new_reservation.user, new_reservation.reservation_item)
        if trainings.exists():
            msg = get_blocking_training_error_message(trainings)
            policy_problems.append(msg)
            return policy_problems, True

        return policy_problems, True

    def check_to_enable_tool(
        self, tool: Tool, operator: User, user: User, project: Project, staff_charge: bool, remote_work=False
    ) -> HttpResponse:
        if not operator.is_staff_on_tool(tool):
            trainings = blocking_trainings_for_user(user, tool)
            if trainings.exists():
                msg = get_blocking_training_error_message(trainings)
                return HttpResponseBadRequest(msg)
        return HttpResponse()

    def check_to_enter_any_area(self, user: User):
        self._check_area_trainings(user)

    def check_to_enter_area(self, area: Area, user: User):
        self._check_area_trainings(user, area)

    def _check_area_trainings(self, user: User, area: Area = None):
        trainings = blocking_trainings_for_user(user, area)
        if trainings.exists():
            msg = get_blocking_training_error_message(trainings, html=False)
            raise AccessBlockingTrainingDueException(user=user, msg=msg)

    def check_billing_to_project(
        self,
        project: Project,
        user: User,
        item: Union[Tool, Area, Consumable, StaffCharge] = None,
        charge: Union[UsageEvent, AreaAccessRecord, ConsumableWithdraw, StaffCharge, Reservation] = None,
    ):
        if not isinstance(charge, (Reservation, UsageEvent, AreaAccessRecord)):
            trainings = blocking_trainings_for_user(user, item if isinstance(item, (Tool, Area)) else None)
            if trainings.exists():
                msg = get_blocking_training_error_message(trainings)
                raise ProjectBlockingTrainingDueException(project=project, user=user, msg=msg)


def blocking_trainings_for_user(user: User, item: Tool | Area | None = None) -> QuerySet[TrainingRecord]:
    training_user = TrainingUser.objects.filter(nemo_user=user).first()
    return training_user.blocking_trainings_due_for(item) if training_user else TrainingRecord.objects.none()


def get_blocking_training_error_message(user_trainings_due: QuerySet[TrainingRecord], html=True) -> str:
    training_names = user_trainings_due.order_by("training__name").values_list("training__name", flat=True).distinct()
    if html:
        training_list = format_html_join(
            "", "<li style='margin-left: 40px'>{}</li>", ((name,) for name in training_names)
        )
        return format_html(
            "<ul style='padding-left:0'>The following trainings must be completed successfully before proceeding: {}</ul>",
            training_list,
        )
    else:
        return f"The following trainings must be completed successfully before proceeding: {', '.join(training_names)}"
