import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / '.github' / 'scripts' / 'trivy_autofix.py'
SPEC = importlib.util.spec_from_file_location('trivy_autofix', SCRIPT_PATH)
trivy_autofix = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(trivy_autofix)


class TrivyAutofixTest(TestCase):
    def test_latest_docker_cli_tag_accepts_precise_patch_tags(self) -> None:
        with patch.object(
            trivy_autofix,
            '_hub_tags',
            side_effect=lambda image, major: {
                '30': [],
                '29': ['29-cli', '29.6-cli', '29.6.0-cli', '29.6.0-dind', '29.5.2-cli'],
            }.get(major, []),
        ):
            self.assertEqual(
                trivy_autofix.latest_docker_cli_tag('29-cli'),
                '29.6.0-cli',
            )

    def test_latest_docker_cli_tag_returns_none_when_current_is_latest(self) -> None:
        with patch.object(
            trivy_autofix,
            '_hub_tags',
            side_effect=lambda image, major: {
                '30': [],
                '29': ['29-cli', '29.6-cli', '29.6.0-cli'],
            }.get(major, []),
        ):
            self.assertIsNone(trivy_autofix.latest_docker_cli_tag('29.6.0-cli'))
