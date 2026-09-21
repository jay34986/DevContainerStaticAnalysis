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
        self.required = [{"context": "test", "app_id": 15368}]
        self.runs = [
            {
                "name": "test",
                "app": {"id": 15368},
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
            },
        ]
        self.statuses = []
        self.rules = []
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
        if path.startswith("branches/"):
            return {
                "protection": {
                    "required_status_checks": {"checks": self.required, "contexts": []},
                },
            }
        raise AssertionError(path)

    def pages(self, path: str, key: str | None = None) -> list[j.JSONObject]:
        """Return fixture records for the requested endpoint."""
        if "/files" in path:
            return self.files
        if "/check-runs" in path:
            return self.runs
        if "/statuses" in path:
            return self.statuses
        if path.startswith("rules/"):
            return self.rules
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

    def run_review(self, **kwargs: bool | str) -> j.JSONObject:
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
        self.http.return_value["answers"]["review"]["confidence"] = 0.94
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

    def test_failed_pending_cancelled_skipped_and_missing_ci(self) -> None:
        """Verify failed pending cancelled skipped and missing ci."""
        for conclusion in ("failure", "cancelled", "skipped", "neutral", None):
            self.gh.runs[0]["conclusion"] = conclusion
            self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
            self.assertFalse(self.gh.approvals)
        self.gh.runs = []
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.gh.required = []
        self.assertIn(
            "No required CI checks configured or discovered",
            self.run_review()["reasons"],
        )

    def test_app_identity_and_duplicate_checks(self) -> None:
        """Verify app identity and duplicate checks."""
        self.gh.runs[0]["app"]["id"] = 42
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.gh = FakeGitHub()
        self.gh.runs *= 2
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")

    def test_classic_status_and_ruleset(self) -> None:
        """Verify classic status and ruleset."""
        self.gh.required = []
        self.gh.rules = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "legacy", "integration_id": None},
                    ],
                },
            },
        ]
        self.gh.statuses = [
            {"context": "legacy", "state": "pending"},
            {"context": "legacy", "state": "success"},
        ]
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")
        self.gh.statuses.pop(0)
        self.assertEqual(self.run_review()["result"], "APPROVED")

    def test_circular_dependency(self) -> None:
        """Verify circular dependency."""
        self.gh.required = [{"context": j.SELF_CHECK}]
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")

    def test_protected_files_and_renames_still_classified(self) -> None:
        """Verify protected files and renames still classified."""
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
        self.http.assert_called()
        self.gh.files[0] = dict(FILE, previous_filename="evil", status="renamed")
        self.assertEqual(self.run_review()["result"], "HUMAN_REVIEW")

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

    def test_ci_failure_on_final_refresh(self) -> None:
        """Verify ci failure on final refresh."""
        original = self.gh.pages
        calls = 0
        final_refresh = 2

        def pages(path: str, key: str | None = None) -> list[j.JSONObject]:
            """Return fixture records for the requested endpoint."""
            nonlocal calls
            if "/check-runs" in path:
                calls += 1
                if calls == final_refresh:
                    self.gh.runs[0]["conclusion"] = "failure"
            return original(path, key)

        self.gh.pages = pages
        report = self.run_review()
        self.assertEqual(report["result"], "HUMAN_REVIEW")
        self.assertEqual(report["checks"]["CI"], "FAIL")
        self.assertFalse(self.gh.approvals)

    def test_latest_head_is_reclassified(self) -> None:
        """Verify latest head is reclassified."""
        latest = "d" * 40
        self.gh.pr["head"]["sha"] = latest
        self.gh.runs[0]["head_sha"] = latest
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
