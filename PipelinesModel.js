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

function openFilter(payload, panelHost) {
    var empty = {filter: null, notice: ""};
    try {
        var value = typeof payload === "string" ? JSON.parse(payload) : payload;
        if (!value || typeof value !== "object" || Array.isArray(value) || typeof value.filter !== "string") return empty;
        var filter = value.filter.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").trim();
        if (!filter || filter.length > 200) return empty;
        if ("host" in value) {
            if (typeof value.host !== "string" || !value.host) return empty;
            if (value.host.toLowerCase() !== panelHost.replace(/:[0-9]+$/, "").toLowerCase()) {
                var shown = value.host.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").slice(0, 100);
                return {filter: null, notice: "Repository is on " + shown + "; this panel shows " + panelHost};
            }
        }
        return {filter: filter, notice: ""};
    } catch (error) {
        return empty;
    }
}

function validProject(name) {
    return typeof name === "string" && /^[A-Za-z0-9_.][A-Za-z0-9_.-]*(\/[A-Za-z0-9_.][A-Za-z0-9_.-]*)+$/.test(name) &&
        !/(^|\/)\.\.?(\/|$)/.test(name);
}

function pins(config, saved) {
    var names = [], configured = Object.create(null), seen = Object.create(null);
    (Array.isArray(config) ? config : []).forEach(function(name) {
        if (validProject(name)) configured[name] = true;
    });
    (Array.isArray(config) ? config : []).concat(Array.isArray(saved) ? saved : []).forEach(function(name) {
        if (validProject(name) && !seen[name]) {
            seen[name] = true;
            if (names.length < 10) names.push(name);
        }
    });
    return {names:names, config:configured};
}

function togglePin(repo, config, saved) {
    var p = pins(config, saved), current = Array.isArray(saved) ? saved : [];
    if (p.config[repo]) return {saved:null, notice:"Pinned in shell.json"};
    if (p.names.indexOf(repo) >= 0) return {saved:current.filter(function(name) { return name !== repo; }), notice:"Unpinned " + repo};
    if (p.names.length >= 10) return {saved:null, notice:"At most 10 pins"};
    return {saved:current.filter(function(name) { return name !== repo; }).concat([repo]), notice:"Pinned " + repo};
}

function state(item) {
    return item.awaitingFinal ? "awaiting final status" : item.lookupError ? "unavailable" : item.conclusion || item.status || "unknown";
}

function latest(runs) {
    var found = null;
    runs.forEach(function(run) {
        if (run.status === "completed" && !run.awaitingFinal && !run.lookupError &&
            isFinite(Number(run.id)) && (!found || Number(run.id) > Number(found.id))) found = run;
    });
    return found;
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
        var age = row.lastStatus ? ago(row.lastAt, now) : "";
        var checked = row.info && /running$/.test(row.info) ? ago(row.checked, now) : "";
        return row.info + (row.lastStatus ? " · last " + row.lastStatus + (age ? " " + age : "") : "") +
            (checked ? " · checked " + checked : "");
    }
    var live = duration({started_at: row.started, completed_at: row.ended,
        status: row.ended ? "completed" : ""}, now);
    var parts = [row.status];
    if (row.kind === "run") parts.push(live, ago(row.finished, now));
    else if (row.kind === "stage") parts.push(row.done + "/" + row.total + " jobs", live);
    else if (row.kind === "trigger") parts.push(live ? "trigger " + live : "", ago(row.finished, now));
    else if (row.kind === "job") {
        if (row.status === "failed" || row.status === "allowed to fail") parts.push(reasonText(row.reason));
        parts.push(row.complete && typeof row.serverDuration === "number" ? seconds(Math.round(row.serverDuration)) : live);
        if (row.queued > 0) parts.push("queued " + seconds(Math.round(row.queued)));
        parts.push(ago(row.finished, now));
    } else return row.status + (row.info ? " · " + row.info : "");
    return parts.filter(Boolean).join(" · ");
}

function accessibleName(row) {
    if (row.kind === "more" || row.kind === "message") return row.title;
    var kinds = {repo: "project", run: "pipeline", stage: "stage", job: "job", trigger: "downstream pipeline"};
    var parts = [row.title, kinds[row.kind]];
    if (row.kind === "repo" && row.pinned) parts.push("pinned");
    if (row.kind === "run" && row.watched) parts.push("watched");
    var status = group(row.status);
    var names = {success: "passed", allowed: "failed, allowed", neutral: "no status", unknown: "no status"};
    parts.push(names[status] || status);
    return parts.join(", ");
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

function rows(repos, expanded, details, filter, now, pinned, watched) {
    var result = [];
    var query = filter.toLowerCase();
    pinned = pinned || {};
    watched = watched || {};
    repos.slice().sort(function(a, b) { return (!!pinned[b.repo]) - (!!pinned[a.repo]) || (b.active || 0) - (a.active || 0); }).forEach(function(repo) {
        var repoMatch = repoMatches(repo, query);
        var runs = (repo.runs || []).filter(function(run) {
            return repoMatch || runMatches(run, query);
        });
        if (query && !repoMatch && !runs.length) return;
        var active = repo.active === undefined ? (repo.runs || []).filter(function(run) { return run.status === "in_progress"; }).length : repo.active;
        var last = repo.error ? null : latest(repo.runs || []);
        var repoKey = "repo:" + repo.repo;
        result.push({key: repoKey, parent: "", kind: "repo", depth: 0, title: repo.repo, pinned: !!pinned[repo.repo],
            subtitle: repo.error || repo.description || "", status: repo.error ? "error" : (active ? "running" : (last ? state(last) : "neutral")),
            info: repo.archived ? "archived" : repo.disabled ? "disabled" : repo.error ? "unavailable" :
                !active && repo.summaryAt !== undefined && !(repo.runs || []).length ? "no pipelines" : repo.checked || repo.runs ? active + " running" : "not checked",
            lastStatus: last ? state(last) : "", lastAt: last ? last.completed_at || last.updated_at || "" : "",
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
                repo: repo.repo, run: String(run.id), url: run.html_url, sha: run.sha || "",
                watched: !!watched[repo.repo + ":" + run.id]});
            if (!expanded[runKey]) return;
            if (!detail || detail.error || !detail.jobs) result.push({key: runKey + ":message", parent: runKey, kind: "message", depth: 2,
                title: detail && detail.error ? detail.error : "Loading jobs…", subtitle: "", status: detail && detail.error ? "error" : "queued", info: "", repo: repo.repo, run: String(run.id)});
            var entries = ((detail && detail.jobs) || []).concat((detail && detail.bridges) || []);
            entries.sort(function(a, b) { return Number(a.id) - Number(b.id); });
            stages(entries).forEach(function(stage) {
                var stageKey = runKey + ":stage:" + stage.name;
                var done = stage.jobs.filter(function(job) { return job.status === "completed"; }).length;
                result.push({key: stageKey, parent: runKey, kind: "stage", depth: 2, title: stage.name, subtitle: "",
                    status: stage.status, info: done + "/" + stage.jobs.length + " jobs · " + duration(stage.span, now),
                    started: stage.span.started_at || "", ended: stage.span.completed_at || "", done: done, total: stage.jobs.length,
                    repo: repo.repo, run: String(run.id), url: run.html_url, sha: run.sha || ""});
                if (!expanded[stageKey]) return;
                stage.jobs.forEach(function(job) {
                    if (Object.prototype.hasOwnProperty.call(job, "downstream")) {
                        var downstream = job.downstream;
                        var child = downstream && typeof downstream.project_id === "number" && downstream.project_id >= 0 && downstream.project_id % 1 === 0 &&
                            typeof downstream.parent_project_id === "number" && downstream.parent_project_id >= 0 && downstream.parent_project_id % 1 === 0 &&
                            downstream.project_id === downstream.parent_project_id;
                        var status = downstream ? state(downstream) : state(job);
                        result.push({key: runKey + ":bridge:" + job.id, parent: stageKey, kind: "trigger", depth: 3,
                            title: "» " + job.name, subtitle: downstream ? (child ? "child" : downstream.project || "another project") +
                                " · #" + (downstream.iid || downstream.id) + " · " + shortRef(downstream.ref) : "downstream not created or unavailable",
                            status: status === "failed" && job.allow_failure ? "allowed to fail" : status,
                            info: duration(job, now), started: job.started_at || "", ended: job.completed_at || "",
                            finished: job.completed_at || "", repo: repo.repo, run: String(run.id),
                            url: downstream && downstream.url || job.html_url, sha: downstream ? downstream.sha : run.sha || ""});
                        return;
                    }
                    result.push({key: runKey + ":" + job.id, parent: stageKey, kind: "job", job: String(job.id), depth: 3, title: job.name, subtitle: "",
                        status: job.conclusion === "failed" && job.allow_failure ? "allowed to fail" : state(job),
                        info: duration(job, now), started: job.started_at || "", ended: job.completed_at || "",
                        finished: job.completed_at || "", complete: job.status === "completed",
                        serverDuration: job.duration == null ? null : job.duration,
                        queued: job.queued_duration == null ? null : job.queued_duration,
                        reason: job.failure_reason || "", repo: repo.repo, run: String(run.id), url: job.html_url,
                        sha: run.sha || ""});
                });
            });
            if (detail && detail.bridgesError) result.push({key: runKey + ":bridges-message", parent: runKey, kind: "message", depth: 2,
                title: "Downstream pipelines: " + detail.bridgesError, subtitle: "", status: "error", info: "", repo: repo.repo, run: String(run.id)});
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
        if (rows[i].status === "failed" && ["run", "stage", "job", "trigger"].indexOf(rows[i].kind) >= 0) return i;
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
    "fetched", "done", "total", "complete", "serverDuration", "queued", "reason", "sha", "pinned", "watched", "lastStatus", "lastAt"];

function watchNotice(code, repo, number) {
    if (code === "watching") return "Watching #" + number + " in " + repo;
    if (code === "unwatched") return "Stopped watching #" + number;
    if (code === "finished") return "Pipeline already finished";
    if (code === "cap") return "At most 5 watched pipelines";
    return "Select a pipeline to watch";
}

// Notification daemons may read the body as markup; a branch name can contain & or <.
function bodyText(text) { return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function watchMessage(event, oldHost, newHost) {
    var m = watchText(event, oldHost, newHost);
    return {summary: m.summary, body: bodyText(m.body)};
}

function watchText(event, oldHost, newHost) {
    var w = event.watch || {}, n = event.count;
    var label = (w.repo + " #" + w.number) + (w.ref ? " · " + w.ref : "");
    var many = n + " " + (n === 1 ? "pipeline" : "pipelines");
    if (event.type === "finished") {
        var word = event.conclusion === "success" ? "passed" : event.conclusion;
        return {summary: "Pipeline " + word, body: label};
    }
    if (event.type === "expired") return {summary: "Stopped watching a pipeline", body: w.repo + " #" + w.number + ": still running after 6 hours"};
    if (event.type === "unavailable") return {summary: "Pipeline unavailable", body: w.repo + " #" + w.number};
    if (event.type === "auth") return {summary: "GitLab sign-in needed", body: "Stopped watching " + many + ". Run glab auth login."};
    return {summary: "Stopped watching " + many, body: "The panel now uses " + newHost + ", not " + oldHost + "."};
}

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

// Pipeline and job actions (#39). The raw GitLab object decides, never the mapped row status.
var activeStates = ["created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"];

function actionFor(key, row, raw) {
    var isRun = !!row && row.kind === "run", isJob = !!row && row.kind === "job";
    if (!isRun && !isJob) return {reason: "Select a pipeline or job"};
    if (!raw) return {reason: "Select the row again"};
    var what = isRun ? "pipeline" : "job", c = raw.conclusion;
    if (key === "a") {
        return c === "failed" || c === "canceled" ? {action: "retry-" + what}
            : {reason: "Only a failed or canceled " + what + " can be retried"};
    }
    if (key === "c") {
        return activeStates.indexOf(c) >= 0 ? {action: "cancel-" + what}
            : {reason: "Only a running or queued " + what + " can be canceled"};
    }
    if (key === "x") {
        return isJob && c === "manual" ? {action: "play-job"} : {reason: "Only a manual job can be played"};
    }
    if (key === "n" && isRun) {
        var ref = raw.ref;
        if (raw.source === "merge_request_event" || typeof ref === "string" && ref.indexOf("refs/merge-requests/") === 0)
            return {reason: "Merge-request pipelines cannot be started from the panel"};
        return typeof ref === "string" && ref ? {action: "new-pipeline"} : {reason: "This pipeline has no branch or tag to start from"};
    }
    return {reason: "Select a pipeline or job"};
}

function cut(text) {
    text = String(text);
    return text.length > 30 ? text.slice(0, 29) + "…" : text;
}

function describe(action, repo, run, job) {
    var ref = cut(run.head_branch || ""), name = cut(run.name || "Pipeline");
    var pipe = "#" + run.run_number + " " + name + " (" + ref + ") in " + repo;
    var one = job ? cut(job.name) + " (job " + job.id + ") of #" + run.run_number + " in " + repo : "";
    var yes = " y yes · Esc no", undone = " Cannot be undone.";
    switch (action) {
    case "retry-pipeline": return {confirm: "Retry pipeline " + pipe + "?" + yes, done: "Retry requested: pipeline " + pipe};
    case "cancel-pipeline": return {confirm: "Cancel pipeline " + pipe + "?" + undone + yes, done: "Cancel requested: pipeline " + pipe};
    case "retry-job": return {confirm: "Retry job " + one + "?" + yes, done: "Retry requested: job " + one};
    case "cancel-job": return {confirm: "Cancel job " + one + "?" + undone + yes, done: "Cancel requested: job " + one};
    case "play-job": return {confirm: "Play manual job " + one + " with its default variables?" + yes, done: "Play requested: job " + one};
    default: return {confirm: "Start a new pipeline on " + ref + " in " + repo + " with default variables?" + yes,
        done: "New pipeline requested on " + ref + " in " + repo};
    }
}

function actionReply(stdout, code, requestId) {
    var unknown = {requestId: requestId, errorType: "unknown", error: "Outcome unknown; check GitLab before retrying"};
    if (!String(stdout).trim()) return code === 127 ? {errorType: "setup", error: "python3 not found"} : unknown;
    try {
        var value = JSON.parse(stdout);
        return value && typeof value === "object" && !Array.isArray(value) && value.requestId === requestId ? value : unknown;
    } catch (error) {
        return unknown;
    }
}
