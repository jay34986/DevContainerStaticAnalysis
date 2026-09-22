"""Offline integration and unit tests; no credentials or network required."""

from __future__ import annotations

import copy
import email.message
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts import jev_review as j

CONFIG = json.loads(Path("config/jev-review.json").read_text())
SHA = "a" * 40
BASE = "b" * 40
PR = {
    "number": 190,
    "title": "Bump tools",
    "body": "Release notes",
    "user": {"login": "dependabot[bot]", "type": "Bot"},
    "state": "open",
    "draft": False,
    "head": {"sha": SHA, "repo": {"full_name": "owner/repo"}},
    "base": {"sha": BASE, "ref": "develop", "repo": {"full_name": "owner/repo"}},
    "changed_files": 1,
}
FILE = {
    "filename": ".devcontainer/requirements.txt",
    "status": "modified",
    "patch": "-uv==0.11.1\n+uv==0.11.2",
}
ANSWER = {
    "model": "jev-1.13.0",
    "answers": {
        "review": {
            "type": "choice",
            "choice": "AUTO_APPROVE",
            "confidence": 0.98,
            "probabilities": {
                "AUTO_APPROVE": 1.0,
                "HUMAN_REVIEW": 0.0,
                "UNCERTAIN": 0.0,
            },
        },
    },
}


class FakeGitHub(j.GitHub):
    """Provide mutable GitHub fixtures without making network requests."""

    repository = "owner/repo"

    def __init__(self) -> None:
        """Initialize independent mutable API fixtures."""
        self.pr = copy.deepcopy(PR)
        self.files = [copy.deepcopy(FILE)]
        self.approvals = []
        self.reads = 0
        self.change_at = None
        self.failure = None

    def get(self, path: str, payload: j.JSONValue = None) -> j.JSONValue:
        """Return a fixture or record a submitted approval."""
        if self.failure:
            raise j.ReviewError(self.failure)
        if path.endswith("/reviews"):
            self.approvals.append(payload)
            return {"id": 1}
        if path.startswith("pulls/"):
            self.reads += 1
            result = copy.deepcopy(self.pr)
            if self.change_at and self.reads >= self.change_at:
                result["head"]["sha"] = "c" * 40
            return result
        raise AssertionError(path)

    def pages(self, path: str, key: str | None = None) -> list[j.JSONObject]:
        """Return fixture records for the requested endpoint."""
        if "/files" in path:
            return self.files
        raise AssertionError(path)

    def content(self, filename: str, sha: str) -> str:
        """Return manifest text for the requested commit."""
        return "uv==0.11.1\n" if sha == BASE else "uv==0.11.2\n"


class ReviewTests(unittest.TestCase):
    """Exercise classification and all approval gates using fake APIs."""

    def setUp(self) -> None:
        """Install fresh API fixtures and a mocked Jev HTTP response."""
        self.gh = FakeGitHub()
        self.http = patch.object(
            j,
            "request_json",
            return_value=copy.deepcopy(ANSWER),
        ).start()
        self.addCleanup(patch.stopall)

    def run_review(self, **kwargs: bool | str | float) -> j.JSONObject:
        """Evaluate a review with overridable approval settings."""
        return j.review(
            self.gh,
            190,
            "fake-key",
            CONFIG,
            options=j.ReviewOptions(**({"dry_run": False, "enabled": True} | kwargs)),
        )

    def test_eligible_approval_is_bound_to_sha(self) -> None:
        """Verify eligible approval is bound to sha."""
        report = self.run_review()
        self.assertEqual(report["result"], "APPROVED")
        self.assertEqual(self.gh.approvals[0]["commit_id"], SHA)
        self.http.assert_called_once()
        url, key, payload = self.http.call_args.args
        self.assertEqual(url, j.JEV_URL)
        self.assertEqual(payload["questions"]["review"]["type"], "choice")
        self.assertEqual(payload["state"]["head_sha"], SHA)

    def test_dry_run_and_disabled(self) -> None:
        """Verify dry run and disabled."""
        for kwargs in (
            {"dry_run": True},
            {"enabled": False},
            {"dry_run": True, "enabled": False},
        ):
            with self.subTest(kwargs=kwargs):
                self.run_review(**kwargs)
                self.assertEqual(self.gh.approvals, [])

    def test_non_dependabot_is_skipped_without_api(self) -> None:
        """Verify non dependabot is skipped without api."""
        self.gh.pr["user"]["login"] = "human"
        self.assertEqual(self.run_review()["result"], "SKIPPED")
        self.http.assert_not_called()

    def test_closed_draft_fork_and_untrusted_base(self) -> None:
        """Verify closed draft fork and untrusted base."""
        for field in ("closed", "draft", "fork", "base"):
            self.gh = FakeGitHub()
            if field == "closed":
                self.gh.pr["state"] = "closed"
            elif field == "draft":
                self.gh.pr["draft"] = True
            elif field == "fork":
                self.gh.pr["head"]["repo"]["full_name"] = "fork/repo"
            else:
                self.gh.pr["base"]["ref"] = "untrusted"
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)

    def test_human_and_uncertain(self) -> None:
        """Verify human and uncertain."""
        for decision in ("HUMAN_REVIEW", "UNCERTAIN"):
            answer = copy.deepcopy(ANSWER)
            answer["answers"]["review"]["choice"] = decision
            answer["answers"]["review"]["probabilities"] = {
                c: float(c == decision) for c in j.CHOICES
            }
            self.http.return_value = answer
            self.assertEqual(self.run_review()["decision"], decision)
            self.assertFalse(self.gh.approvals)

    def test_low_confidence(self) -> None:
        """Verify low confidence."""
        self.http.return_value["answers"]["review"]["confidence"] = 0.39
        self.assertIn(
            "Jev confidence below configured threshold",
            self.run_review()["reasons"],
        )
        self.assertFalse(self.gh.approvals)

    def test_invalid_responses(self) -> None:
        """Verify invalid responses."""
        for value in (None, True, "0.99", float("nan"), float("inf"), -1, 1.1):
            answer = copy.deepcopy(ANSWER)
            answer["answers"]["review"]["confidence"] = value
            self.http.return_value = answer
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)
        for response in (
            {},
            {"answers": None},
            {"answers": {"review": {"choice": "APPROVE"}}},
        ):
            self.http.return_value = response
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")

    def test_no_ci_is_required_but_sha_is_checked(self) -> None:
        """No CI endpoints exist in the fake; PR identity must still be refreshed."""
        for options, expected, reads in (
            ({"dry_run": True}, "DRY_RUN", 2),
            ({"enabled": False}, "AUTO_APPROVE_DISABLED", 2),
            ({"dry_run": True, "enabled": False}, "DRY_RUN", 2),
            ({}, "APPROVED", 3),
        ):
            with self.subTest(options=options):
                self.gh = FakeGitHub()
                report = self.run_review(**options)
                self.assertTrue(report["auto_candidate"])
                self.assertEqual(report["result"], expected)
                self.assertEqual(report["checks"], {
                    "Dependabot PR": "PASS", "Allowed files/metadata": "PASS",
                    "CI": "NOT_REQUIRED", "Commit SHA": "PASS",
                })
                self.assertEqual(self.gh.reads, reads)
                self.assertEqual(bool(self.gh.approvals), expected == "APPROVED")

    def test_protected_files_and_renames_skip_jev(self) -> None:
        """Verify protected files and renames never call Jev."""
        for name in (
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
            ".devcontainer/Dockerfile",
            ".devcontainer/devcontainer.json",
            "Dockerfile",
            "other/Dockerfile",
            ".devcontainer/bootstrap-requirements.txt",
            "README.md",
        ):
            self.gh.files[0]["filename"] = name
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)
        self.http.assert_not_called()
        self.gh.files[0] = dict(FILE, previous_filename="evil", status="renamed")
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.http.assert_not_called()

    def test_poc_decisions_and_independent_gates(self) -> None:
        """Replay supplied PoC scores without treating them as live API results."""
        cases = (
            (166, "AUTO_APPROVE", 0.51, 0.67, 0.31, True),
            (170, "AUTO_APPROVE", 0.22, 0.48, 0.48, False),
            (184, "HUMAN_REVIEW", 0.25, 0.48, 0.50, False),
            (185, "HUMAN_REVIEW", 0.94, 0.03, 0.96, False),
            (189, "AUTO_APPROVE", 0.47, 0.65, 0.31, True),
            (190, "AUTO_APPROVE", 0.47, 0.65, 0.31, True),
        )
        for number, decision, confidence, auto, human, expected in cases:
            with self.subTest(pr=number):
                self.gh = FakeGitHub()
                answer = self.http.return_value["answers"]["review"]
                answer.update(choice=decision, confidence=confidence, probabilities={
                    "AUTO_APPROVE": auto, "HUMAN_REVIEW": human,
                    "UNCERTAIN": round(1 - auto - human, 10),
                })
                report = self.run_review(dry_run=True, enabled=False)
                self.assertEqual(report["auto_candidate"], expected)
                self.assertEqual(report["result"], "DRY_RUN" if expected else "HUMAN_REVIEW")
                self.assertAlmostEqual(report["auto_margin"], auto - human)
                self.assertFalse(self.gh.approvals)
                self.assertEqual(report["checks"]["CI"], "NOT_REQUIRED")
                self.assertEqual(report["checks"]["Commit SHA"], "PASS")

    def test_threshold_boundaries_and_individual_failures(self) -> None:
        """Require each inclusive threshold and reject ties even with zero margin."""
        cases = (
            (0.40, 0.60, 0.40, {}, None),
            (0.399999, 0.65, 0.31, {}, "confidence"),
            (0.40, 0.599999, 0.30, {}, "auto_probability"),
            (0.40, 0.60, 0.300001, {"min_auto_margin": 0.30}, "margin"),
            (0.90, 0.48, 0.48, {"min_auto_probability": 0.40}, "margin"),
            (0.90, 0.50, 0.50, {"min_auto_probability": 0.40, "min_auto_margin": 0}, "margin"),
            (0.50, 0.70, 0.30, {"threshold": 0.51}, "confidence"),
            (0.50, 0.70, 0.30, {"min_auto_probability": 0.71}, "auto_probability"),
            (0.50, 0.70, 0.30, {"min_auto_margin": 0.41}, "margin"),
        )
        for confidence, auto, human, options, failure in cases:
            with self.subTest(failure=failure, options=options):
                self.gh = FakeGitHub()
                self.http.return_value["answers"]["review"].update(
                    confidence=confidence, probabilities={
                        "AUTO_APPROVE": auto, "HUMAN_REVIEW": human,
                        "UNCERTAIN": max(0, round(1 - auto - human, 10)),
                    },
                )
                report = self.run_review(dry_run=True, **options)
                self.assertEqual(report["auto_candidate"], failure is None)
                self.assertEqual(report["result"], "DRY_RUN" if failure is None else "HUMAN_REVIEW")
                if failure:
                    self.assertEqual(report["jev_gates"][failure], "FAIL")
                self.assertFalse(self.gh.approvals)

    def test_invalid_thresholds_skip_jev(self) -> None:
        """Fail closed on malformed or non-finite policy values."""
        for name in ("threshold", "min_auto_probability", "min_auto_margin"):
            for value in (True, "0.4", -0.1, 1.1, float("nan"), float("inf")):
                with self.subTest(name=name, value=value):
                    self.assertEqual(self.run_review(**{name: value})["result"], "HUMAN_REVIEW")
        self.http.assert_not_called()

    def test_manifest_prechecks_skip_jev(self) -> None:
        """Reject incomplete metadata and every unsupported manifest change before Jev."""
        for after in (
            "uv==0.11.0\n", "uv>=0.11.2\n", "uv==0.11.2\npip==26.1.0\n",
            "", "uv==0.11.1\n", "# new comment\nuv==0.11.2\n",
        ):
            with self.subTest(after=after), patch.object(
                self.gh, "content", side_effect=["uv==0.11.1\n", after],
            ):
                report = self.run_review()
                self.assertEqual(report["decision"], "NOT_CALLED")
                self.assertEqual(report["result"], "HUMAN_REVIEW")
        self.gh.files[0]["filename"] = ".devcontainer/package.json"
        with patch.object(self.gh, "content", side_effect=[
            '{"dependencies":{"x":"1.0.0"},"scripts":{"test":"safe"}}',
            '{"dependencies":{"x":"1.0.1"},"scripts":{"test":"changed"}}',
        ]):
            self.assertEqual(self.run_review()["decision"], "NOT_CALLED")
        with patch.object(self.gh, "content", side_effect=j.ReviewError("Missing manifest content")):
            self.assertEqual(self.run_review()["decision"], "NOT_CALLED")
        self.http.assert_not_called()

    def test_mixed_allowed_and_human_files_skip_jev(self) -> None:
        """One human-review file excludes the entire otherwise eligible PR."""
        self.gh.files.append(dict(FILE, filename=".devcontainer/Dockerfile"))
        self.gh.pr["changed_files"] = 2
        report = self.run_review()
        self.assertEqual(report["decision"], "NOT_CALLED")
        self.assertIn("Deterministic human-review", report["jev_skip_reason"])
        self.http.assert_not_called()

    def test_sha_changes_during_evaluation_and_before_approval(self) -> None:
        """Verify sha changes during evaluation and before approval."""
        for at in (2, 3):
            self.gh = FakeGitHub()
            self.gh.change_at = at
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)

    def test_missing_key_and_api_failure(self) -> None:
        """Verify missing key and api failure."""
        report = j.review(
            self.gh,
            190,
            "",
            CONFIG,
            options=j.ReviewOptions(dry_run=False, enabled=True),
        )
        self.assertIn("JEV_API_KEY is not configured", report["reasons"])
        self.http.assert_not_called()
        self.http.side_effect = j.ReviewError("API network error or timeout")
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.assertFalse(self.gh.approvals)

    def test_github_failure_and_file_truncation(self) -> None:
        """Verify github failure and file truncation."""
        self.gh.failure = "API HTTP error 403"
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.gh.failure = None
        self.gh.pr["changed_files"] = 2
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.assertFalse(self.gh.approvals)

    def test_missing_or_truncated_diff_skips_jev(self) -> None:
        """Missing patches and incomplete file lists stop before classification."""
        for missing_patch in (True, False):
            self.gh = FakeGitHub()
            if missing_patch:
                self.gh.files[0].pop("patch")
            else:
                self.gh.pr["changed_files"] = 2
            report = self.run_review()
            self.assertEqual(report["result"], "HUMAN_REVIEW")
            self.assertEqual(report["decision"], "NOT_CALLED")
            self.assertFalse(self.gh.approvals)
        self.http.assert_not_called()

    def test_pr_identity_changes_stop_review(self) -> None:
        """Recheck every identity field after classification and before approval."""
        changes = (
            ("state", None, "closed"), ("draft", None, True),
            ("user", "login", "human"), ("user", "type", "User"),
            ("head", "sha", "c" * 40), ("base", "sha", "c" * 40),
            ("base", "ref", "main"),
            ("head", "repo", {"full_name": "fork/repo"}),
            ("base", "repo", {"full_name": "other/repo"}),
        )
        for field, nested, value in changes:
            for at, options in ((2, {"dry_run": True}), (2, {"enabled": False}), (3, {})):
                with self.subTest(field=field, nested=nested, at=at, options=options):
                    self.gh = FakeGitHub()
                    original = self.gh.get

                    def get(path: str, payload: j.JSONValue = None) -> j.JSONValue:
                        result = original(path, payload)
                        if self.gh.reads >= at:
                            if nested is None:
                                result[field] = value
                            else:
                                result[field][nested] = value
                        return result

                    with patch.object(self.gh, "get", side_effect=get):
                        report = self.run_review(**options)
                    self.assertEqual(report["result"], "HUMAN_REVIEW")
                    self.assertEqual(report["checks"]["Commit SHA"], "FAIL")
                    self.assertFalse(self.gh.approvals)

    def test_pr_refresh_failure_stops_approval(self) -> None:
        """A failed PR reread cannot bypass the final guard."""
        for at in (2, 3):
            self.gh = FakeGitHub()
            with patch.object(self.gh, "get", side_effect=[
                *[copy.deepcopy(PR) for _ in range(at - 1)],
                j.ReviewError("API HTTP error 403"),
            ]):
                report = self.run_review()
            self.assertEqual(report["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)

    def test_latest_head_is_reclassified(self) -> None:
        """Verify latest head is reclassified."""
        latest = "d" * 40
        self.gh.pr["head"]["sha"] = latest
        self.assertEqual(self.run_review()["result"], "APPROVED")
        self.assertEqual(self.http.call_args.args[2]["state"]["head_sha"], latest)
        self.assertEqual(self.gh.approvals[0]["commit_id"], latest)

    def test_boolean_strings_never_enable_approval(self) -> None:
        """Verify boolean strings never enable approval."""
        for argument in ("dry_run", "enabled"):
            self.assertEqual(
                self.run_review(**{argument: "false"})["result"],
                "HUMAN_REVIEW",
            )
        self.assertFalse(self.gh.approvals)


class ParsingTests(unittest.TestCase):
    """Verify input parsing and transport failures without credentials."""

    def test_main_reads_independent_threshold_variables(self) -> None:
        """Pass Actions Variables through to the review policy and keep approval off."""
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(json.dumps({
                "inputs": {"pr_number": "166", "dry_run": "true"},
            }))
            environment = {
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_TOKEN": "fake-token",
                "JEV_MIN_CONFIDENCE": "0.45",
                "JEV_MIN_AUTO_PROBABILITY": "0.70",
                "JEV_MIN_AUTO_MARGIN": "0.30",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(j, "review", return_value={}) as review,
                patch.object(j, "write_summary"),
            ):
                j.main()
            self.assertEqual(
                review.call_args.kwargs["options"],
                j.ReviewOptions(
                    threshold=0.45, min_auto_probability=0.70, min_auto_margin=0.30,
                ),
            )

    def test_summary_file_for_invalid_configuration(self) -> None:
        """Write a human-review summary without exposing configuration secrets."""
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            environment = {
                "GITHUB_EVENT_PATH": str(Path(directory) / "missing-secret-event.json"),
                "GITHUB_STEP_SUMMARY": str(summary),
                "JEV_API_KEY": "missing-secret",
            }
            with patch.dict(os.environ, environment, clear=True):
                j.main()
            result = summary.read_text()
            self.assertIn("HUMAN_REVIEW", result)
            self.assertNotIn("missing-secret", result)

    def test_cli_summary_without_github_output_file(self) -> None:
        """Keep the local CLI summary available on standard output."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(j.sys, "stdout", new_callable=io.StringIO) as output,
        ):
            j.main()
            self.assertIn("Dependabot Jev Review", output.getvalue())
            self.assertIn("HUMAN_REVIEW", output.getvalue())

    def test_review_options_require_keywords(self) -> None:
        """Reject ambiguous positional approval switches."""
        with self.assertRaises(TypeError):
            j.ReviewOptions(False, True)

    def test_malformed_github_data_stops_approval(self) -> None:
        """Convert known malformed input failures into human-review reports."""
        for exception in (
            KeyError("secret"),
            TypeError("secret"),
            AttributeError("secret"),
        ):
            gh = FakeGitHub()
            with patch.object(gh, "get", side_effect=exception):
                report = j.review(gh, 190, "fake-key", CONFIG)
            self.assertEqual(report["result"], "HUMAN_REVIEW")
            self.assertNotIn("secret", json.dumps(report))
            self.assertFalse(gh.approvals)

    def test_unexpected_programming_error_is_not_swallowed(self) -> None:
        """Let unexpected defects fail the run before any approval is submitted."""
        gh = FakeGitHub()
        with (
            patch.object(gh, "get", side_effect=RuntimeError("unexpected defect")),
            self.assertRaises(RuntimeError),
        ):
            j.review(gh, 190, "fake-key", CONFIG)
        self.assertFalse(gh.approvals)

    def test_events(self) -> None:
        """Verify events."""
        for action in ("opened", "synchronize", "reopened"):
            self.assertEqual(
                j.target("pull_request", {"number": 190, "action": action}),
                (190, False),
            )
        for value in ("true", True):
            self.assertEqual(
                j.target(
                    "workflow_dispatch",
                    {"inputs": {"pr_number": "190", "dry_run": value}},
                ),
                (190, True),
            )
        self.assertEqual(
            j.target(
                "workflow_dispatch",
                {"inputs": {"pr_number": "191", "dry_run": "false"}},
            ),
            (191, False),
        )
        for value in ('"false"', "0", "null", ""):
            with self.assertRaises((j.ReviewError, ValueError)):
                j.boolean(value)

    def test_grouped_dependencies(self) -> None:
        """Verify grouped dependencies."""
        old = json.dumps(
            {"scripts": {"test": "safe"}, "dependencies": {"a": "1.0.0", "b": "2.0.0"}},
        )
        new = json.dumps(
            {"scripts": {"test": "safe"}, "dependencies": {"a": "1.1.0", "b": "3.0.0"}},
        )
        result = j.dependency_changes(".devcontainer/package.json", old, new)
        self.assertEqual([d["update_type"] for d in result], ["Minor", "Major"])
        with self.assertRaises(j.ReviewError):
            j.dependency_changes(
                ".devcontainer/package.json",
                old,
                new.replace("safe", "evil"),
            )

    def test_unsupported_requirement_and_added_dependency(self) -> None:
        """Verify unsupported requirement and added dependency."""
        for after in (
            "uv>=0.11.2",
            "uv==0.11.0",
            "uv==0.11.2\npip==26.1.0",
            "uv==0.11.2 --hash=abc",
        ):
            with self.assertRaises(j.ReviewError):
                j.dependency_changes(
                    ".devcontainer/requirements.txt",
                    "uv==0.11.1",
                    after,
                )

    def test_manifest_dispatch_accepts_root_and_nested_paths(self) -> None:
        """Recognize supported manifests independently of their directory."""
        for directory in ("", ".devcontainer/"):
            for name, before, after in (
                (
                    "package.json",
                    '{"devDependencies": {"tool": "1.0.0"}}',
                    '{"devDependencies": {"tool": "1.0.1"}}',
                ),
                ("requirements.txt", "tool==1.0.0\n", "tool==1.0.1\n"),
            ):
                with self.subTest(directory=directory, name=name):
                    updates = j.dependency_changes(directory + name, before, after)
                    self.assertEqual(len(updates), 1)
                    self.assertEqual(updates[0]["update_type"], "Patch")

    def test_unsupported_manifest_is_not_parsed_as_requirements(self) -> None:
        """An allowlist entry alone must not enable an unsupported format."""
        gh = FakeGitHub()
        filename = ".devcontainer/tool.conf"
        gh.files[0]["filename"] = filename
        config = copy.deepcopy(CONFIG)
        config["allowed_files"].append(filename)
        with patch.object(j, "request_json") as request:
            report = j.review(
                gh, 190, "fake-key", config,
                options=j.ReviewOptions(dry_run=False, enabled=True),
            )
        self.assertEqual(report["result"], "HUMAN_REVIEW")
        self.assertIn("Unsupported manifest format; human review needed", report["reasons"])
        request.assert_not_called()
        self.assertFalse(gh.approvals)

    def test_package_metadata_type_changes_require_human_review(self) -> None:
        """Do not hide boolean/number changes behind Python value equality."""
        for before, after in ((True, 1), (0, False), ([True], [1])):
            with self.subTest(before=before, after=after), self.assertRaises(j.ReviewError):
                j.dependency_changes(
                    "package.json",
                    json.dumps({"private": before, "dependencies": {"a": "1.0.0"}}),
                    json.dumps({"private": after, "dependencies": {"a": "1.0.1"}}),
                )

    def test_package_key_order_and_formatting_do_not_change_metadata(self) -> None:
        """Permit equivalent JSON formatting alongside an exact upgrade."""
        updates = j.dependency_changes(
            "package.json",
            '{"private": true, "dependencies": {"a": "1.0.0", "b": "2.0.0"}}',
            '{\n "dependencies": {"b": "2.0.0", "a": "1.0.1"}, "private": true\n}',
        )
        self.assertEqual([update["name"] for update in updates], ["a"])

    def test_transport_errors_are_sanitized(self) -> None:
        """Verify transport errors are sanitized."""
        for exc in (
            TimeoutError("secret"),
            urllib.error.URLError("secret"),
            urllib.error.HTTPError(j.JEV_URL, 401, "secret", {}, None),
        ):
            with patch.object(j.urllib.request, "build_opener") as opener:
                opener.return_value.open.side_effect = exc
                with self.assertRaises(j.ReviewError) as caught:
                    j.request_json(j.JEV_URL, "secret", {})
                self.assertNotIn("secret", str(caught.exception))

    def test_invalid_json_transport(self) -> None:
        """Verify invalid json transport."""
        with patch.object(j.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(
                b"not JSON",
            )
            with self.assertRaises(j.ReviewError):
                j.request_json(j.JEV_URL, "fake", {})

    def test_transport_rejects_untrusted_urls(self) -> None:
        """Reject unsafe schemes and destinations before constructing a request."""
        urls = (
            "file:///etc/passwd",
            "http://api.github.com/repos/owner/repo",
            "https://api.github.com.evil.example/repos/owner/repo",
            "https://api.github.com@evil.example/repos/owner/repo",
            "https://evil.example/v1/systemone",
            "https://api.typesafe.ai/v1/other",
        )
        with patch.object(j.urllib.request, "Request") as request:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(j.ReviewError):
                    j.request_json(url, "fake", {})
            request.assert_not_called()

    def test_transport_refuses_redirects(self) -> None:
        """Prevent redirects from forwarding API credentials to another host."""
        with self.assertRaises(j.ReviewError):
            j.NoRedirect().redirect_request(
                j.urllib.request.Request(j.JEV_URL),
                None,
                302,
                "Found",
                email.message.Message(),
                "https://evil.example/",
            )


class BoundaryTests(unittest.TestCase):
    """Verify untrusted JSON and output handling independently of review policy."""

    def test_choice_rejects_invalid_container_types(self) -> None:
        """Reject malformed JSON containers before using a model decision."""
        for value in (None, [], "response", {"answers": []}):
            with self.subTest(value=value), self.assertRaises(j.ReviewError):
                j.validate_choice(value)

    def test_probability_distribution_is_validated(self) -> None:
        """Reject incomplete, nonnumeric and inconsistent model distributions."""
        distributions = (
            {"AUTO_APPROVE": 1.0},
            {"AUTO_APPROVE": True, "HUMAN_REVIEW": 0, "UNCERTAIN": 0},
            {"AUTO_APPROVE": 0.6, "HUMAN_REVIEW": 0.6, "UNCERTAIN": 0},
            {"AUTO_APPROVE": 0.1, "HUMAN_REVIEW": 0.9, "UNCERTAIN": 0},
        )
        for probabilities in distributions:
            response = copy.deepcopy(ANSWER)
            response["answers"]["review"]["probabilities"] = probabilities
            with (
                self.subTest(probabilities=probabilities),
                self.assertRaises(j.ReviewError),
            ):
                j.validate_choice(response)

    def test_pages_rejects_non_object_records(self) -> None:
        """Do not return primitive values as typed GitHub records."""
        gh = j.GitHub("owner/repo", "fake")
        for response in ([None], ["record"], {"check_runs": [False]}):
            key = "check_runs" if isinstance(response, dict) else None
            with (
                patch.object(gh, "get", return_value=response),
                self.assertRaises(j.ReviewError),
            ):
                gh.pages("commits/sha/check-runs", key)

    def test_manifest_rejects_non_string_versions(self) -> None:
        """Reject malformed dependency sections and non-string versions."""
        for value in ([], {"dependencies": []}, {"dependencies": {"tool": 123}}):
            with self.subTest(value=value), self.assertRaises(j.ReviewError):
                j.manifest(".devcontainer/package.json", json.dumps(value))

    def test_summary_redacts_json_escaped_secrets(self) -> None:
        """Hide quotes, backslashes and newlines before escaping summary HTML."""
        secret = 'key"with\\slash\nand-newline'
        report = {"reasons": [f"prefix {secret} suffix", "<script>untrusted</script>"]}
        summary = j.render_summary(report, (secret,))
        self.assertIn("[REDACTED]", summary)
        self.assertNotIn("and-newline", summary)
        self.assertNotIn("<script>", summary)
        self.assertIn("&lt;script&gt;", summary)

    def test_summary_appends_to_existing_file(self) -> None:
        """Keep earlier step summaries when adding review output."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            path.write_text("Earlier step\n")
            j.write_summary("Review result\n", str(path))
            self.assertEqual(path.read_text(), "Earlier step\nReview result\n")


if __name__ == "__main__":
    unittest.main()
