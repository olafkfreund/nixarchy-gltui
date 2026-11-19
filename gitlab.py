"""GitLab pipeline data and a closed set of pipeline and job actions, using glab's existing authentication."""
import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlsplit


# Unfinished statuses polled by a full summary; "running" is also the activity check.
PHASES = ("running", "pending", "created", "waiting_for_resource", "preparing")
# ZWNJ and ZWJ are Cf but kept: emoji sequences and several scripts need them, and they cannot reorder text (#15).
JOINERS = "\u200c\u200d"
IN_PROGRESS = ("running", "canceling")
QUEUED = ("created", "waiting_for_resource", "preparing", "pending", "waiting_for_callback")
SEGMENT = r"[A-Za-z0-9_.][A-Za-z0-9_.-]*"
ACTIONS = {"retry-pipeline": (False, "retry"), "cancel-pipeline": (False, "cancel"),
           "retry-job": (True, "retry"), "cancel-job": (True, "cancel"),
           "play-job": (True, "play"), "new-pipeline": (False, "")}


class DeadlineExceeded(Exception):
    pass


def project_path(value):
    if not isinstance(value, str) or not re.fullmatch(SEGMENT + r"(?:/" + SEGMENT + r")+", value):
        raise ValueError("Project must be group/project")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("Invalid project")
    return value


def state_path():
    base = os.environ.get("XDG_STATE_HOME", "")
    if not os.path.isabs(base):
        base = os.path.expanduser("~/.local/state")
    return Path(base) / "omarchy-gitlab-pipelines" / "pinned.json"


def read_state(path):
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return {"version": 1, "hosts": {}}
    except OSError as exc:
        raise ValueError("Cannot read pinned.json") from exc
    except ValueError as exc:
        raise ValueError("pinned.json is not valid") from exc
    if (not isinstance(state, dict) or state.get("version") != 1 or
            not isinstance(state.get("hosts"), dict) or
            any(not isinstance(value, list) for value in state["hosts"].values())):
        raise ValueError("pinned.json is not valid")
    return state


def pins(task):
    if not isinstance(task, dict):
        raise ValueError("Invalid pins")
    host = host_name(task.get("host")).lower()
    path = state_path()
    if "save" not in task:
        state = read_state(path)
        valid = []
        for name in state["hosts"].get(host, []):
            try:
                valid.append(project_path(name))
            except ValueError:
                pass
        return {"pins": valid}
    if not isinstance(task["save"], list):
        raise ValueError("Invalid pins")
    names = []
    for name in task["save"]:
        try:
            project_path(name)
        except ValueError as exc:
            raise ValueError("Invalid pins") from exc
        if name not in names:
            names.append(name)
    state = read_state(path)
    state["hosts"][host] = names
    tmp = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pinned-", suffix=".json")
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(json.dumps(state, indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    except Exception as exc:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise ValueError("Cannot write pinned.json") from exc
        raise
    return {"pins": names}


def host_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?", value):
        raise ValueError("Invalid GitLab host")
    return value


def request(endpoint, host="gitlab.com", method=None):
    child = subprocess.Popen(
        ["glab", "api", "--hostname", host_name(host), "--include"] +
        (["--method", method] if method else []) + [endpoint],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=25)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    return stdout, stderr, child.returncode


def numeric_id(value, label):
    number = str(value)
    if not re.fullmatch(r"[0-9]+", number) or int(number) < 1:
        raise ValueError(f"Invalid {label} ID")
    return number


def page_endpoint(task):
    if not isinstance(task, dict) or task.get("kind") not in ("catalogue", "activity", "summary", "jobs", "bridges", "run", "mrs", "mr"):
        raise ValueError("Invalid page operation")
    number = task.get("page", 1)
    if type(number) is not int or number < 1 or number > 100000:
        raise ValueError("Invalid page number")
    if type(task.get("requestId")) is not int or task["requestId"] < 1:
        raise ValueError("Invalid request identity")
    host_name(task.get("host", "gitlab.com"))
    if task["kind"] == "catalogue":
        return f"projects?membership=true&per_page=100&page={number}"
    if task["kind"] == "mrs":
        if number != 1:
            raise ValueError("Invalid page number")
        return "merge_requests?scope=created_by_me&state=opened&order_by=updated_at&sort=desc&per_page=50"
    if task["kind"] == "mr":
        return f"projects/{numeric_id(task.get('project'), 'project')}/merge_requests/{numeric_id(task.get('iid'), 'merge request')}"
    base = "projects/" + quote(project_path(task.get("repo")), safe="") + "/pipelines"
    if task["kind"] in ("jobs", "bridges", "run"):
        run = numeric_id(task.get("run", ""), "pipeline")
        if task["kind"] == "run":
            return f"{base}/{run}"
        if task["kind"] == "bridges":
            route = task.get("route", "bridges")
            if route not in ("bridges", "trigger_jobs"):
                raise ValueError("Invalid trigger jobs route")
            return f"{base}/{run}/{route}?per_page=100&page={number}"
        return f"{base}/{run}/jobs?include_retried=false&per_page=100&page={number}"
    status = "running" if task["kind"] == "activity" else task.get("status", "recent")
    if status == "recent":
        return f"{base}?per_page=10"
    if status not in PHASES:
        raise ValueError("Invalid pipeline status")
    return f"{base}?status={status}&per_page=100&page={number}"


def http_reply(stdout):
    text = stdout.replace("\r\n", "\n")
    headers = {}
    status = None
    while text.startswith("HTTP/") and (status is None or status < 200):
        head, separator, text = text.partition("\n\n")
        if not separator:
            raise ValueError("Malformed HTTP response")
        lines = head.splitlines()
        match = re.fullmatch(r"HTTP/\S+ (\d{3})(?: .*)?", lines[0])
        if not match:
            raise ValueError("Malformed HTTP status")
        status = int(match[1])
        headers = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if separator:
                headers[name.lower()] = value.strip()
    if status is None:
        raise ValueError("Missing HTTP response")
    return status, headers, text


def limits(headers, result):
    if headers.get("ratelimit-remaining", "").isdigit():
        result["remaining"] = int(headers["ratelimit-remaining"])
    if headers.get("ratelimit-reset", "").isdigit():
        result["resetAt"] = int(headers["ratelimit-reset"]) * 1000
    retry = headers.get("retry-after", "")
    if retry:
        try:
            result["retryAt"] = ((datetime.now(timezone.utc).timestamp() + int(retry)) * 1000
                                 if retry.isdigit() else parsedate_to_datetime(retry).timestamp() * 1000)
        except (ValueError, TypeError, OverflowError):
            pass


def next_page(headers, page):
    value = headers.get("x-next-page", "")
    if not value:
        return 0
    if not value.isdigit() or int(value) != page + 1:
        raise ValueError("Invalid pagination header")
    return int(value)


def state(status):
    if status in IN_PROGRESS:
        return "in_progress"
    return "queued" if status in QUEUED else "completed"


def entry(row):
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1 or not isinstance(row.get("status"), str):
        raise ValueError("Invalid pipeline entry")
    return row


# Field names are shared with the panel model and scheduler; conclusion keeps GitLab's status.
def plain(value):
    """Display text from GitLab: line breaks and tabs become spaces, other Cc/Cf characters go (#15, ghtui #32)."""
    if not isinstance(value, str):
        return value
    text = " ".join(value.replace("\t", " ").splitlines())
    return "".join(c for c in text if c in JOINERS or unicodedata.category(c) not in ("Cc", "Cf"))


def valid_ref(value):
    return (isinstance(value, str) and 1 <= len(value) <= 255 and
            not value.startswith("refs/merge-requests/") and
            all(ord(char) >= 32 and ord(char) != 127 for char in value))


def pipeline_total(headers, count):
    """X-Total, or -1 ("more, count unknown") when GitLab omits it above 10,000 but X-Next-Page is set."""
    value = headers.get("x-total")
    if value is None:
        return -1 if headers.get("x-next-page", "") else count
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Invalid pipeline total")
    return int(value)


def pipeline(row):
    entry(row)
    status = state(row["status"])
    return {"id": row["id"], "run_number": row.get("iid"),
            "name": plain(row.get("name") or str(row.get("source") or "").replace("_", " ") or "Pipeline"),
            "display_title": str(row.get("sha") or "")[:8],
            "sha": row["sha"] if isinstance(row.get("sha"), str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", row["sha"]) else "",
            "head_branch": plain(row.get("ref") or ""),
            "ref": row.get("ref") if valid_ref(row.get("ref")) else "",
            "source": row.get("source") if isinstance(row.get("source"), str) and re.fullmatch(r"[a-z_]{1,40}", row["source"]) else "",
            "html_url": row.get("web_url") or "", "run_started_at": row.get("started_at") or row.get("created_at"),
            "completed_at": row.get("finished_at"), "updated_at": row.get("updated_at"),
            "status": status, "conclusion": row["status"],
            # A retried job changes a finished pipeline's updated_at: that is the rerun signal.
            "run_attempt": (row.get("updated_at") or 1) if status == "completed" else "active"}


def merge_request(row):
    if not isinstance(row, dict) or any(type(row.get(key)) is not int or row[key] < 1 for key in ("id", "iid", "project_id")):
        raise ValueError("Invalid merge request entry")
    project = ""
    reference = row.get("references")
    full = reference.get("full") if isinstance(reference, dict) else None
    if isinstance(full, str) and full.endswith(f"!{row['iid']}"):
        try:
            project = project_path(full[:-(len(str(row["iid"])) + 1)])
        except ValueError:
            pass
    if not project and isinstance(row.get("web_url"), str):
        try:
            path, separator, _ = urlsplit(row["web_url"]).path.lstrip("/").partition("/-/")
            if separator:
                project = project_path(path)
        except ValueError:
            pass
    return {"id": row["id"], "iid": row["iid"], "project_id": row["project_id"],
            "project": project, "title": plain(row.get("title") or ""),
            "source_branch": plain(row.get("source_branch") or ""),
            "draft": bool(row.get("draft") or row.get("work_in_progress")),
            "web_url": row.get("web_url") or "", "updated_at": row.get("updated_at")}


def mr_detail(row):
    if not isinstance(row, dict) or any(type(row.get(key)) is not int or row[key] < 1 for key in ("iid", "project_id")):
        raise ValueError("Invalid merge request detail")
    result = {"iid": row["iid"], "project_id": row["project_id"], "pipeline": None,
              "pipelineState": "hidden" if "head_pipeline" not in row else "none"}
    if row.get("head_pipeline") is not None:
        head = row["head_pipeline"]
        if not isinstance(head, dict) or type(head.get("project_id")) is not int or head["project_id"] < 1:
            raise ValueError("Invalid head pipeline project ID")
        result["pipeline"] = {**pipeline(head), "project_id": head["project_id"]}
        result["pipelineState"] = "ok"
    return result


def job(row):
    entry(row)
    def number(value):
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None

    return {"id": row["id"], "name": plain(row.get("name") or "Job"), "stage": plain(str(row.get("stage") or "")),
            "status": state(row["status"]), "conclusion": row["status"], "allow_failure": bool(row.get("allow_failure")),
            "started_at": row.get("started_at"), "completed_at": row.get("finished_at"), "html_url": row.get("web_url") or "",
            "failure_reason": plain(row["failure_reason"]) if isinstance(row.get("failure_reason"), str) else "",
            "duration": number(row.get("duration")), "queued_duration": number(row.get("queued_duration"))}


def bridge(row, host):
    result = job(row)
    downstream = row.get("downstream_pipeline")
    if not isinstance(downstream, dict):
        result["downstream"] = None
        return result

    def non_negative_int(value):
        return value if type(value) is int and value >= 0 else None

    parent = row.get("pipeline")
    url = downstream.get("web_url") or ""
    path = ""
    if isinstance(url, str):
        try:
            parsed = urlsplit(url)
        except ValueError:
            parsed = None
        if parsed and parsed.netloc.lower() == host.lower():
            candidate, separator, _ = parsed.path.lstrip("/").partition("/-/pipelines/")
            if separator:
                try:
                    path = project_path(candidate)
                except ValueError:
                    pass
    sha = downstream.get("sha")
    result["downstream"] = {
        "id": downstream.get("id"), "iid": non_negative_int(downstream.get("iid")),
        "project_id": non_negative_int(downstream.get("project_id")),
        "parent_project_id": non_negative_int(parent.get("project_id")) if isinstance(parent, dict) else None,
        "status": state(downstream.get("status")), "conclusion": downstream.get("status"),
        "ref": plain(downstream.get("ref") or ""),
        "sha": sha if isinstance(sha, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha) else "",
        "url": url, "project": path}
    return result


def project(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid project entry")
    if type(row.get("id")) is not int or row["id"] < 1:
        raise ValueError("Invalid project ID")
    return {"id": row["id"], "repo": project_path(row.get("path_with_namespace")), "description": plain(row.get("description") or ""),
            "url": row.get("web_url") or "", "lastActivity": row.get("last_activity_at") or "",
            "archived": bool(row.get("archived")), "disabled": row.get("builds_access_level") == "disabled"}


def write_endpoint(task):
    if not isinstance(task, dict) or task.get("action") not in ACTIONS:
        raise ValueError("Invalid action")
    if type(task.get("requestId")) is not int or task["requestId"] < 1:
        raise ValueError("Invalid request identity")
    host_name(task.get("host", "gitlab.com"))
    action = task["action"]
    base = "projects/" + quote(project_path(task.get("repo")), safe="")
    if action == "new-pipeline":
        ref = task.get("ref")
        if not valid_ref(ref) or task.get("source") == "merge_request_event":
            raise ValueError("Invalid pipeline ref")
        return base + "/pipeline?ref=" + quote(ref, safe="")
    if ACTIONS[action][0]:
        return base + "/jobs/" + numeric_id(task.get("job"), "job") + "/" + ACTIONS[action][1]
    return base + "/pipelines/" + numeric_id(task.get("run"), "pipeline") + "/" + ACTIONS[action][1]


def actions_enabled(host):
    try:
        config = json.loads((Path(os.environ["HOME"]) / ".config/omarchy/shell.json").read_text())
        entries = config.get("plugins", [])
        return isinstance(entries, list) and any(
            isinstance(entry, dict) and entry.get("id") == "olafkfreund.gitlab-pipelines" and
            entry.get("actions") is True and
            (entry.get("host") if isinstance(entry.get("host"), str) else "gitlab.com").lower() == host.lower() for entry in entries)
    except (KeyError, OSError, ValueError, TypeError, AttributeError):
        return False


def message_text(body):
    def strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [part for item in value.values() for part in strings(item)]
        if isinstance(value, list):
            return [part for item in value for part in strings(item)]
        return []

    value = body.get("message", body.get("error", "")) if isinstance(body, dict) else body
    return plain("; ".join(strings(value)))[:120]


def write_action(task):
    endpoint = write_endpoint(task)
    host = task.get("host", "gitlab.com")
    result = {"requestId": task["requestId"], "action": task["action"], "httpStatus": 0,
              "ok": False, "error": "", "errorType": "", "retryAt": 0,
              "remaining": None, "resetAt": 0, "created": None}
    if not actions_enabled(host):
        result.update(errorType="disabled", error="Actions are off in shell.json")
        return result
    try:
        stdout, stderr, code = request(endpoint, host, "POST")
        if not stdout.strip() and "auth login" in stderr.lower():
            result.update(errorType="auth", error="Authenticate with glab auth login")
            return result
        status, headers, raw_body = http_reply(stdout)
        result["httpStatus"] = status
        limits(headers, result)
        try:
            body = json.loads(raw_body) if raw_body.strip() else None
        except ValueError:
            # A proxy's HTML or text error page still has a status worth classifying (a bare 429 must pause polling).
            if 200 <= status < 300:
                raise
            body = None
        message = message_text(body)
        if 200 <= status < 300:
            result["ok"] = True
            if task["action"] in ("new-pipeline", "retry-job") and isinstance(body, dict) and ("id" in body or "iid" in body):
                result["created"] = {"id": body.get("id"), "iid": body.get("iid")}
        elif status == 429 or result["remaining"] == 0 or result["retryAt"] or "rate limit" in message.lower():
            result.update(errorType="rate", error="GitLab rate limit")
        elif status == 401:
            result.update(errorType="auth", error="Authenticate with glab auth login")
        elif status == 403 and isinstance(body, dict) and any(
                "insufficient_scope" in str(body.get(key, "")).lower() for key in ("error", "message")):
            result.update(errorType="scope", error="Needs a token with the api scope")
        elif 400 <= status < 500:
            result.update(errorType="refused", error="GitLab refused: " + (message or f"HTTP {status}"))
        elif 300 <= status < 400:
            result.update(errorType="refused", error="GitLab redirected the request; the project may have moved")
        else:
            result.update(errorType="unknown", error="Outcome unknown; check GitLab before retrying")
    except FileNotFoundError:
        result.update(errorType="setup", error="Install glab (GitLab CLI)")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        result.update(errorType="unknown", error="Outcome unknown; check GitLab before retrying")
    return result


def read_page(task):
    endpoint = page_endpoint(task)
    result = {"requestId": task["requestId"], "httpStatus": 0, "nextPage": 0,
              "data": None, "error": "", "errorType": "", "retryAt": 0,
              "remaining": None, "resetAt": 0}
    try:
        stdout, stderr, code = request(endpoint, task.get("host", "gitlab.com"))
        if not stdout.strip() and "auth login" in stderr.lower():
            result.update(errorType="auth", error="Authenticate with glab auth login")
            return result
        status, headers, raw_body = http_reply(stdout)
        result["httpStatus"] = status
        limits(headers, result)
        try:
            body = json.loads(raw_body) if raw_body.strip() else None
        except ValueError:
            if status < 300:
                raise
            body = None
        if status >= 300 or code:
            message = str(body.get("message", body.get("error", ""))) if isinstance(body, dict) else ""
            if status == 429 or result["remaining"] == 0 or result["retryAt"] or "rate limit" in message.lower():
                result.update(errorType="rate", error="GitLab rate limit")
            elif status == 401:
                result.update(errorType="auth", error="Authenticate with glab auth login")
            elif status == 404 and task["kind"] == "bridges":
                result.update(errorType="route", error="GitLab has no trigger jobs route")
            elif status in (403, 404) and task["kind"] in ("mrs", "mr"):
                result.update(errorType="permission", error="Merge request unavailable")
            elif status in (403, 404):
                result.update(errorType="permission", error="Project unavailable or read_api scope missing")
            elif 300 <= status < 400:
                result.update(errorType="network", error="GitLab redirected the request; the project may have moved")
            else:
                result.update(errorType="network", error="GitLab request failed")
            return result
        kind = task["kind"]
        if kind == "mr":
            if not isinstance(body, dict) or str(body.get("iid")) != str(task["iid"]):
                raise ValueError("Invalid merge request response")
            result["data"] = mr_detail(body)
        elif kind == "run":
            if not isinstance(body, dict) or str(body.get("id")) != str(task["run"]):
                raise ValueError("Invalid pipeline response")
            result["data"] = pipeline(body)
        else:
            if not isinstance(body, list):
                raise ValueError("Invalid list response")
            if kind == "catalogue":
                result["data"] = [project(row) for row in body]
            elif kind == "mrs":
                result["data"] = [merge_request(row) for row in body]
            elif kind == "jobs":
                result["data"] = sorted((job(row) for row in body), key=lambda row: row["id"])
            elif kind == "bridges":
                result["data"] = sorted((bridge(row, task.get("host", "gitlab.com")) for row in body), key=lambda row: row["id"])
            else:
                result["data"] = [pipeline(row) for row in body]
            if kind == "mrs":
                result["total"] = pipeline_total(headers, len(body))
            elif kind in ("catalogue", "jobs", "bridges"):
                result["nextPage"] = next_page(headers, task.get("page", 1))
            elif kind == "activity" or task.get("status") in PHASES:
                # One page per unfinished status (#15, ghtui #30); X-Total says how many were left out.
                result["total"] = pipeline_total(headers, len(body))
    except FileNotFoundError:
        # ponytail: only Popen(["glab", ...]) raises this; PermissionError stays "network"
        result.update(data=None, errorType="setup", error="Install glab (GitLab CLI)")
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        result.update(data=None, errorType="network", error="GitLab request timed out or returned invalid data")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("page", "pins", "act"))
    parser.add_argument("request")
    args = parser.parse_args()
    if args.mode == "pins":
        try:
            print(json.dumps(pins(json.loads(args.request))))
            return 0
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
    # Bound the complete request, including glab start-up.
    def timed_out(*_):
        raise DeadlineExceeded()

    def cancelled(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGALRM, timed_out)
    signal.signal(signal.SIGTERM, cancelled)
    signal.alarm(90)
    task = None
    try:
        task = json.loads(args.request)
        data = write_action(task) if args.mode == "act" else read_page(task)
        print(json.dumps(data))
    except (ValueError, DeadlineExceeded) as exc:
        message = str(exc) if isinstance(exc, ValueError) else ("Outcome unknown; check GitLab before retrying"
                                                              if args.mode == "act" else "GitLab request timed out")
        error = {"error": message, "errorType": ("unknown" if args.mode == "act" else "network")
                 if isinstance(exc, DeadlineExceeded) else "setup"}
        if isinstance(task, dict) and type(task.get("requestId")) is int and task["requestId"] > 0:
            error["requestId"] = task["requestId"]
        print(json.dumps(error))
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
