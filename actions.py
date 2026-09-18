"""Read-only GitLab pipeline data, using glab's existing authentication."""
import argparse
import json
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote


# Unfinished statuses polled by a full summary; "running" is also the activity check.
PHASES = ("running", "pending", "created", "waiting_for_resource", "preparing")
IN_PROGRESS = ("running", "canceling")
QUEUED = ("created", "waiting_for_resource", "preparing", "pending")
SEGMENT = r"[A-Za-z0-9_.][A-Za-z0-9_.-]*"


class DeadlineExceeded(Exception):
    pass


def project_path(value):
    if not isinstance(value, str) or not re.fullmatch(SEGMENT + r"(?:/" + SEGMENT + r")+", value):
        raise ValueError("Project must be group/project")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("Invalid project")
    return value


def host_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?", value):
        raise ValueError("Invalid GitLab host")
    return value


def request(endpoint, host="gitlab.com"):
    child = subprocess.Popen(
        ["glab", "api", "--hostname", host_name(host), "--include", endpoint],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=25)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    return stdout, stderr, child.returncode


def page_endpoint(task):
    if not isinstance(task, dict) or task.get("kind") not in ("catalogue", "activity", "summary", "jobs", "run"):
        raise ValueError("Invalid page operation")
    number = task.get("page", 1)
    if type(number) is not int or number < 1 or number > 100000:
        raise ValueError("Invalid page number")
    if type(task.get("requestId")) is not int or task["requestId"] < 1:
        raise ValueError("Invalid request identity")
    host_name(task.get("host", "gitlab.com"))
    if task["kind"] == "catalogue":
        return f"projects?membership=true&per_page=100&page={number}"
    base = "projects/" + quote(project_path(task.get("repo")), safe="") + "/pipelines"
    if task["kind"] in ("jobs", "run"):
        run = str(task.get("run", ""))
        if not re.fullmatch(r"[0-9]+", run) or int(run) < 1:
            raise ValueError("Invalid pipeline ID")
        if task["kind"] == "run":
            return f"{base}/{run}"
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
    while text.startswith("HTTP/"):
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


# The panel's model and scheduler consume GitHub-shaped fields; conclusion keeps GitLab's status.
def pipeline(row):
    entry(row)
    status = state(row["status"])
    return {"id": row["id"], "run_number": row.get("iid"),
            "name": row.get("name") or str(row.get("source") or "").replace("_", " ") or "Pipeline",
            "display_title": str(row.get("sha") or "")[:8], "head_branch": row.get("ref") or "",
            "html_url": row.get("web_url") or "", "run_started_at": row.get("started_at") or row.get("created_at"),
            "completed_at": row.get("finished_at"), "updated_at": row.get("updated_at"),
            "status": status, "conclusion": row["status"],
            # A retried job changes a finished pipeline's updated_at: that is the rerun signal.
            "run_attempt": (row.get("updated_at") or 1) if status == "completed" else "active"}


def job(row):
    entry(row)
    return {"id": row["id"], "name": row.get("name") or "Job", "stage": str(row.get("stage") or ""),
            "status": state(row["status"]), "conclusion": row["status"], "allow_failure": bool(row.get("allow_failure")),
            "started_at": row.get("started_at"), "completed_at": row.get("finished_at"), "html_url": row.get("web_url") or ""}


def project(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid project entry")
    return {"repo": project_path(row.get("path_with_namespace")), "description": row.get("description") or "",
            "url": row.get("web_url") or "", "lastActivity": row.get("last_activity_at") or "",
            "archived": bool(row.get("archived")), "disabled": row.get("builds_access_level") == "disabled"}


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
        try:
            body = json.loads(raw_body) if raw_body.strip() else None
        except ValueError:
            if status < 400:
                raise
            body = None
        if status >= 400 or code:
            message = str(body.get("message", body.get("error", ""))) if isinstance(body, dict) else ""
            if status == 429 or result["remaining"] == 0 or result["retryAt"] or "rate limit" in message.lower():
                result.update(errorType="rate", error="GitLab rate limit")
            elif status == 401:
                result.update(errorType="auth", error="Authenticate with glab auth login")
            elif status in (403, 404):
                result.update(errorType="permission", error="Project unavailable or read_api scope missing")
            else:
                result.update(errorType="network", error="GitLab request failed")
            return result
        kind = task["kind"]
        if kind == "run":
            if not isinstance(body, dict) or str(body.get("id")) != str(task["run"]):
                raise ValueError("Invalid pipeline response")
            result["data"] = pipeline(body)
        else:
            if not isinstance(body, list):
                raise ValueError("Invalid list response")
            if kind == "catalogue":
                result["data"] = [project(row) for row in body]
            elif kind == "jobs":
                result["data"] = sorted((job(row) for row in body), key=lambda row: row["id"])
            else:
                result["data"] = [pipeline(row) for row in body]
            if not (kind == "summary" and task.get("status", "recent") == "recent"):
                result["nextPage"] = next_page(headers, task.get("page", 1))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        result.update(data=None, errorType="network", error="GitLab request timed out or returned invalid data")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("page",))
    parser.add_argument("request")
    args = parser.parse_args()
    # Bound the complete request, including glab start-up.
    def timed_out(*_):
        raise DeadlineExceeded()

    def cancelled(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGALRM, timed_out)
    signal.signal(signal.SIGTERM, cancelled)
    signal.alarm(90)
    try:
        data = read_page(json.loads(args.request))
        print(json.dumps(data))
    except (ValueError, DeadlineExceeded) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "GitLab request timed out"
        print(json.dumps({"error": message}))
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
