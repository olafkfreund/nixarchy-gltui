import unittest
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import gitlab


def reply(body, status="200 OK", headers=""):
    return (f"HTTP/2.0 {status}\r\n{headers}\r\n" + json.dumps(body), "", 0)


PIPELINE = {"id": 7, "iid": 3, "status": "running", "source": "merge_request_event", "name": None,
            "ref": "main", "sha": "0123456789abcdef", "web_url": "https://gitlab.com/g/s/p/-/pipelines/7",
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:05:00Z",
            "user": {"name": "secret-user"}}


class ValidationTest(unittest.TestCase):
    def test_project_paths(self):
        for value in ["group/project", "g/sub/sub2/p.x", "a_b/c-d"]:
            self.assertEqual(gitlab.project_path(value), value)
        for value in ["../x", "a/..", "a/.", "-R/x", "a/-b", "single", "a//b", "a/b?x", "a/b;touch x", "a/b/", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gitlab.project_path(value)

    def test_hosts(self):
        for value in ["gitlab.com", "git.example.org:8443"]:
            self.assertEqual(gitlab.host_name(value), value)
        for value in ["-x", "a/b", "evil.test/path", "a b", "", "host:", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gitlab.host_name(value)

    def test_endpoints(self):
        base = "projects/g%2Fsub%2Fp/pipelines"
        cases = [({"kind": "catalogue", "page": 2}, "projects?membership=true&per_page=100&page=2"),
                 ({"kind": "activity", "repo": "g/sub/p"}, base + "?status=running&per_page=100&page=1"),
                 ({"kind": "summary", "repo": "g/sub/p"}, base + "?per_page=10"),
                 ({"kind": "summary", "repo": "g/sub/p", "status": "waiting_for_resource"},
                  base + "?status=waiting_for_resource&per_page=100&page=1"),
                 ({"kind": "run", "repo": "g/sub/p", "run": "7"}, base + "/7"),
                 ({"kind": "jobs", "repo": "g/sub/p", "run": 7, "page": 3},
                  base + "/7/jobs?include_retried=false&per_page=100&page=3")]
        for task, expected in cases:
            with self.subTest(task=task):
                self.assertEqual(gitlab.page_endpoint({"requestId": 1, **task}), expected)
        for task in [{"kind": "url"}, {"kind": "catalogue", "page": 0, "requestId": 1},
                     {"kind": "catalogue", "requestId": 1, "host": "evil.test/x"},
                     {"kind": "activity", "repo": "a/..", "requestId": 1},
                     {"kind": "jobs", "repo": "a/b", "run": "../x", "requestId": 1},
                     {"kind": "summary", "repo": "a/b", "status": "success", "requestId": 1}]:
            with self.subTest(task=task), self.assertRaises(ValueError):
                gitlab.page_endpoint(task)


class NormaliseTest(unittest.TestCase):
    def test_status_mapping(self):
        for raw, expected in [("running", "in_progress"), ("canceling", "in_progress"), ("created", "queued"),
                              ("waiting_for_resource", "queued"), ("preparing", "queued"), ("pending", "queued"),
                              ("success", "completed"), ("failed", "completed"), ("canceled", "completed"),
                              ("skipped", "completed"), ("manual", "completed"), ("scheduled", "completed")]:
            with self.subTest(raw=raw):
                self.assertEqual(gitlab.state(raw), expected)

    def test_pipeline_fields_and_attempt(self):
        running = gitlab.pipeline(PIPELINE)
        self.assertEqual(running, {"id": 7, "run_number": 3, "name": "merge request event", "display_title": "01234567",
                                   "head_branch": "main", "html_url": PIPELINE["web_url"],
                                   "run_started_at": "2026-01-01T00:00:00Z", "completed_at": None,
                                   "updated_at": "2026-01-01T00:05:00Z", "status": "in_progress",
                                   "conclusion": "running", "run_attempt": "active"})
        done = gitlab.pipeline({**PIPELINE, "status": "failed", "name": "Nightly", "started_at": "2026-01-01T00:01:00Z"})
        self.assertEqual((done["status"], done["conclusion"], done["name"]), ("completed", "failed", "Nightly"))
        self.assertEqual(done["run_attempt"], "2026-01-01T00:05:00Z")
        self.assertEqual(done["run_started_at"], "2026-01-01T00:01:00Z")
        self.assertEqual(gitlab.pipeline({"id": 1, "status": "manual"})["name"], "Pipeline")
        for bad in [{"id": "7", "status": "running"}, {"id": 0, "status": "running"}, {"id": 1}, []]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gitlab.pipeline(bad)


class PageTest(unittest.TestCase):
    def test_headers_pagination_and_single_call(self):
        task = {"kind": "activity", "repo": "g/p", "page": 1, "requestId": 3, "host": "git.example.org"}
        output = ('HTTP/1.1 100 Continue\r\n\r\nHTTP/2.0 200 OK\r\n'
                  'Ratelimit-Remaining: 42\r\nRatelimit-Reset: 1700000000\r\n'
                  'Private-Token: must-not-escape\r\nX-Next-Page: 2\r\n\r\n' + json.dumps([PIPELINE]))
        with patch.object(gitlab, "request", return_value=(output, "", 0)) as request:
            result = gitlab.read_page(task)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[1], "git.example.org")
            self.assertEqual(result["nextPage"], 2)
            self.assertEqual(result["remaining"], 42)
            self.assertEqual(result["resetAt"], 1700000000000)
            self.assertEqual(result["requestId"], 3)
            self.assertEqual(result["data"][0]["status"], "in_progress")
            self.assertNotIn("must-not-escape", json.dumps(result))
            self.assertNotIn("secret-user", json.dumps(result))

    def test_next_page_header(self):
        self.assertEqual(gitlab.next_page({"x-next-page": ""}, 1), 0)
        self.assertEqual(gitlab.next_page({}, 4), 0)
        self.assertEqual(gitlab.next_page({"x-next-page": "5"}, 4), 5)
        for value in ["7", "x", "-1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gitlab.next_page({"x-next-page": value}, 4)
        with patch.object(gitlab, "request", return_value=reply([], headers="X-Next-Page: 9\r\n")):
            self.assertEqual(gitlab.read_page({"kind": "catalogue", "requestId": 1})["errorType"], "network")

    def test_catalogue_and_jobs(self):
        projects = [{"path_with_namespace": "g/sub/p", "description": None, "web_url": "https://gitlab.com/g/sub/p",
                     "last_activity_at": "2026-01-02T00:00:00Z", "archived": False, "builds_access_level": "disabled",
                     "owner": {"name": "leak"}}]
        with patch.object(gitlab, "request", return_value=reply(projects)):
            data = gitlab.read_page({"kind": "catalogue", "requestId": 1})["data"]
        self.assertEqual(data, [{"repo": "g/sub/p", "description": "", "url": "https://gitlab.com/g/sub/p",
                                 "lastActivity": "2026-01-02T00:00:00Z", "archived": False, "disabled": True}])
        jobs = [{"id": 9, "name": "test", "stage": "test", "status": "failed", "allow_failure": True,
                 "runner": {"description": "leak"}},
                {"id": 8, "name": "build", "stage": "build", "status": "success", "finished_at": "2026-01-01T00:02:00Z"}]
        with patch.object(gitlab, "request", return_value=reply(jobs)):
            data = gitlab.read_page({"kind": "jobs", "repo": "g/p", "run": "7", "requestId": 1})["data"]
        self.assertEqual([row["id"] for row in data], [8, 9])
        self.assertEqual(data[0]["completed_at"], "2026-01-01T00:02:00Z")
        self.assertEqual((data[1]["conclusion"], data[1]["allow_failure"]), ("failed", True))
        self.assertNotIn("leak", json.dumps(data))

    def test_single_pipeline(self):
        with patch.object(gitlab, "request", return_value=reply({**PIPELINE, "status": "success"})):
            result = gitlab.read_page({"kind": "run", "repo": "g/p", "run": "7", "requestId": 1})
            self.assertEqual(result["data"]["conclusion"], "success")
        with patch.object(gitlab, "request", return_value=reply({**PIPELINE, "id": 8})):
            self.assertEqual(gitlab.read_page({"kind": "run", "repo": "g/p", "run": "7", "requestId": 1})["errorType"], "network")

    def test_api_errors_keep_metadata(self):
        for status, message, extra, expected in [
            (429, "Retry later", "Retry-After: 60\n", "rate"),
            (403, "rate limit exceeded", "", "rate"),
            (403, "Forbidden", "Ratelimit-Remaining: 0\nRatelimit-Reset: 1700000000\n", "rate"),
            (401, "401 Unauthorized", "", "auth"),
            (403, "403 Forbidden", "", "permission"),
            (404, "404 Project Not Found", "", "permission"),
            (502, "Unavailable", "", "network")]:
            with self.subTest(status=status, message=message), patch.object(gitlab, "request", return_value=(
                    f"HTTP/2.0 {status} Error\n{extra}\n" + json.dumps({"message": message}), "glab failed", 1)):
                result = gitlab.read_page({"kind": "catalogue", "requestId": 1})
                self.assertEqual(result["errorType"], expected)
                self.assertEqual(result["httpStatus"], status)
                if "Retry-After" in extra:
                    self.assertGreater(result["retryAt"], time.time() * 1000)
                if "Remaining" in extra:
                    self.assertEqual(result["remaining"], 0)

    def test_broken_responses(self):
        for stdout in ["", "garbage", "HTTP/2.0 200 OK\n\ninvalid", "HTTP/2.0 200 OK\n\n{}",
                       "HTTP/2.0 200 OK\n\n[{\"path_with_namespace\": \"../x\"}]"]:
            with self.subTest(stdout=stdout), patch.object(gitlab, "request", return_value=(stdout, "", 0)):
                self.assertEqual(gitlab.read_page({"kind": "catalogue", "requestId": 1})["errorType"], "network")

    def test_missing_auth_and_non_json_rate_error(self):
        task = {"kind": "catalogue", "requestId": 1}
        with patch.object(gitlab, "request", return_value=("", "Run glab auth login to authenticate", 1)):
            self.assertEqual(gitlab.read_page(task)["errorType"], "auth")
        with patch.object(gitlab, "request", return_value=("HTTP/2.0 429 Error\nRetry-After: 60\n\n<html>Slow down</html>", "failed", 1)):
            result = gitlab.read_page(task)
            self.assertEqual(result["errorType"], "rate")
            self.assertGreater(result["retryAt"], time.time() * 1000)

    def test_recent_history_does_not_follow_pagination(self):
        with patch.object(gitlab, "request", return_value=reply([], headers="X-Next-Page: 99\r\n")):
            result = gitlab.read_page({"kind": "summary", "repo": "g/p", "status": "recent", "requestId": 1})
            self.assertEqual(result["nextPage"], 0)
            self.assertEqual(result["error"], "")


class ProcessTest(unittest.TestCase):
    request = json.dumps({"kind": "activity", "repo": "g/p", "requestId": 1})

    def test_cancellation_reaps_glab(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "glab"
            pidfile = Path(directory) / "pid"
            fake.write_text(f"#!{sys.executable}\nimport os,time\nopen({str(pidfile)!r},'w').write(str(os.getpid()))\ntime.sleep(30)\n")
            fake.chmod(0o700)
            process = subprocess.Popen([sys.executable, "gitlab.py", "page", self.request],
                                       env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}, stdout=subprocess.PIPE)
            try:
                for _ in range(100):
                    if pidfile.exists() and pidfile.read_text():
                        break
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists(), "Fake glab did not start")
                child = int(pidfile.read_text())
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=3)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_missing_glab_is_json_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "gitlab.py", "page", self.request],
                                    env={**os.environ, "PATH": directory}, capture_output=True, text=True, check=True)
            reply = json.loads(result.stdout)
            self.assertEqual((reply["requestId"], reply["errorType"]), (1, "network"))

    def test_invalid_request_is_json_error(self):
        result = subprocess.run([sys.executable, "gitlab.py", "page", '{"kind":"url"}'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))


class HardeningTest(unittest.TestCase):
    def test_body_is_not_read_as_headers(self):
        self.assertEqual(gitlab.http_reply("HTTP/2 200\n\nHTTP/1.1 500 x\n\n[]"), (200, {}, "HTTP/1.1 500 x\n\n[]"))
        status, headers, body = gitlab.http_reply("HTTP/1.1 100 Continue\n\nHTTP/1.1 200 OK\nA: b\n\n[]")
        self.assertEqual((status, headers, body), (200, {"a": "b"}, "[]"))

    def test_redirect_is_reported(self):
        with patch.object(gitlab, "request", return_value=("HTTP/2.0 301 Moved\nLocation: x\n\n", "", 0)):
            result = gitlab.read_page({"kind": "catalogue", "requestId": 1})
        self.assertEqual(result["errorType"], "network")
        self.assertEqual(result["error"], "GitLab redirected the request; the project may have moved")

    def test_deadline_reports_timeout(self):
        out = io.StringIO()
        with patch.object(sys, "argv", ["gitlab.py", "page", "{}"]), \
                patch.object(gitlab, "read_page", side_effect=gitlab.DeadlineExceeded()), \
                contextlib.redirect_stdout(out):
            self.assertEqual(gitlab.main(), 1)
        self.assertEqual(json.loads(out.getvalue()), {"error": "GitLab request timed out"})


if __name__ == "__main__":
    unittest.main()
