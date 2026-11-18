"""Exercise the wheel check workflow: version detection, skips, and the per-platform compile.

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
WORKFLOW = ROOT / ".github/workflows/check-wheels.yml"
DEFAULT_PLATFORMS = "x86_64-manylinux_2_28,aarch64-manylinux_2_28"


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


def write(directory, files):
    for path, text in files.items():
        target = Path(directory) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def read_outputs(path):
    return dict(line.split("=", 1) for line in Path(path).read_text().splitlines() if "=" in line)


class DetectTest(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["check"]
        self.step = step_named(self.job, "Detect Python version")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def detect(self, dockerfile, lock_dir=".", context=".", name="Dockerfile"):
        files = {name: dockerfile}
        if lock_dir is not None:
            files[f"{lock_dir}/uv.lock"] = "version = 1\n"
        write(self.dir, files)
        out = self.dir / "out.txt"
        out.write_text("")
        result = run_step(self.step, self.dir,
                          {"inputs.dockerfile": name, "inputs.build-context": context},
                          extra_env={"GITHUB_OUTPUT": str(out)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return read_outputs(out), result.stdout

    def test_version_from_last_python_from(self):
        outputs, _ = self.detect("FROM python:3.14-slim AS deps\nRUN true\nFROM python:3.15-slim\n")
        self.assertEqual(outputs["version"], "3.15")
        self.assertEqual(outputs["skip"], "false")

    def test_version_with_platform_flag_and_digest(self):
        outputs, _ = self.detect(
            "FROM --platform=$BUILDPLATFORM python:3.15.1-slim-trixie@sha256:abc AS b\n")
        self.assertEqual(outputs["version"], "3.15")

    def test_bare_tag(self):
        outputs, _ = self.detect("FROM python:3.15\n")
        self.assertEqual(outputs["version"], "3.15")

    def test_python_build_stage_nginx_runtime(self):
        outputs, _ = self.detect(
            "FROM python:3.12-slim AS build\nFROM nginxinc/nginx-unprivileged:stable-alpine\n")
        self.assertEqual(outputs["version"], "3.12")
        self.assertEqual(outputs["skip"], "false")

    def test_skip_non_python(self):
        outputs, stdout = self.detect("FROM node:22\n")
        self.assertEqual(outputs["skip"], "true")
        self.assertIn("no python base image", stdout)

    def test_skip_templated_tag(self):
        outputs, _ = self.detect("ARG PY=3.15\nFROM python:${PY}-slim\n")
        self.assertEqual(outputs["skip"], "true")

    def test_skip_no_lock(self):
        outputs, stdout = self.detect("FROM python:3.15-slim\n", lock_dir=None)
        self.assertEqual(outputs["skip"], "true")
        self.assertIn("no uv.lock", stdout)

    def test_lock_in_subdir_context(self):
        outputs, _ = self.detect("FROM python:3.15-slim\n", lock_dir="hub", context="hub",
                                 name="hub/Dockerfile")
        self.assertEqual(outputs["skip"], "false")

    def test_lock_outside_context_skips(self):
        outputs, _ = self.detect("FROM python:3.15-slim\n", lock_dir=".", context="hub",
                                 name="hub/Dockerfile")
        self.assertEqual(outputs["skip"], "true")


STUB_UV = """#!/bin/bash
log="$STUB_LOG"
if [ "$1" = export ]; then
  printf 'httpx==0.28.1\\nops-ui @ git+https://github.com/pitmonkey/ops-ui@abc\\n-e ./contracts\\n'
  exit 0
fi
if [ "$1" = pip ] && [ "$2" = compile ]; then
  echo "ARGS $*" >> "$log"
  echo "STDIN $(cat | tr '\\n' ' ')" >> "$log"
  if [ -n "$STUB_FAIL_PLATFORM" ] && [[ " $* " == *" $STUB_FAIL_PLATFORM "* ]]; then
    echo "error: Failed to build httptools==0.8.0" >&2
    exit 1
  fi
  exit 0
fi
exit 2
"""


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["check"]
        self.step = step_named(self.job, "Check wheels")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "uv").write_text(STUB_UV)
        (bin_dir / "uv").chmod(0o755)
        self.bin = str(bin_dir)
        self.log = self.dir / "log.txt"
        self.summary = self.dir / "summary.md"
        self.log.write_text("")
        self.summary.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, fail_platform=""):
        values = {"inputs.build-context": ".", "inputs.platforms": DEFAULT_PLATFORMS,
                  "steps.detect.outputs.version": "3.15"}
        return run_step(self.step, self.dir, values, path_prefix=self.bin,
                        extra_env={"STUB_LOG": str(self.log), "STUB_FAIL_PLATFORM": fail_platform,
                                   "GITHUB_STEP_SUMMARY": str(self.summary)})

    def test_check_drops_git_and_editable_lines(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        stdins = [l for l in self.log.read_text().splitlines() if l.startswith("STDIN")]
        self.assertTrue(stdins)
        for line in stdins:
            self.assertEqual(line.split(" ", 1)[1].strip(), "httpx==0.28.1")

    def test_check_runs_each_platform(self):
        self.check()
        args = [l for l in self.log.read_text().splitlines() if l.startswith("ARGS")]
        platforms = [re.search(r"--python-platform (\S+)", a)[1] for a in args]
        self.assertEqual(platforms, DEFAULT_PLATFORMS.split(","))
        for a in args:
            self.assertIn("--no-build", a)
            self.assertIn("--python-version 3.15", a)

    def test_check_fails_and_summarises(self):
        result = self.check(fail_platform="aarch64-manylinux_2_28")
        self.assertNotEqual(result.returncode, 0)
        summary = self.summary.read_text()
        self.assertIn("aarch64-manylinux_2_28", summary)
        self.assertIn("httptools", summary)
        self.assertNotIn("x86_64-manylinux_2_28", summary)


class ShapeTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.workflow = yaml.safe_load(self.text)

    def test_inputs_and_defaults(self):
        inputs = self.workflow[True]["workflow_call"]["inputs"]
        self.assertEqual(inputs["dockerfile"]["default"], "Dockerfile")
        self.assertEqual(inputs["build-context"]["default"], ".")
        self.assertEqual(inputs["platforms"]["default"], DEFAULT_PLATFORMS)

    def test_workflow_has_no_secrets(self):
        self.assertNotIn("secrets", self.workflow[True]["workflow_call"])
        self.assertNotIn("secrets.", self.text)

    def test_runs_on_pi_arm64_read_only(self):
        job = self.workflow["jobs"]["check"]
        self.assertEqual(job["runs-on"], "pi-arm64")
        self.assertEqual(job["permissions"], {"contents": "read"})

    def test_uv_pinned_and_check_gated_on_skip(self):
        job = self.workflow["jobs"]["check"]
        uv = next(s for s in job["steps"] if "astral-sh/setup-uv" in s.get("uses", ""))
        self.assertEqual(uv["uses"], "astral-sh/setup-uv@v10.3.3")
        self.assertIn("steps.detect.outputs.skip != 'true'", uv["if"])
        self.assertIn("steps.detect.outputs.skip != 'true'", step_named(job, "Check wheels")["if"])

    def test_inputs_reach_shell_only_through_env(self):
        for step in self.workflow["jobs"]["check"]["steps"]:
            self.assertNotIn("${{", step.get("run", ""), step.get("name"))


if __name__ == "__main__":
    unittest.main()
