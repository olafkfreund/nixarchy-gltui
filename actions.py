"""Read-only GitHub Actions data, using gh's existing authentication."""
import argparse
import json
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, parse_qs


ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")


class DeadlineExceeded(Exception):
    pass


def repo_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Repository must be owner/name")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("Invalid repository")
    return value


def request(endpoint, include=False):
    child = subprocess.Popen(
        ["gh", "api", "--hostname", "github.com"] + (["--include"] if include else []) + [endpoint],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=25)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    return stdout, stderr, child.returncode


def api(endpoint):
    stdout, stderr, code = request(endpoint)
    if code:
        error = stderr.lower()
        if "rate limit" in error or "http 429" in error:
            raise RuntimeError("GitHub rate limit; refresh will back off")
        if "auth login" in error or "http 401" in error:
            raise RuntimeError("Authenticate with gh auth login")
        if "http 403" in error or "http 404" in error:
            raise RuntimeError("Repository unavailable or Actions read permission missing")
        raise RuntimeError("GitHub request failed; check connection and gh auth status")
    return json.loads(stdout)


def page_endpoint(task):
    if not isinstance(task, dict) or task.get("kind") not in ("catalogue", "activity", "summary", "jobs", "run"):
        raise ValueError("Invalid page operation")
    number = task.get("page", 1)
    if type(number) is not int or number < 1 or number > 100000:
        raise ValueError("Invalid page number")
    if type(task.get("requestId")) is not int or task["requestId"] < 1:
        raise ValueError("Invalid request identity")
    if task["kind"] == "catalogue":
        return f"user/repos?affiliation=owner,collaborator,organization_member&sort=pushed&direction=desc&per_page=100&page={number}"
    base = "repos/" + repo_name(task.get("repo")) + "/actions/runs"
    if task["kind"] in ("jobs", "run"):
        run = str(task.get("run", ""))
        if not re.fullmatch(r"[0-9]+", run) or int(run) < 1:
            raise ValueError("Invalid run ID")
        if task["kind"] == "run":
            return f"{base}/{run}"
        return f"{base}/{run}/jobs?filter=latest&per_page=100&page={number}"
    status = "in_progress" if task["kind"] == "activity" else task.get("status", "recent")
    if status == "recent":
        return f"{base}?per_page=10"
    if status not in ACTIVE:
        raise ValueError("Invalid workflow status")
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


def next_page(endpoint, headers):
    for link in headers.get("link", "").split(","):
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not match:
            continue
        target = urlsplit(match[1])
        source = urlsplit("https://api.github.com/" + endpoint)
        query, expected = parse_qs(target.query), parse_qs(source.query)
        page = query.pop("page", [])
        previous = expected.pop("page", ["1"])
        if (target.scheme != "https" or target.netloc != "api.github.com"
                or target.path != source.path or target.fragment or query != expected
                or len(page) != 1 or not page[0].isdigit() or int(page[0]) != int(previous[0]) + 1):
            raise ValueError("Invalid pagination link")
        return int(page[0])
    return 0


def read_page(task):
    endpoint = page_endpoint(task)
    result = {"requestId": task["requestId"], "httpStatus": 0, "nextPage": 0,
              "data": None, "error": "", "errorType": "", "retryAt": 0,
              "remaining": None, "resetAt": 0}
    try:
        stdout, stderr, code = request(endpoint, include=True)
        if not stdout.strip() and "auth login" in stderr.lower():
            result.update(errorType="auth", error="Authenticate with gh auth login")
            return result
        status, headers, raw_body = http_reply(stdout)
        result["httpStatus"] = status
        if headers.get("x-ratelimit-remaining", "").isdigit():
            result["remaining"] = int(headers["x-ratelimit-remaining"])
        if headers.get("x-ratelimit-reset", "").isdigit():
            result["resetAt"] = int(headers["x-ratelimit-reset"]) * 1000
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
        result["data"] = body
        if status >= 400 or code:
            message = str(body.get("message", "")) if isinstance(body, dict) else ""
            if status == 429 or result["remaining"] == 0 or result["retryAt"] or "rate limit" in message.lower() or "secondary rate" in message.lower():
                result.update(errorType="rate", error="GitHub rate limit")
            elif status == 401:
                result.update(errorType="auth", error="Authenticate with gh auth login")
            elif status in (403, 404):
                result.update(errorType="permission", error="Resource unavailable or Actions read permission missing")
            else:
                result.update(errorType="network", error="GitHub request failed")
            return result
        kind = task["kind"]
        if kind == "catalogue":
            if not isinstance(body, list):
                raise ValueError("Invalid repository response")
            if any(not isinstance(row, dict) for row in body):
                raise ValueError("Invalid repository entry")
            result["data"] = [{"repo": repo_name(row["full_name"]), "description": row.get("description") or "",
                               "archived": bool(row.get("archived")), "disabled": bool(row.get("disabled"))} for row in body]
        elif kind == "run":
            if not isinstance(body, dict) or str(body.get("id")) != str(task["run"]) or "status" not in body:
                raise ValueError("Invalid run response")
        else:
            key = "jobs" if kind == "jobs" else "workflow_runs"
            if not isinstance(body, dict) or not isinstance(body.get(key), list):
                raise ValueError("Invalid workflow response")
            if any(not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1 or not isinstance(row.get("status"), str) for row in body[key]):
                raise ValueError("Invalid workflow entry")
            if kind == "jobs" and any(not isinstance(row.get("steps", []), list) for row in body[key]):
                raise ValueError("Invalid job steps")
            result["data"] = body[key]
        if kind != "run" and not (kind == "summary" and task.get("status", "recent") == "recent"):
            result["nextPage"] = next_page(endpoint, headers)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        result.update(errorType="network", error="GitHub request timed out or returned invalid data")
    return result


def pages(endpoint, key):
    page = 1
    while True:
        separator = "&" if "?" in endpoint else "?"
        data = api(f"{endpoint}{separator}per_page=100&page={page}")
        rows = data[key]
        if not isinstance(rows, list):
            raise ValueError("Unexpected GitHub response")
        yield from rows
        if len(rows) < 100:
            break
        page += 1


def runs(repo):
    base = f"repos/{repo_name(repo)}/actions/runs"
    found = {}
    for status in ACTIVE:
        for run in pages(f"{base}?status={status}", "workflow_runs"):
            found[run["id"]] = run
    # Include recent completions; querying them last resolves completion races.
    for run in api(f"{base}?per_page=10")["workflow_runs"]:
        found[run["id"]] = run
    return sorted(found.values(), key=lambda run: (run["status"] == "completed", -run["id"]))


def repositories_page(page):
    if not page.isdigit() or int(page) < 1:
        raise ValueError("Repository page must be a positive number")
    rows = api("user/repos?affiliation=owner,collaborator,organization_member"
               f"&sort=pushed&direction=desc&per_page=100&page={page}")
    if not isinstance(rows, list):
        raise ValueError("Unexpected repository response")
    return {"repos": [{"repo": repo_name(row["full_name"]),
                       "description": row.get("description") or "",
                       "archived": row.get("archived", False),
                       "disabled": row.get("disabled", False)} for row in rows],
            "nextPage": int(page) + 1 if len(rows) == 100 else 0}


def activity(repo):
    repo = repo_name(repo)
    running = list(pages(f"repos/{repo}/actions/runs?status=in_progress", "workflow_runs"))
    return {"repo": repo, "runs": running, "active": len(running)}


def summary(repos):
    result = []
    for repo in dict.fromkeys(repo_name(value) for value in repos):
        try:
            result.append({"repo": repo, "runs": runs(repo), "error": ""})
        except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else "Unable to read GitHub workflow data"
            result.append({"repo": repo, "error": message})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("summary", "jobs", "repositories", "activity", "page"))
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    # Bound the complete request, including all pages/repositories.
    def timed_out(*_):
        raise DeadlineExceeded()

    def cancelled(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGALRM, timed_out)
    signal.signal(signal.SIGTERM, cancelled)
    signal.alarm(90)
    try:
        if args.mode == "page":
            if len(args.targets) != 1:
                raise ValueError("page requires one JSON request")
            data = read_page(json.loads(args.targets[0]))
        elif args.mode == "repositories":
            if len(args.targets) != 1:
                raise ValueError("repositories requires one page number")
            data = repositories_page(args.targets[0])
        elif args.mode == "activity":
            if len(args.targets) != 1:
                raise ValueError("activity requires one repository")
            data = activity(args.targets[0])
        elif args.mode == "summary":
            data = {"repos": summary(args.targets)}
        else:
            if len(args.targets) != 2 or not args.targets[1].isdigit():
                raise ValueError("jobs requires owner/repo and numeric run ID")
            repo, run = repo_name(args.targets[0]), args.targets[1]
            data = {"jobs": list(pages(f"repos/{repo}/actions/runs/{run}/jobs?filter=latest", "jobs"))}
        data["updated"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(data))
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired, DeadlineExceeded) as exc:
        message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "GitHub request timed out or returned invalid data"
        print(json.dumps({"error": message}))
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
