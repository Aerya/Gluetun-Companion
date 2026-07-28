from pathlib import Path
from unittest import TestCase


DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


class DockerfileSecurityPinsTest(TestCase):
    def test_compose_dependencies_are_pinned_to_fixed_versions(self) -> None:
        content = DOCKERFILE.read_text()

        self.assertIn(
            "github.com/containerd/containerd/v2@v2.2.5",
            content,
        )
        self.assertEqual(
            content.count("google.golang.org/grpc@v1.82.1"),
            2,
        )
