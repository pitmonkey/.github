"""Exercise the reusable workflow at its action/CLI boundaries.

Run: uv run --with pyyaml python -m unittest discover -s tests -v
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def condition(expression, values):
    expression = expression.replace("||", "or").replace("&&", "and")
    expression = re.sub(r"[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+",
                        lambda match: repr(values.get(match[0], "")), expression)
    return bool(eval(expression, {"__builtins__": {}}, {}))


class AutomergeTest(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load((ROOT / ".github/workflows/dependabot-automerge.yml").read_text())["jobs"]["dev-tooling-automerge"]

    def execute(self, client_id="client-id", dependency="direct:development",
                ecosystem="uv", author="dependabot[bot]", token="app-token"):
        values = {
            "github.event.pull_request.user.login": author,
            "steps.meta.outputs.dependency-type": dependency,
            "steps.meta.outputs.package-ecosystem": ecosystem,
            "inputs.app-client-id": client_id,
            "steps.app-token.outputs.token": token,
            "secrets.GITHUB_TOKEN": "legacy-token",
            "github.event.pull_request.html_url": "https://github.com/example/repo/pull/1",
        }
        if not condition(self.job["if"], values):
            return [], []
        actions, results = [], []
        with tempfile.TemporaryDirectory() as directory:
            gh = Path(directory) / "gh"
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$GH_TOKEN" "$*"\n')
            gh.chmod(0o755)
            for step in self.job["steps"]:
                if not condition(step.get("if", "True"), values):
                    continue
                if "uses" in step:
                    actions.append(step)
                    continue
                env = {**os.environ, "PATH": directory + ":" + os.environ["PATH"]}
                for key, value in step.get("env", {}).items():
                    env[key] = re.sub(r"\$\{\{\s*(.*?)\s*\}\}",
                                      lambda match: str(values.get(match[1], "")), str(value))
                script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}",
                                lambda match: str(values.get(match[1], "")), step["run"])
                results.append(subprocess.run(["bash", "-e", "-c", script], env=env,
                                              text=True, capture_output=True))
        return actions, results

    def test_app_merge_uses_app_identity(self):
        actions, results = self.execute()
        self.assertTrue(any(a["uses"].startswith("actions/create-github-app-token@") for a in actions))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].returncode, 0, results[0].stderr)
        self.assertEqual(results[0].stdout.splitlines(), ["app-token", "pr merge --auto --squash https://github.com/example/repo/pull/1"])

    def test_legacy_caller_still_merges(self):
        actions, results = self.execute(client_id="")
        self.assertFalse(any(a["uses"].startswith("actions/create-github-app-token@") for a in actions))
        self.assertEqual(results[0].returncode, 0, results[0].stderr)
        self.assertEqual(results[0].stdout.splitlines()[0], "legacy-token")

    def test_empty_app_token_never_falls_back(self):
        _, results = self.execute(token="")
        self.assertNotEqual(results[0].returncode, 0)
        self.assertEqual(results[0].stdout, "")

    def test_only_eligible_updates_merge(self):
        for dependency, ecosystem, eligible in [
            ("direct:development", "uv", True),
            ("direct:production", "pre_commit", True),
            ("direct:production", "github_actions", True),
            ("direct:production", "uv", False),
            ("direct:production", "docker", False),
            ("", "", False),
        ]:
            with self.subTest(dependency=dependency, ecosystem=ecosystem):
                actions, results = self.execute(dependency=dependency, ecosystem=ecosystem)
                self.assertEqual(len(results), int(eligible))
                self.assertEqual(any(a["uses"].startswith("actions/create-github-app-token@") for a in actions), eligible)

    def test_non_dependabot_does_nothing(self):
        self.assertEqual(self.execute(author="someone"), ([], []))


if __name__ == "__main__":
    unittest.main()
