"""Exercise how build-docker.yml gates its builds on the wheel check.

Run: uv run --with pyyaml python -m unittest discover -s tests -v
"""
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-docker.yml"
BUILD_JOBS = ["build", "build-multiplatform", "build-native-matrix"]


def condition(expression, values):
    """Evaluate a GitHub `if:` built from ==, !=, !, &&, ||, startsWith() and cancelled()."""
    expression = expression.replace("||", " or ").replace("&&", " and ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    expression = expression.replace("startsWith(", "starts_with(").replace("cancelled()", "cancelled_()")
    expression = re.sub(r"(?<!['\w])[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+",
                        lambda match: repr(values.get(match[0], "")), expression)
    return bool(eval(expression, {"__builtins__": {}},
                     {"starts_with": lambda text, prefix: str(text).startswith(prefix),
                      "cancelled_": lambda: values.get("cancelled", False),
                      "true": True, "false": False}))


def context(event="pull_request", author="dependabot[bot]", head="dependabot/docker/python-3.15",
            wheel_check=True, platforms="", native=False, wheels="skipped"):
    return {
        "github.event_name": event,
        "github.event.pull_request.user.login": author if event == "pull_request" else "",
        "github.head_ref": head if event == "pull_request" else "",
        "inputs.wheel-check": wheel_check,
        "inputs.platforms": platforms,
        "inputs.native-arm64": native,
        "needs.wheels.result": wheels,
    }


def build_contexts(**kwargs):
    """One context per build job, with the platform inputs that select that job."""
    return {
        "build": context(platforms="", **kwargs),
        "build-multiplatform": context(platforms="linux/amd64,linux/arm64", native=False, **kwargs),
        "build-native-matrix": context(platforms="linux/amd64,linux/arm64", native=True, **kwargs),
    }


class WheelsJobTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.jobs = self.workflow["jobs"]

    def gate(self, **kwargs):
        return condition(self.jobs["wheels"]["if"], context(**kwargs))

    def test_wheel_check_input_default_true(self):
        wheel_check = self.workflow[True]["workflow_call"]["inputs"]["wheel-check"]
        self.assertEqual(wheel_check["type"], "boolean")
        self.assertIs(wheel_check["default"], True)

    def test_wheels_calls_check_wheels_with_build_inputs(self):
        wheels = self.jobs["wheels"]
        self.assertEqual(wheels["uses"], "pitmonkey/.github/.github/workflows/check-wheels.yml@main")
        self.assertEqual(wheels["with"]["dockerfile"], "${{ inputs.dockerfile }}")
        self.assertEqual(wheels["with"]["build-context"], "${{ inputs.build-context }}")

    def test_wheels_runs_on_dependabot_docker_pr(self):
        self.assertTrue(self.gate())

    def test_wheels_skipped_on_uv_dependabot_pr(self):
        self.assertFalse(self.gate(head="dependabot/uv/httpx-0.28.1"))

    def test_wheels_skipped_on_human_pr_and_push(self):
        self.assertFalse(self.gate(author="someone", head="feature/x"))
        self.assertFalse(self.gate(author="someone", head="dependabot/docker/python-3.15"))
        self.assertFalse(self.gate(event="push"))

    def test_wheels_skipped_when_opted_out(self):
        self.assertFalse(self.gate(wheel_check=False))


class BuildGateTest(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]

    def runs(self, job, **kwargs):
        return condition(self.jobs[job]["if"], build_contexts(**kwargs)[job])

    def test_build_jobs_need_wheels(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                needs = self.jobs[job]["needs"]
                self.assertIn("wheels", [needs] if isinstance(needs, str) else needs)

    def test_build_runs_when_wheels_skipped(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                self.assertTrue(self.runs(job, event="push", wheels="skipped"))
                self.assertTrue(self.runs(job, author="someone", head="feature/x", wheels="skipped"))

    def test_build_runs_when_wheels_passed(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                self.assertTrue(self.runs(job, wheels="success"))

    def test_build_blocked_when_wheels_failed(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                self.assertFalse(self.runs(job, wheels="failure"))

    def test_build_blocked_when_cancelled(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                ctx = build_contexts(event="push")[job]
                ctx["cancelled"] = True
                self.assertFalse(condition(self.jobs[job]["if"], ctx))

    def test_existing_dependabot_guard_unchanged(self):
        for job in BUILD_JOBS:
            with self.subTest(job=job):
                self.assertFalse(self.runs(job, head="dependabot/uv/httpx-0.28.1"))

    def test_merge_still_follows_native_matrix(self):
        self.assertEqual(self.jobs["merge"]["needs"], "build-native-matrix")


if __name__ == "__main__":
    unittest.main()
