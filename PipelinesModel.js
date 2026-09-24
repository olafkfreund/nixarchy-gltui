// Fixed text only: stderr can hold paths and tracebacks, so it goes to the log, never the panel.
function reply(stdout, code, requestId) {
    if (stdout.trim()) return stdout;
    return JSON.stringify({requestId: requestId, errorType: "setup",
        error: code === 127 ? "python3 not found" : "GitLab helper failed (exit " + code + "); see the shell log"});
}

function state(item) {
    return item.awaitingFinal ? "awaiting final status" : item.lookupError ? "unavailable" : item.conclusion || item.status || "unknown";
}

function icon(status) {
    if (status === "success") return "✓";
    if (status === "failed") return "✕";
    if (status === "running" || status === "canceling") return "◷";
    if (status === "canceled") return "⊘";
    if (["skipped", "manual", "scheduled", "neutral"].indexOf(status) >= 0) return "−";
    return "○";
}

function some(jobs, statuses) {
    return jobs.some(function(job) { return statuses.indexOf(job.conclusion) >= 0; });
}

// Stage status follows GitLab: activity first, then blocking failures.
function stageStatus(jobs) {
    if (some(jobs, ["running", "canceling"])) return "running";
    if (jobs.some(function(job) { return job.conclusion === "failed" && !job.allow_failure; })) return "failed";
    if (some(jobs, ["created", "pending", "preparing", "waiting_for_resource"])) return "pending";
    if (some(jobs, ["canceled"])) return "canceled";
    if (some(jobs, ["success"])) return "success";
    return jobs.length && jobs.every(function(job) { return job.conclusion === "manual"; }) ? "manual" : "skipped";
}

function stages(jobs) {
    var order = [], byName = {};
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
    var seconds = Math.max(0, Math.floor(((isFinite(end) ? end : now) - start) / 1000));
    if (seconds >= 3600) return Math.floor(seconds / 3600) + "h " + Math.floor(seconds % 3600 / 60) + "m";
    return seconds >= 60 ? Math.floor(seconds / 60) + "m " + seconds % 60 + "s" : seconds + "s";
}

function rows(repos, expanded, details, filter, now) {
    var result = [];
    var query = filter.toLowerCase();
    repos.slice().sort(function(a, b) { return (b.active || 0) - (a.active || 0); }).forEach(function(repo) {
        var repoMatch = (repo.repo + " " + (repo.description || "")).toLowerCase().indexOf(query) >= 0;
        var runs = (repo.runs || []).filter(function(run) {
            return repoMatch || [run.name, run.display_title, run.head_branch, state(run)].join(" ").toLowerCase().indexOf(query) >= 0;
        });
        if (query && !repoMatch && !runs.length) return;
        var active = repo.active === undefined ? (repo.runs || []).filter(function(run) { return run.status === "in_progress"; }).length : repo.active;
        var repoKey = "repo:" + repo.repo;
        result.push({key: repoKey, parent: "", kind: "repo", depth: 0, title: repo.repo,
            subtitle: repo.error || repo.description || "", status: repo.error ? "error" : (active ? "running" : "neutral"),
            info: repo.archived ? "archived" : repo.disabled ? "disabled" : repo.error ? "unavailable" : repo.checked || repo.runs ? active + " running" : "not checked",
            repo: repo.repo, url: repo.url ? repo.url + "/-/pipelines" : ""});
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
            var stamp = detail && detail.updated ? " · jobs fetched " + detail.updated.slice(11, 19) + " UTC" : "";
            result.push({key: runKey, parent: repoKey, kind: "run", depth: 1, title: run.name || "Pipeline",
                subtitle: (run.head_branch || "") + " · #" + run.run_number + stamp + " · " + (run.display_title || ""),
                status: state(run), info: duration(run, now), repo: repo.repo, run: String(run.id), url: run.html_url});
            if (!expanded[runKey]) return;
            if (!detail || detail.error) result.push({key: runKey + ":message", parent: runKey, kind: "message", depth: 2,
                title: detail ? detail.error : "Loading jobs…", subtitle: "", status: detail ? "error" : "queued", info: "", repo: repo.repo, run: String(run.id)});
            stages((detail && detail.jobs) || []).forEach(function(stage) {
                var stageKey = runKey + ":stage:" + stage.name;
                var done = stage.jobs.filter(function(job) { return job.status === "completed"; }).length;
                result.push({key: stageKey, parent: runKey, kind: "stage", depth: 2, title: stage.name, subtitle: "",
                    status: stage.status, info: done + "/" + stage.jobs.length + " jobs · " + duration(stage.span, now),
                    repo: repo.repo, run: String(run.id), url: run.html_url});
                if (!expanded[stageKey]) return;
                stage.jobs.forEach(function(job) {
                    result.push({key: runKey + ":" + job.id, parent: stageKey, kind: "job", depth: 3, title: job.name, subtitle: "",
                        status: state(job), info: duration(job, now), repo: repo.repo, run: String(run.id), url: job.html_url});
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

// ponytail: the fields the delegate reads that can change for a key; add any new one the delegate reads.
var shownFields = ["title", "subtitle", "status", "info"];

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
        if (shownFields.some(function(field) { return old[field] !== rows[i][field]; }))
            model.setProperty(i, "rowData", rows[i]);
    }
    return structureChanged;
}
