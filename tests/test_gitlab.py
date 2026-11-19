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
from urllib.parse import unquote
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
                  base + "/7/jobs?include_retried=false&per_page=100&page=3"),
                 ({"kind": "bridges", "repo": "g/sub/p", "run": 7}, base + "/7/bridges?per_page=100&page=1"),
                 ({"kind": "bridges", "repo": "g/sub/p", "run": 7, "route": "bridges", "page": 3},
                  base + "/7/bridges?per_page=100&page=3"),
                 ({"kind": "bridges", "repo": "g/sub/p", "run": 7, "route": "trigger_jobs", "page": 3},
                  base + "/7/trigger_jobs?per_page=100&page=3")]
        for task, expected in cases:
            with self.subTest(task=task):
                self.assertEqual(gitlab.page_endpoint({"requestId": 1, **task}), expected)
        for task in [{"kind": "url"}, {"kind": "catalogue", "page": 0, "requestId": 1},
                     {"kind": "catalogue", "requestId": 1, "host": "evil.test/x"},
                     {"kind": "activity", "repo": "a/..", "requestId": 1},
                     {"kind": "jobs", "repo": "a/b", "run": "../x", "requestId": 1},
                     {"kind": "bridges", "repo": "a/b", "run": "../x", "requestId": 1},
                     {"kind": "bridges", "repo": "a/b", "run": 7, "route": "jobs", "requestId": 1},
                     {"kind": "summary", "repo": "a/b", "status": "success", "requestId": 1}]:
            with self.subTest(task=task), self.assertRaises(ValueError):
                gitlab.page_endpoint(task)


class PinsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"XDG_STATE_HOME": self.temp.name, "HOME": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.path = gitlab.state_path()

    def write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(value)

    def test_load_and_validation(self):
        self.assertEqual(gitlab.pins({"host": "GITLAB.COM"}), {"pins": []})
        self.write(json.dumps({"version": 1, "hosts": {"gitlab.com": ["a/b", "bad", 3, "c/d"]}}))
        self.assertEqual(gitlab.pins({"host": "Gitlab.com"}), {"pins": ["a/b", "c/d"]})
        for value in ("{bad", "[]", '{"version": 2, "hosts": {}}',
                      '{"version": 1, "hosts": {"gitlab.com": "x"}}'):
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaisesRegex(ValueError, "pinned.json is not valid"):
                    gitlab.pins({"host": "gitlab.com"})

    def test_unreadable(self):
        if os.geteuid() == 0:
            self.skipTest("root can read mode 000")
        self.write('{"version": 1, "hosts": {}}')
        self.path.chmod(0)
        self.addCleanup(self.path.chmod, 0o600)
        with self.assertRaisesRegex(ValueError, "Cannot read pinned.json"):
            gitlab.pins({"host": "gitlab.com"})
        with self.assertRaisesRegex(ValueError, "Cannot read pinned.json"):
            gitlab.pins({"host": "gitlab.com", "save": ["a/b"]})

    def test_save_preserves_hosts_and_modes(self):
        self.assertEqual(gitlab.pins({"host": "Gitlab.Example.org:8443", "save": ["a/b", "a/b", "c/d"]}),
                         {"pins": ["a/b", "c/d"]})
        state = json.loads(self.path.read_text())
        self.assertEqual(state["hosts"], {"gitlab.example.org:8443": ["a/b", "c/d"]})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        gitlab.pins({"host": "other.test", "save": ["x/y"]})
        self.assertEqual(json.loads(self.path.read_text())["hosts"],
                         {"gitlab.example.org:8443": ["a/b", "c/d"], "other.test": ["x/y"]})

    def test_save_refuses_bad_state_and_replace_failure(self):
        for value in ("{bad", '{"version": 2, "hosts": {}}'):
            self.write(value)
            with self.assertRaisesRegex(ValueError, "pinned.json is not valid"):
                gitlab.pins({"host": "gitlab.com", "save": ["a/b"]})
            self.assertEqual(self.path.read_text(), value)
        old = '{"version": 1, "hosts": {"other.test": ["x/y"]}}'
        self.write(old)
        with patch.object(gitlab.os, "replace", side_effect=OSError("fail")):
            with self.assertRaisesRegex(ValueError, "Cannot write pinned.json"):
                gitlab.pins({"host": "gitlab.com", "save": ["a/b"]})
        self.assertEqual(self.path.read_text(), old)
        self.assertEqual(list(self.path.parent.glob(".pinned-*")), [])

    def test_bad_input_and_fallback_path(self):
        for task in ({"host": "bad/host"}, {"host": "gitlab.com", "save": "a/b"},
                     {"host": "gitlab.com", "save": ["bad"]}, []):
            with self.subTest(task=task), self.assertRaises(ValueError):
                gitlab.pins(task)
        for base in ("", "relative"):
            with patch.dict(os.environ, {"XDG_STATE_HOME": base}):
                self.assertEqual(gitlab.state_path(), Path(self.temp.name) / ".local/state/omarchy-gitlab-pipelines/pinned.json")

    def test_main(self):
        for request, expected, code in [('{"host":"gitlab.com"}', {"pins": []}, 0),
                                         ('{"host":"bad/host"}', {"error": "Invalid GitLab host"}, 1),
                                         ('not json', None, 1)]:
            out = io.StringIO()
            with patch.object(sys, "argv", ["gitlab.py", "pins", request]), contextlib.redirect_stdout(out):
                self.assertEqual(gitlab.main(), code)
            value = json.loads(out.getvalue())
            if expected is None:
                self.assertIn("error", value)
            else:
                self.assertEqual(value, expected)


class ActionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"HOME": temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.config = Path(temp.name) / ".config/omarchy/shell.json"
        self.config.parent.mkdir(parents=True)
        self.task = {"requestId": 4, "host": "GitLab.com", "repo": "g/sub/p", "run": "7"}

    def enable(self, **changes):
        self.config.write_text(json.dumps({"plugins": [{"id": "olafkfreund.gitlab-pipelines",
                                                     "actions": True, **changes}]}))

    def test_endpoints_and_request_arguments(self):
        base = "projects/g%2Fsub%2Fp"
        cases = [("retry-pipeline", {}, base + "/pipelines/7/retry"),
                 ("cancel-pipeline", {}, base + "/pipelines/7/cancel"),
                 ("retry-job", {"job": 9}, base + "/jobs/9/retry"),
                 ("cancel-job", {"job": 9}, base + "/jobs/9/cancel"),
                 ("play-job", {"job": 9}, base + "/jobs/9/play"),
                 ("new-pipeline", {"ref": "main"}, base + "/pipeline?ref=main")]
        self.enable()
        for action, extra, endpoint in cases:
            with self.subTest(action=action), patch.object(gitlab, "request", return_value=reply({"id": 8})) as request:
                task = {**self.task, "action": action, **extra}
                self.assertEqual(gitlab.write_endpoint(task), endpoint)
                self.assertTrue(gitlab.write_action(task)["ok"])
                request.assert_called_once_with(endpoint, "GitLab.com", "POST")
        child = unittest.mock.Mock()
        child.communicate.return_value = ("", "")
        child.poll.return_value = 0
        with patch.object(gitlab.subprocess, "Popen", return_value=child) as popen:
            gitlab.request("projects/g%2Fp/pipeline?ref=main", "gitlab.com", "POST")
        self.assertEqual(popen.call_args.args[0], ["glab", "api", "--hostname", "gitlab.com",
                                                   "--include", "--method", "POST", "projects/g%2Fp/pipeline?ref=main"])

    def test_invalid_actions_ids_and_refs(self):
        for changes in ({"action": "delete"}, {"action": "retry-pipeline", "run": "../7"},
                        {"action": "retry-job", "job": 0}, {"action": "retry-job", "job": True},
                        {"action": "new-pipeline", "ref": ""},
                        {"action": "new-pipeline", "ref": "a" * 256},
                        {"action": "new-pipeline", "ref": "refs/merge-requests/2/head"},
                        {"action": "new-pipeline", "ref": "a\n"},
                        {"action": "new-pipeline", "ref": "a\x7f"},
                        {"action": "new-pipeline", "ref": "main", "source": "merge_request_event"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                gitlab.write_endpoint({**self.task, **changes})
        ref = "café&#%+/branch"
        endpoint = gitlab.write_endpoint({**self.task, "action": "new-pipeline", "ref": ref})
        self.assertEqual(unquote(endpoint.split("ref=", 1)[1]), ref)

    def test_gate_never_requests_when_disabled(self):
        task = {**self.task, "action": "retry-pipeline"}
        with patch.object(gitlab, "request") as request:
            for contents in (None, json.dumps({"plugins": [{"id": "olafkfreund.gitlab-pipelines", "actions": False}]}),
                             json.dumps({"plugins": [{"id": "olafkfreund.gitlab-pipelines", "actions": True,
                                                      "host": "elsewhere.test"}]}), "{bad"):
                with self.subTest(contents=contents):
                    if contents is None:
                        self.config.unlink(missing_ok=True)
                    else:
                        self.config.write_text(contents)
                    result = gitlab.write_action(task)
                    self.assertEqual((result["errorType"], result["error"]),
                                     ("disabled", "Actions are off in shell.json"))
            request.assert_not_called()

    def test_replies(self):
        self.enable()
        task = {**self.task, "action": "retry-pipeline"}
        cases = [("429 Too Many Requests", {"message": "Wait"}, "", "rate"),
                 ("403 Forbidden", {"message": "rate limit exceeded"}, "", "rate"),
                 ("401 Unauthorized", {"message": "No"}, "", "auth"),
                 ("403 Forbidden", {"error": "insufficient_scope", "error_description": "more", "scope": "api"}, "", "scope"),
                 ("403 Forbidden", {"error": "insufficient_scope", "message": "Denied"}, "", "scope"),
                 ("403 Forbidden", {"message": "Denied"}, "", "refused"),
                 ("400 Bad Request", {"message": {"base": ["one", "two"]}}, "", "refused"),
                 ("404 Not Found", {"message": "Gone"}, "", "refused"),
                 ("409 Conflict", {"message": "Busy"}, "", "refused"),
                 ("422 Unprocessable", {"message": "Invalid"}, "", "refused"),
                 ("302 Found", {}, "", "refused"),
                 ("503 Unavailable", {"message": "Error"}, "", "unknown")]
        for status, body, headers, kind in cases:
            with self.subTest(status=status, body=body), patch.object(gitlab, "request", return_value=reply(body, status, headers)):
                result = gitlab.write_action(task)
                self.assertEqual(result["errorType"], kind)
                self.assertFalse(result["ok"])
                if body.get("message") == {"base": ["one", "two"]}:
                    self.assertEqual(result["error"], "GitLab refused: one; two")
        with patch.object(gitlab, "request", return_value=reply({"id": 8, "iid": 6}, headers="Ratelimit-Remaining: 0\r\nRatelimit-Reset: 1700000000\r\n")):
            result = gitlab.write_action({**task, "action": "retry-job", "job": 9})
            self.assertEqual((result["ok"], result["remaining"], result["resetAt"], result["created"]),
                             (True, 0, 1700000000000, {"id": 8, "iid": 6}))
        with patch.object(gitlab, "request", return_value=reply({"id": 11, "iid": 7})):
            self.assertEqual(gitlab.write_action({**task, "action": "new-pipeline", "ref": "main"})["created"],
                             {"id": 11, "iid": 7})
        for response in [("", "run glab auth login", 1), ("", "failed", 1),
                         ("HTTP/2.0 200 OK\n\nnot json", "", 0)]:
            with self.subTest(response=response), patch.object(gitlab, "request", return_value=response):
                self.assertEqual(gitlab.write_action(task)["errorType"],
                                 "auth" if "auth login" in response[1] else "unknown")
        for failure, kind in [(FileNotFoundError(), "setup"), (subprocess.TimeoutExpired("glab", 25), "unknown")]:
            with self.subTest(kind=kind), patch.object(gitlab, "request", side_effect=failure):
                self.assertEqual(gitlab.write_action(task)["errorType"], kind)

    def test_ref_keeps_control_free_raw_text(self):
        ref = "café\u200b&#%+/branch"
        value = gitlab.pipeline({**PIPELINE, "ref": ref})
        self.assertEqual(value["ref"], ref)
        self.assertNotEqual(value["head_branch"], ref)

    def test_main_validation_and_disabled(self):
        for task, expected, code in [({**self.task, "action": "bad"}, "setup", 1),
                                     ({**self.task, "action": "retry-pipeline"}, "disabled", 0)]:
            with self.subTest(task=task), patch.object(sys, "argv", ["gitlab.py", "act", json.dumps(task)]), \
                    patch.object(gitlab, "request") as request, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gitlab.main(), code)
                self.assertEqual(json.loads(output.getvalue())["errorType"], expected)
                request.assert_not_called()


class NormaliseTest(unittest.TestCase):
    def test_status_mapping(self):
        for raw, expected in [("running", "in_progress"), ("canceling", "in_progress"), ("created", "queued"),
                              ("waiting_for_resource", "queued"), ("preparing", "queued"), ("pending", "queued"),
                              ("success", "completed"), ("failed", "completed"), ("canceled", "completed"),
                              ("skipped", "completed"), ("manual", "completed"), ("scheduled", "completed")]:
            with self.subTest(raw=raw):
                self.assertEqual(gitlab.state(raw), expected)

    def test_waiting_for_callback_job_is_queued(self):
        self.assertEqual(gitlab.job({"id": 5, "status": "waiting_for_callback"})["status"], "queued")

    def test_job_details(self):
        base = {"id": 5, "status": "failed"}
        result = gitlab.job({**base, "failure_reason": "script\u0000_failure\n", "duration": 62,
                             "queued_duration": 1.5})
        self.assertEqual((result["failure_reason"], result["duration"], result["queued_duration"]),
                         ("script_failure", 62, 1.5))
        self.assertEqual(gitlab.job(base)["failure_reason"], "")
        self.assertEqual(gitlab.job({**base, "failure_reason": 12})["failure_reason"], "")
        for value in (None, -1, True, "12", float("inf")):
            with self.subTest(value=value):
                result = gitlab.job({**base, "duration": value, "queued_duration": value})
                self.assertIsNone(result["duration"])
                self.assertIsNone(result["queued_duration"])
        self.assertIsNone(gitlab.job(base)["duration"])
        self.assertIsNone(gitlab.job(base)["queued_duration"])

    def test_bridge_details(self):
        base = {"id": 5, "status": "success", "name": "deploy", "stage": "test",
                "pipeline": {"project_id": 42}}
        self.assertIsNone(gitlab.bridge(base, "gitlab.com")["downstream"])
        self.assertIsNone(gitlab.bridge({**base, "downstream_pipeline": []}, "gitlab.com")["downstream"])
        downstream = {"id": 7, "iid": 3, "project_id": 42, "status": "running", "ref": "main",
                      "sha": "a" * 40, "web_url": "https://gitlab.com/g/sub/p/-/pipelines/7"}
        result = gitlab.bridge({**base, "downstream_pipeline": downstream}, "gitlab.com")
        self.assertEqual(result["name"], "deploy")
        self.assertEqual(result["downstream"], {
            "id": 7, "iid": 3, "project_id": 42, "parent_project_id": 42,
            "status": "in_progress", "conclusion": "running", "ref": "main", "sha": "a" * 40,
            "url": downstream["web_url"], "project": "g/sub/p"})
        for value in (-1, "42", None, True):
            with self.subTest(value=value):
                changed = {**downstream, "iid": value, "project_id": value}
                normalized = gitlab.bridge({**base, "pipeline": {"project_id": value},
                                            "downstream_pipeline": changed}, "gitlab.com")["downstream"]
                self.assertIsNone(normalized["iid"])
                self.assertIsNone(normalized["project_id"])
                self.assertIsNone(normalized["parent_project_id"])
        missing = gitlab.bridge({**base, "pipeline": {}, "downstream_pipeline": {"id": 7, "status": "manual"}},
                                "gitlab.com")["downstream"]
        self.assertEqual((missing["iid"], missing["project_id"], missing["parent_project_id"]), (None, None, None))
        self.assertEqual(missing["status"], "completed")
        for url in ("https://foreign.example/g/p/-/pipelines/7", "https://gitlab.com/a/../p/-/pipelines/7",
                    "https://gitlab.com/single/-/pipelines/7"):
            with self.subTest(url=url):
                self.assertEqual(gitlab.bridge({**base, "downstream_pipeline": {**downstream, "web_url": url}},
                                               "gitlab.com")["downstream"]["project"], "")
        self.assertEqual(gitlab.bridge({**base, "downstream_pipeline": {**downstream, "sha": "bad"}},
                                       "gitlab.com")["downstream"]["sha"], "")

    def test_pipeline_fields_and_attempt(self):
        running = gitlab.pipeline(PIPELINE)
        self.assertEqual(running, {"id": 7, "run_number": 3, "name": "merge request event", "display_title": "01234567", "sha": "",
                                   "head_branch": "main", "ref": "main", "source": "merge_request_event",
                                   "html_url": PIPELINE["web_url"],
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

    def test_pipeline_sha(self):
        for sha in ("a" * 40, "0" * 64):
            with self.subTest(sha=sha):
                result = gitlab.pipeline({**PIPELINE, "sha": sha})
                self.assertEqual(result["sha"], sha)
                self.assertEqual(result["display_title"], sha[:8])
        for sha in (None, 123, "a" * 7, "a" * 8, "A" * 40, "g" * 40):
            with self.subTest(sha=sha):
                self.assertEqual(gitlab.pipeline({**PIPELINE, "sha": sha})["sha"], "")
        self.assertEqual(gitlab.pipeline({key: value for key, value in PIPELINE.items() if key != "sha"})["sha"], "")


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
            self.assertEqual((result["nextPage"], result["total"]), (0, -1))
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

    def test_bridge_malformed_url_keeps_row(self):
        row = {"id": 5, "status": "success", "name": "deploy", "stage": "test",
               "downstream_pipeline": {"id": 7, "status": "running", "web_url": "https://[gitlab.com/x/-/pipelines/7"}}
        self.assertEqual(gitlab.bridge(row, "gitlab.com")["downstream"]["project"], "")

    def test_bridges_sorted_and_paginated(self):
        bridges = [{"id": 9, "status": "success", "downstream_pipeline": None},
                   {"id": 8, "status": "success", "downstream_pipeline": {"id": 12, "status": "running"}}]
        task = {"kind": "bridges", "repo": "g/p", "run": 7, "requestId": 1}
        with patch.object(gitlab, "request", return_value=reply(bridges, headers="X-Next-Page: 2\r\n")) as request:
            result = gitlab.read_page(task)
        self.assertEqual([row["id"] for row in result["data"]], [8, 9])
        self.assertEqual(result["data"][0]["downstream"]["status"], "in_progress")
        self.assertEqual(result["nextPage"], 2)
        self.assertEqual(request.call_args.args[0], "projects/g%2Fp/pipelines/7/bridges?per_page=100&page=1")

    def test_bridge_404_only_changes_bridge_error(self):
        for kind in ("bridges", "jobs", "run"):
            with self.subTest(kind=kind), patch.object(gitlab, "request", return_value=reply(
                    {"message": "private response"}, status="404 Not Found")):
                result = gitlab.read_page({"kind": kind, "repo": "g/p", "run": 7, "requestId": 1})
                self.assertEqual(result["errorType"], "route" if kind == "bridges" else "permission")
                self.assertEqual(result["error"], "GitLab has no trigger jobs route" if kind == "bridges"
                                 else "Project unavailable or read_api scope missing")
                self.assertNotIn("private response", json.dumps(result))

    def test_waiting_for_callback_job_is_not_completed(self):
        jobs = [{"id": 5, "name": "deploy", "stage": "deploy", "status": "waiting_for_callback"}]
        with patch.object(gitlab, "request", return_value=reply(jobs)):
            data = gitlab.read_page({"kind": "jobs", "repo": "g/p", "run": "7", "requestId": 1})["data"]
        self.assertNotEqual(data[0]["status"], "completed")

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
            self.assertEqual((reply["requestId"], reply["errorType"], reply["error"]), (1, "setup", "Install glab (GitLab CLI)"))

    def test_invalid_request_is_json_error(self):
        result = subprocess.run([sys.executable, "gitlab.py", "page", '{"kind":"url"}'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))


class LargeProjectTest(unittest.TestCase):
    def page(self, task, headers, body=None):
        with patch.object(gitlab, "request", return_value=reply(body if body is not None else [PIPELINE], headers=headers)):
            return gitlab.read_page({"repo": "g/p", "requestId": 1, "page": 1, **task})

    def test_unfinished_summary_reads_one_page_with_total(self):
        result = self.page({"kind": "summary", "status": "pending"}, "X-Total: 250\r\nX-Next-Page: 2\r\n")
        self.assertEqual((result["total"], result["nextPage"]), (250, 0))

    def test_total_unknown_above_ten_thousand(self):
        self.assertEqual(self.page({"kind": "activity"}, "X-Next-Page: 2\r\n")["total"], -1)
        self.assertEqual(self.page({"kind": "activity"}, "")["total"], 1)

    def test_malformed_total_is_network_error(self):
        self.assertEqual(self.page({"kind": "summary", "status": "running"}, "X-Total: x\r\n")["errorType"], "network")

    def test_recent_and_jobs_unchanged(self):
        self.assertNotIn("total", self.page({"kind": "summary", "status": "recent"}, "X-Total: 99\r\n"))
        jobs = self.page({"kind": "jobs", "run": "7"}, "X-Next-Page: 2\r\n", [{"id": 1, "name": "j", "stage": "s", "status": "success"}])
        self.assertEqual(jobs["nextPage"], 2)


class PlainTextTest(unittest.TestCase):
    def test_plain_strips_controls_keeps_joiners(self):
        self.assertEqual(gitlab.plain("a\u202eb\u0007c"), "abc")
        self.assertEqual(gitlab.plain("x\u200dy\u200cz"), "x\u200dy\u200cz")
        self.assertEqual(gitlab.plain("a\nb\tc"), "a b c")
        self.assertIsNone(gitlab.plain(None))

    def test_gitlab_text_is_plain(self):
        pipeline = gitlab.pipeline({**PIPELINE, "ref": "main\u202egnp.exe", "name": "CI\u0007"})
        self.assertEqual((pipeline["head_branch"], pipeline["name"]), ("maingnp.exe", "CI"))
        job = gitlab.job({"id": 1, "name": "unit\u202e", "stage": "te\nst", "status": "success"})
        self.assertEqual((job["name"], job["stage"]), ("unit", "te st"))
        project = gitlab.project({"path_with_namespace": "g/p", "description": "safe\u2066text"})
        self.assertEqual(project["description"], "safetext")


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
        self.assertEqual(json.loads(out.getvalue()), {"error": "GitLab request timed out", "errorType": "network"})

    def test_main_errors_carry_type_and_request(self):
        for request, side_effect, expected in [
                ('{"requestId": 7}', gitlab.DeadlineExceeded(), {"error": "GitLab request timed out", "errorType": "network", "requestId": 7}),
                ('{"requestId": 7}', ValueError("Invalid page number"), {"error": "Invalid page number", "errorType": "setup", "requestId": 7}),
                ('not json', None, None)]:
            out = io.StringIO()
            with self.subTest(request=request), patch.object(sys, "argv", ["gitlab.py", "page", request]), \
                    patch.object(gitlab, "read_page", side_effect=side_effect), contextlib.redirect_stdout(out):
                self.assertEqual(gitlab.main(), 1)
                reply = json.loads(out.getvalue())
                if expected:
                    self.assertEqual(reply, expected)
                else:
                    self.assertEqual(reply["errorType"], "setup")
                    self.assertNotIn("requestId", reply)

    def test_missing_glab_in_process_is_setup(self):
        with patch.object(gitlab, "request", side_effect=FileNotFoundError()):
            result = gitlab.read_page({"kind": "catalogue", "requestId": 1})
        self.assertEqual((result["errorType"], result["error"]), ("setup", "Install glab (GitLab CLI)"))


if __name__ == "__main__":
    unittest.main()
