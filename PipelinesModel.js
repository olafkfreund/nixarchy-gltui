// Fixed text only: stderr can hold paths and tracebacks, so it goes to the log, never the panel.
function reply(stdout, code, requestId) {
    if (stdout.trim()) return stdout;
    return JSON.stringify({requestId: requestId, errorType: "setup",
        error: code === 127 ? "python3 not found" : "GitLab helper failed (exit " + code + "); see the shell log"});
}

// The trailing slash pins the host; no whitespace or Cc control may reach xdg-open's helpers (#15, ghtui #32).
function browsable(url, host) {
    if (typeof url !== "string" || typeof host !== "string") return false;
    var pinned = host.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("^https://" + pinned + "/[^\\s\\x00-\\x1f\\x7f-\\x9f]+$").test(url);
}

function state(item) {
    return item.awaitingFinal ? "awaiting final status" : item.lookupError ? "unavailable" : item.conclusion || item.status || "unknown";
}

function group(status) {
    switch (status) {
    case "running": case "canceling": return "running";
    case "success": return "success";
    case "failed": case "error": case "unavailable": return "failed";
    case "allowed to fail": return "allowed";
    case "manual": return "manual";
    case "scheduled": return "scheduled";
    case "created": case "pending": case "waiting_for_resource": case "preparing":
    case "waiting_for_callback": case "queued": case "awaiting final status": return "queued";
    case "skipped": return "skipped";
    case "canceled": return "canceled";
    case "neutral": return "neutral";
    default: return "unknown";
    }
}

function icon(status) {
    return {running: "●", success: "✓", failed: "✕", allowed: "!", manual: "▶",
        scheduled: "◷", queued: "◌", skipped: "−", canceled: "⊘", neutral: "·", unknown: "○"}[group(status)];
}

function some(jobs, statuses) {
    return jobs.some(function(job) { return statuses.indexOf(job.conclusion) >= 0; });
}

// Stage status follows GitLab: activity first, then blocking failures.
function stageStatus(jobs) {
    if (some(jobs, ["running", "canceling"])) return "running";
    if (jobs.some(function(job) { return job.conclusion === "failed" && !job.allow_failure; })) return "failed";
    if (some(jobs, ["created", "pending", "preparing", "waiting_for_resource", "waiting_for_callback"])) return "pending";
    if (some(jobs, ["canceled"])) return "canceled";
    if (some(jobs, ["success"]) || jobs.some(function(job) { return job.conclusion === "failed" && job.allow_failure; })) return "success";
    return jobs.length && jobs.every(function(job) { return job.conclusion === "manual"; }) ? "manual" : "skipped";
}

function stages(jobs) {
    var order = [], byName = Object.create(null);
    jobs.forEach(function(job) {
        if (!byName[job.stage]) { byName[job.stage] = []; order.push(job.stage); }
        byName[job.stage].push(job);
    });
    return order.map(function(name) {
        var list = byName[name];
        var starts = list.map(function(job) { return job.started_at; }).filter(Boolean).sort();
        var ends = list.map(function(job) { return job.completed_at; }).filter(Boolean).sort();
        var done = list.every(function(job) { return job.status === "completed"; });
        return {name: name || "Jobs", jobs: list, status: stageStatus(list),
            span: {started_at: starts[0], completed_at: done ? ends[ends.length - 1] : "", status: done ? "completed" : "in_progress"}};
    });
}

function duration(item, now) {
    var start = Date.parse(item.started_at || item.run_started_at || "");
    if (!isFinite(start)) return "";
    var end = Date.parse(item.completed_at || (item.status === "completed" ? item.updated_at : "") || "");
    return seconds(Math.max(0, Math.floor(((isFinite(end) ? end : now) - start) / 1000)));
}

function seconds(n) {
    if (n >= 3600) return Math.floor(n / 3600) + "h " + Math.floor(n % 3600 / 60) + "m";
    return n >= 60 ? Math.floor(n / 60) + "m " + n % 60 + "s" : n + "s";
}

function ago(iso, now) {
    var time = Date.parse(iso || "");
    if (!isFinite(time)) return "";
    var s = Math.floor((now - time) / 1000);
    if (s < 10) return "just now";
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
}

function shortRef(ref) {
    var match = /^refs\/merge-requests\/(\d+)\/(head|merge|train)$/.exec(ref);
    return match ? "!" + match[1] : ref;
}

function reasonText(code) {
    var names = {script_failure: "script failure", runner_system_failure: "runner error",
        stuck_or_timeout_failure: "timed out", job_execution_timeout: "timed out", api_failure: "API error",
        missing_dependency_failure: "missing dependency", runner_unsupported: "runner unsupported",
        scheduler_failure: "scheduler error", data_integrity_failure: "data error", unknown_failure: "unknown failure"};
    return Object.prototype.hasOwnProperty.call(names, code) ? names[code] : (code ? code.replace(/_/g, " ") : "");
}

function infoText(row, now) {
    if (row.kind === "repo") {
        var checked = row.info && /running$/.test(row.info) ? ago(row.checked, now) : "";
        return row.info + (checked ? " · checked " + checked : "");
    }
    var live = duration({started_at: row.started, completed_at: row.ended,
        status: row.ended ? "completed" : ""}, now);
    var parts = [row.status];
    if (row.kind === "run") parts.push(live, ago(row.finished, now));
    else if (row.kind === "stage") parts.push(row.done + "/" + row.total + " jobs", live);
    else if (row.kind === "job") {
        if (row.status === "failed" || row.status === "allowed to fail") parts.push(reasonText(row.reason));
        parts.push(row.complete && typeof row.serverDuration === "number" ? seconds(Math.round(row.serverDuration)) : live);
        if (row.queued > 0) parts.push("queued " + seconds(Math.round(row.queued)));
        parts.push(ago(row.finished, now));
    } else return row.status + (row.info ? " · " + row.info : "");
    return parts.filter(Boolean).join(" · ");
}

function subtitleText(row, now) {
    var fetched = row.kind === "run" ? ago(row.fetched, now) : "";
    return (row.subtitle || "") + (fetched ? " · jobs fetched " + fetched : "");
}

function repoMatches(repo, query) {
    return (repo.repo + " " + (repo.description || "")).toLowerCase().indexOf(query) >= 0;
}

function runMatches(run, query) {
    return [run.name, run.display_title, run.head_branch, shortRef(run.head_branch), state(run)].join(" ").toLowerCase().indexOf(query) >= 0;
}

function autoOpen(repos, filter) {
    var result = {};
    var query = filter.toLowerCase();
    if (!query) return result;
    repos.forEach(function(repo) {
        if (!repoMatches(repo, query) && (repo.runs || []).some(function(run) { return runMatches(run, query); }))
            result["repo:" + repo.repo] = true;
    });
    return result;
}

function merge(expanded, auto, collapsed) {
    var result = {};
    Object.keys(expanded).forEach(function(key) { if (Object.prototype.hasOwnProperty.call(expanded, key)) result[key] = expanded[key]; });
    Object.keys(auto).forEach(function(key) { if (Object.prototype.hasOwnProperty.call(auto, key)) result[key] = auto[key]; });
    Object.keys(collapsed).forEach(function(key) { if (Object.prototype.hasOwnProperty.call(collapsed, key)) delete result[key]; });
    return result;
}

function rows(repos, expanded, details, filter, now) {
    var result = [];
    var query = filter.toLowerCase();
    repos.slice().sort(function(a, b) { return (b.active || 0) - (a.active || 0); }).forEach(function(repo) {
        var repoMatch = repoMatches(repo, query);
        var runs = (repo.runs || []).filter(function(run) {
            return repoMatch || runMatches(run, query);
        });
        if (query && !repoMatch && !runs.length) return;
        var active = repo.active === undefined ? (repo.runs || []).filter(function(run) { return run.status === "in_progress"; }).length : repo.active;
        var repoKey = "repo:" + repo.repo;
        result.push({key: repoKey, parent: "", kind: "repo", depth: 0, title: repo.repo,
            subtitle: repo.error || repo.description || "", status: repo.error ? "error" : (active ? "running" : "neutral"),
            info: repo.archived ? "archived" : repo.disabled ? "disabled" : repo.error ? "unavailable" : repo.checked || repo.runs ? active + " running" : "not checked",
            checked: repo.checked || "", repo: repo.repo, url: repo.url ? repo.url + "/-/pipelines" : ""});
        if (!expanded[repoKey]) return;
        // Pipelines past the first page of each unfinished status are counted, not fetched (#15).
        var hidden = repo.hidden || {};
        var parts = ["running", "pending", "created", "waiting_for_resource", "preparing"].filter(function(s) { return hidden[s] > 0 || hidden[s] === -1; })
            .map(function(s) {
                var name = s.replace(/_/g, " ");
                return hidden[s] === -1 ? "+more " + name : "+" + (hidden[s] > 1000 ? "about " : "") + hidden[s] + " more " + name;
            });
        var more = parts.length && (!query || repoMatch) ? {key: repoKey + ":more", parent: repoKey, kind: "more", depth: 1,
            title: parts.join(" · "), subtitle: "o opens GitLab", status: "", info: "", repo: repo.repo,
            url: repo.url ? repo.url + "/-/pipelines" : ""} : null;
        runs.forEach(function(run) {
            if (more && run.status === "completed") { result.push(more); more = null; }
            var runKey = repo.repo + ":" + run.id;
            var detail = details[runKey];
            result.push({key: runKey, parent: repoKey, kind: "run", depth: 1, title: run.name || "Pipeline",
                subtitle: (shortRef(run.head_branch) || "") + " · #" + run.run_number + " · " + (run.display_title || ""),
                status: state(run), info: duration(run, now), started: run.started_at || run.run_started_at || "",
                ended: run.completed_at || (run.status === "completed" ? run.updated_at : "") || "",
                finished: run.completed_at || "", fetched: detail && detail.updated || "",
                repo: repo.repo, run: String(run.id), url: run.html_url, sha: run.sha || ""});
            if (!expanded[runKey]) return;
            if (!detail || detail.error) result.push({key: runKey + ":message", parent: runKey, kind: "message", depth: 2,
                title: detail ? detail.error : "Loading jobs…", subtitle: "", status: detail ? "error" : "queued", info: "", repo: repo.repo, run: String(run.id)});
            stages((detail && detail.jobs) || []).forEach(function(stage) {
                var stageKey = runKey + ":stage:" + stage.name;
                var done = stage.jobs.filter(function(job) { return job.status === "completed"; }).length;
                result.push({key: stageKey, parent: runKey, kind: "stage", depth: 2, title: stage.name, subtitle: "",
                    status: stage.status, info: done + "/" + stage.jobs.length + " jobs · " + duration(stage.span, now),
                    started: stage.span.started_at || "", ended: stage.span.completed_at || "", done: done, total: stage.jobs.length,
                    repo: repo.repo, run: String(run.id), url: run.html_url, sha: run.sha || ""});
                if (!expanded[stageKey]) return;
                stage.jobs.forEach(function(job) {
                    result.push({key: runKey + ":" + job.id, parent: stageKey, kind: "job", depth: 3, title: job.name, subtitle: "",
                        status: job.conclusion === "failed" && job.allow_failure ? "allowed to fail" : state(job),
                        info: duration(job, now), started: job.started_at || "", ended: job.completed_at || "",
                        finished: job.completed_at || "", complete: job.status === "completed",
                        serverDuration: job.duration == null ? null : job.duration,
                        queued: job.queued_duration == null ? null : job.queued_duration,
                        reason: job.failure_reason || "", repo: repo.repo, run: String(run.id), url: job.html_url,
                        sha: run.sha || ""});
                });
            });
        });
        if (more) result.push(more);
    });
    return result;
}

function selection(rows, key, previous) {
    for (var i = 0; i < rows.length; i++) if (rows[i].key === key) return i;
    return Math.max(0, Math.min(previous, rows.length - 1));
}

function nextFailure(rows, cursor) {
    for (var offset = 1; offset <= rows.length; offset++) {
        var i = (cursor + offset) % rows.length;
        if (rows[i].status === "failed" && ["run", "stage", "job"].indexOf(rows[i].kind) >= 0) return i;
    }
    return -1;
}

function copyText(row, what) {
    if (!row) return {text: "", label: "Nothing to copy"};
    if (what === "url") return row.url ? {text: row.url, label: "Copied URL"} : {text: "", label: "Nothing to copy"};
    return row.sha ? {text: row.sha, label: "Copied " + row.sha.slice(0, 8)} : {text: "", label: "No commit for this row"};
}

// ponytail: the fields the delegate reads that can change for a key; add any new one the delegate reads.
var shownFields = ["title", "subtitle", "status", "info", "checked", "started", "ended", "finished",
    "fetched", "done", "total", "complete", "serverDuration", "queued", "reason", "sha"];

// Keep delegates alive when polling changes a status or inserts a running repo.
// Removing gone rows first keeps one removal from cascading into a move per later row.
function syncRows(model, rows) {
    var structureChanged = false, wanted = {}, present = {}, i, j;
    for (i = 0; i < rows.length; i++) wanted[rows[i].key] = true;
    for (j = model.count - 1; j >= 0; j--)
        if (!wanted[model.get(j).rowKey]) { model.remove(j, 1); structureChanged = true; }
    for (j = 0; j < model.count; j++) present[model.get(j).rowKey] = true;
    for (i = 0; i < rows.length; i++) {
        var key = rows[i].key;
        if (i >= model.count || model.get(i).rowKey !== key) {
            structureChanged = true;
            if (!present[key]) { model.insert(i, {rowKey: key, rowData: rows[i]}); continue; }
            for (j = i + 1; model.get(j).rowKey !== key; j++);
            model.move(j, i, 1);
        }
        var old = model.get(i).rowData;
        // null and undefined compare equal: a ListModel may hand a stored null back as undefined.
        if (shownFields.some(function(field) { return old[field] !== rows[i][field] && !(old[field] == null && rows[i][field] == null); }))
            model.setProperty(i, "rowData", rows[i]);
    }
    return structureChanged;
}

// Panel zoom: one step of 10 points from the current percent, clamped to 75..200; direction 0 resets.
function zoomStep(percent, direction) {
    if (direction > 0) return Math.min(200, Math.floor(percent / 10) * 10 + 10);
    if (direction < 0) return Math.max(75, Math.ceil(percent / 10) * 10 - 10);
    return 100;
}
