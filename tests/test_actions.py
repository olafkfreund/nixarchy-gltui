import unittest
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import actions


class ActionsTest(unittest.TestCase):
    def test_pagination(self):
        with patch.object(actions, "api", side_effect=[{"jobs": list(range(100))}, {"jobs": [100]}]) as api:
            self.assertEqual(list(actions.pages("endpoint?filter=latest", "jobs")), list(range(101)))
            self.assertIn("&per_page=100&page=2", api.call_args.args[0])

    def test_repository_discovery_pages_and_affiliations(self):
        rows = [{"full_name": f"org/repo{i}", "description": None} for i in range(100)]
        with patch.object(actions, "api", side_effect=[rows, []]) as api:
            first = actions.repositories_page("1")
            self.assertEqual(first["nextPage"], 2)
            self.assertEqual(first["repos"][0]["repo"], "org/repo0")
            self.assertEqual(first["repos"][0]["description"], "")
            self.assertIn("affiliation=owner,collaborator,organization_member", api.call_args.args[0])
            self.assertEqual(actions.repositories_page("2")["nextPage"], 0)
        with self.assertRaises(ValueError):
            actions.repositories_page("0")

    def test_activity_uses_paginated_running_filter(self):
        with patch.object(actions, "pages", return_value=iter([{"id": 1}])) as pages:
            self.assertEqual(actions.activity("owner/repo"), {"repo": "owner/repo", "runs": [{"id": 1}], "active": 1})
            self.assertEqual(pages.call_args.args, ("repos/owner/repo/actions/runs?status=in_progress", "workflow_runs"))

    def test_active_runs_and_completion_race(self):
        active = {"id": 1, "status": "in_progress"}
        completed = {"id": 1, "status": "completed"}
        queued = {"id": 2, "status": "queued"}
        with patch.object(actions, "pages", side_effect=[[queued], [active], [], [], []]), patch.object(actions, "api", return_value={"workflow_runs": [completed]}):
            self.assertEqual(actions.runs("owner/repo"), [queued, completed])

    def test_partial_failure_preserves_other_repos(self):
        with patch.object(actions, "runs", side_effect=[RuntimeError("offline"), []]):
            data = actions.summary(["a/one", "b/two", "b/two"])
            self.assertEqual(data, [{"repo": "a/one", "error": "offline"}, {"repo": "b/two", "runs": [], "error": ""}])

    def test_deadline_stops_entire_scan(self):
        with patch.object(actions, "runs", side_effect=actions.DeadlineExceeded) as runs:
            with self.assertRaises(actions.DeadlineExceeded):
                actions.summary(["a/one", "b/two"])
            self.assertEqual(runs.call_count, 1)

    def test_validation(self):
        for value in ["../x", "a/..", "-R", "a/b/c", "a/b?x", "a/b;touch x"]:
            with self.assertRaises(ValueError):
                actions.repo_name(value)
        self.assertEqual(actions.repo_name("olafkfreund/nixarchy"), "olafkfreund/nixarchy")

    def test_cancellation_reaps_gh(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "gh"
            pidfile = Path(directory) / "pid"
            fake.write_text(f"#!{sys.executable}\nimport os,time\nopen({str(pidfile)!r},'w').write(str(os.getpid()))\ntime.sleep(30)\n")
            fake.chmod(0o700)
            process = subprocess.Popen([sys.executable, "actions.py", "summary", "owner/repo"], env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}, stdout=subprocess.PIPE)
            try:
                for _ in range(100):
                    if pidfile.exists() and pidfile.read_text():
                        break
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists(), "Fake gh did not start")
                child = int(pidfile.read_text())
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=3)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_missing_gh_is_json_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "actions.py", "summary", "owner/repo"], env={**os.environ, "PATH": directory}, capture_output=True, text=True, check=True)
            self.assertIn("error", json.loads(result.stdout)["repos"][0])


class PageTest(unittest.TestCase):
    def test_headers_pagination_and_single_call(self):
        task = {"kind":"activity", "repo":"a/b", "page":1, "requestId":3}
        output = ('HTTP/1.1 100 Continue\r\n\r\nHTTP/2.0 200 OK\r\n'
                  'X-RateLimit-Remaining: 42\r\nX-RateLimit-Reset: 1700000000\r\n'
                  'Authorization: must-not-escape\r\n'
                  'Link: <https://api.github.com/repos/a/b/actions/runs?status=in_progress&per_page=100&page=2>; rel="next"\r\n\r\n'
                  '{"workflow_runs":[{"id":7,"status":"in_progress"}]}')
        with patch.object(actions, "request", return_value=(output, "", 0)) as request:
            result = actions.read_page(task)
            self.assertEqual(request.call_count, 1)
            self.assertTrue(request.call_args.kwargs["include"])
            self.assertEqual(result["nextPage"], 2)
            self.assertEqual(result["remaining"], 42)
            self.assertEqual(result["resetAt"], 1700000000000)
            self.assertEqual(result["requestId"], 3)
            self.assertNotIn("must-not-escape", json.dumps(result))

    def test_api_errors_keep_metadata(self):
        for status, message, extra, expected in [
            (403, "API rate limit exceeded", "X-RateLimit-Remaining: 0\nX-RateLimit-Reset: 1700000000\n", "rate"),
            (429, "slow down", "Retry-After: 60\n", "rate"),
            (403, "secondary rate limit", "", "rate"),
            (401, "Bad credentials", "", "auth"),
            (403, "Resource not accessible", "", "permission"),
            (404, "Not found", "", "permission"),
            (502, "Unavailable", "", "network")]:
            with self.subTest(status=status, message=message), patch.object(actions, "request", return_value=(
                    f"HTTP/2.0 {status} Error\n{extra}\n" + json.dumps({"message":message}), "gh failed", 1)):
                result = actions.read_page({"kind":"catalogue", "requestId":1})
                self.assertEqual(result["errorType"], expected)
                self.assertEqual(result["httpStatus"], status)
                if "Retry-After" in extra:
                    self.assertGreater(result["retryAt"], time.time() * 1000)
                if "Remaining" in extra:
                    self.assertEqual(result["remaining"], 0)

    def test_validation_and_broken_responses(self):
        for task in [{"kind":"url"}, {"kind":"catalogue", "page":0, "requestId":1},
                     {"kind":"activity", "repo":"a/..", "requestId":1},
                     {"kind":"jobs", "repo":"a/b", "run":"../x", "requestId":1},
                     {"kind":"summary", "repo":"a/b", "status":"evil", "requestId":1}]:
            with self.assertRaises(ValueError):
                actions.page_endpoint(task)
        for stdout in ["", "garbage", "HTTP/2.0 200 OK\n\ninvalid", "HTTP/2.0 200 OK\n\n{}"]:
            with patch.object(actions, "request", return_value=(stdout, "", 0)):
                self.assertEqual(actions.read_page({"kind":"catalogue", "requestId":1})["errorType"], "network")
        with self.assertRaises(ValueError):
            actions.next_page("user/repos?per_page=100&page=1", {"link":'<https://evil.test/user/repos?per_page=100&page=2>; rel="next"'})

    def test_missing_auth_and_non_json_rate_error(self):
        task = {"kind":"catalogue", "requestId":1}
        with patch.object(actions, "request", return_value=("", "Please run gh auth login", 1)):
            self.assertEqual(actions.read_page(task)["errorType"], "auth")
        with patch.object(actions, "request", return_value=("HTTP/2.0 429 Error\nRetry-After: 60\n\n<html>Slow down</html>", "failed", 1)):
            reply=actions.read_page(task)
            self.assertEqual(reply["errorType"], "rate")
            self.assertGreater(reply["retryAt"], time.time()*1000)

    def test_recent_history_does_not_follow_pagination(self):
        with patch.object(actions, "request", return_value=('HTTP/2.0 200 OK\nLink: <https://evil.test/>; rel="next"\n\n{"workflow_runs":[]}', "", 0)):
            result = actions.read_page({"kind":"summary", "repo":"a/b", "status":"recent", "requestId":1})
            self.assertEqual(result["nextPage"], 0)
            self.assertEqual(result["error"], "")


if __name__ == "__main__":
    unittest.main()
