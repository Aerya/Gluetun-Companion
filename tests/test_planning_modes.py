from unittest import TestCase

from app.routes import _planning_modes


class PlanningModesTest(TestCase):
    def test_disabling_planning_also_disables_observation(self) -> None:
        self.assertEqual(
            _planning_modes(False, True, 0),
            (False, False),
        )

    def test_observation_stays_available_with_planning(self) -> None:
        self.assertEqual(
            _planning_modes(True, True, 0),
            (True, True),
        )

    def test_rotation_pool_can_keep_observation_available(self) -> None:
        self.assertEqual(
            _planning_modes(False, True, 1),
            (False, True),
        )
