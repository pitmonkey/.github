"""Exercise the uv re-lock workflow: its gate, its credential split, and its shell steps.

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
WORKFLOW = ROOT / ".github/workflows/dependabot-uv-relock.yml"


def condition(expression, values):
    """Evaluate a GitHub expression made of ==, &&, || and startsWith over `values`."""
    expression = expression.replace("||", " or ").replace("&&", " and ")
    expression = expression.replace("startsWith(", "starts_with(")
    expression = re.sub(r"(?<!['\w])[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+",
                        lambda match: repr(values.get(match[0], "")), expression)
    return bool(eval(expression, {"__builtins__": {}},
                     {"starts_with": lambda text, prefix: str(text).startswith(prefix)}))


def substitute(text, values):
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: str(values.get(match[1], "")), str(text))


def step_named(job, name):
    return next(step for step in job["steps"] if step.get("name") == name)


def run_step(step, cwd, values, extra_env=None, path_prefix=None):
    env = {**os.environ, **(extra_env or {})}
    for key, value in step.get("env", {}).items():
        env[key] = substitute(value, values)
    if path_prefix:
        env["PATH"] = path_prefix + ":" + env["PATH"]
    return subprocess.run(["bash", "-e", "-c", substitute(step["run"], values)],
                          cwd=cwd, env=env, text=True, capture_output=True)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_repo(directory, files):
    git(directory, "init", "-q")
    git(directory, "config", "user.email", "t@example.com")
    git(directory, "config", "user.name", "t")
    for path, text in files.items():
        target = Path(directory) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git(directory, "add", ".")
    git(directory, "commit", "-q", "-m", "init")


class GateTest(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]

    def gate(self, author="dependabot[bot]", head_repo="o/r", repo="o/r",
             ref="dependabot/uv/contracts/pydantic-2.14.3"):
        return condition(self.jobs["relock"]["if"], {
            "github.event.pull_request.user.login": author,
            "github.event.pull_request.head.repo.full_name": head_repo,
            "github.repository": repo,
            "github.event.pull_request.head.ref": ref,
        })

    def test_runs_for_a_dependabot_uv_pr(self):
        self.assertTrue(self.gate())

    def test_skips_a_human_pr(self):
        self.assertFalse(self.gate(author="someone"))

    def test_skips_a_fork_pr(self):
        self.assertFalse(self.gate(head_repo="attacker/r"))

    def test_skips_other_ecosystems(self):
        for ref in ["dependabot/pip/requests-2.0", "dependabot/github_actions/x", "feature/uv/x"]:
            with self.subTest(ref=ref):
                self.assertFalse(self.gate(ref=ref))

    def test_push_only_follows_a_change(self):
        self.assertEqual(self.jobs["push"]["needs"], "relock")
        self.assertTrue(condition(self.jobs["push"]["if"], {"needs.relock.outputs.changed": "true"}))
        self.assertFalse(condition(self.jobs["push"]["if"], {"needs.relock.outputs.changed": "false"}))


class CredentialSplitTest(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]

    def test_relock_holds_no_write_credential(self):
        relock = self.jobs["relock"]
        self.assertEqual(relock["permissions"], {"contents": "read"})
        checkout = next(s for s in relock["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        self.assertIs(checkout["with"]["persist-credentials"], False)
        self.assertFalse(any(s.get("uses", "").startswith("actions/create-github-app-token@")
                             for s in relock["steps"]))
        self.assertNotIn("app-private-key", yaml.safe_dump(relock))

    def test_push_never_runs_repo_code(self):
        push = self.jobs["push"]
        self.assertEqual(push["permissions"], {"contents": "read"})
        for step in push["steps"]:
            self.assertNotIn("astral-sh/setup-uv", step.get("uses", ""))
            self.assertNotRegex(step.get("run", ""), r"(?m)(^\s*|[;|&(]\s*)uv\s")

    def test_patch_is_verified_before_the_token_exists(self):
        names = [s.get("name", s.get("uses", "")) for s in self.jobs["push"]["steps"]]
        self.assertLess(names.index("Verify the patch only edits uv.lock files"),
                        names.index("Generate App token"))

    def test_pr_text_reaches_shell_only_through_env(self):
        for job in self.jobs.values():
            for step in job["steps"]:
                self.assertNotIn("${{", step.get("run", ""), step.get("name"))


class RelockStepTest(unittest.TestCase):
    """Run the re-lock step with a stub `uv` that records where it was called."""

    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["relock"]

    def relock(self, ignore=""):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as bin_dir:
            make_repo(repo, {"uv.lock": "a\n", "contracts/uv.lock": "b\n",
                             "workers/x/uv.lock": "c\n", "README.md": "r\n"})
            log = Path(bin_dir) / "calls"
            stub = Path(bin_dir) / "uv"
            stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$3" >> {log}\n')
            stub.chmod(0o755)
            result = run_step(step_named(self.job, "Re-lock every uv project"), repo,
                              {"inputs.paths-ignore-glob": ignore, "secrets.ops-ui-token": ""},
                              path_prefix=bin_dir)
            calls = log.read_text().split() if log.exists() else []
            return result, sorted(calls)

    def test_locks_every_project(self):
        result, calls = self.relock()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [".", "contracts", "workers/x"])

    def test_ignore_glob_skips_matching_directories(self):
        result, calls = self.relock(ignore="workers/*")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [".", "contracts"])

    def test_private_dependency_rewrite_is_guarded_on_an_empty_token(self):
        env = step_named(self.job, "Re-lock every uv project")["env"]
        self.assertEqual(env["GIT_CONFIG_COUNT"], "${{ secrets.ops-ui-token != '' && 1 || 0 }}")


class VerifyPatchTest(unittest.TestCase):
    """Run the patch filter against real `git diff` output."""

    def setUp(self):
        self.step = step_named(yaml.safe_load(WORKFLOW.read_text())["jobs"]["push"],
                               "Verify the patch only edits uv.lock files")

    def verify(self, change):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            make_repo(repo, {"uv.lock": "a\n", "svc/uv.lock": "b\n", "pyproject.toml": "p\n"})
            change(Path(repo))
            patch = Path(out) / "uv-relock" / "relock.patch"
            patch.parent.mkdir()
            git(repo, "add", "-N", ".")
            patch.write_text(subprocess.run(["git", "diff", "--binary"], cwd=repo, text=True,
                                            capture_output=True, check=True).stdout)
            git(repo, "reset", "-q", "--hard")
            git(repo, "clean", "-qfd")
            return run_step(self.step, repo, {"runner.temp": out})

    def test_accepts_lock_only_changes(self):
        def change(repo):
            (repo / "uv.lock").write_text("a2\n")
            (repo / "svc/uv.lock").write_text("b2\n")
        result = self.verify(change)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_a_change_outside_uv_lock(self):
        def change(repo):
            (repo / "uv.lock").write_text("a2\n")
            (repo / "pyproject.toml").write_text("evil\n")
        result = self.verify(change)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pyproject.toml", result.stdout)

    def test_rejects_a_new_file(self):
        def change(repo):
            (repo / "new").mkdir()
            (repo / "new/uv.lock").write_text("x\n")
        self.assertNotEqual(self.verify(change).returncode, 0)

    def test_rejects_a_mode_change(self):
        def change(repo):
            (repo / "uv.lock").chmod(0o755)
        self.assertNotEqual(self.verify(change).returncode, 0)


if __name__ == "__main__":
    unittest.main()
