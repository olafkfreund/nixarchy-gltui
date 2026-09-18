function reply(stdout, stderr, code) {
    if (stdout.trim()) return stdout;
    return JSON.stringify({error: stderr.trim().slice(0, 300) || "Workflow helper returned no data (exit " + code + ")"});
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
        runs.forEach(function(run) {
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
    });
    return result;
}

function selection(rows, key, previous) {
    for (var i = 0; i < rows.length; i++) if (rows[i].key === key) return i;
    return Math.max(0, Math.min(previous, rows.length - 1));
}

// Keep delegates alive when polling changes a status or inserts a running repo.
function syncRows(model, rows) {
    var structureChanged = false;
    for (var i = 0; i < rows.length; i++) {
        var found = -1;
        for (var j = i; j < model.count; j++) {
            if (model.get(j).rowKey === rows[i].key) { found = j; break; }
        }
        if (found < 0) {
            model.insert(i, {rowKey: rows[i].key, rowData: rows[i]});
            structureChanged = true;
        } else {
            if (found !== i) { model.move(found, i, 1); structureChanged = true; }
            if (JSON.stringify(model.get(i).rowData) !== JSON.stringify(rows[i]))
                model.setProperty(i, "rowData", rows[i]);
        }
    }
    if (model.count > rows.length) {
        model.remove(rows.length, model.count - rows.length);
        structureChanged = true;
    }
    return structureChanged;
}
