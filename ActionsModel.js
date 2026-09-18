function reply(stdout, stderr, code) {
    if (stdout.trim()) return stdout;
    return JSON.stringify({error: stderr.trim().slice(0, 300) || "Workflow helper returned no data (exit " + code + ")"});
}

function state(item) {
    return item.awaitingFinal ? "awaiting final status" : item.lookupError ? "unavailable" : item.conclusion || item.status || "unknown";
}

function icon(status) {
    if (status === "success") return "✓";
    if (["failure", "timed_out", "startup_failure"].indexOf(status) >= 0) return "✕";
    if (status === "in_progress") return "◷";
    if (status === "cancelled") return "⊘";
    if (["skipped", "neutral"].indexOf(status) >= 0) return "−";
    return "○";
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
            subtitle: repo.error || repo.description || "", status: repo.error ? "error" : (active ? "in_progress" : "neutral"),
            info: repo.archived ? "archived" : repo.disabled ? "disabled" : repo.error ? "unavailable" : repo.checked || repo.runs ? active + " running" : "not checked",
            repo: repo.repo, url: "https://github.com/" + repo.repo + "/actions"});
        if (!expanded[repoKey]) return;
        runs.forEach(function(run) {
            var runKey = repo.repo + ":" + run.id;
            var detail = details[runKey];
            var stamp = detail && detail.updated ? " · jobs fetched " + detail.updated.slice(11, 19) + " UTC" : "";
            result.push({key: runKey, parent: repoKey, kind: "run", depth: 1, title: run.name || "Workflow",
                subtitle: (run.head_branch || "") + " · #" + run.run_number + stamp + " · " + (run.display_title || ""),
                status: state(run), info: duration(run, now), repo: repo.repo, run: String(run.id), url: run.html_url});
            if (!expanded[runKey]) return;
            if (!detail || detail.error) result.push({key: runKey + ":message", parent: runKey, kind: "message", depth: 2,
                title: detail ? detail.error : "Loading jobs…", subtitle: "", status: detail ? "error" : "queued", info: "", repo: repo.repo, run: String(run.id)});
            ((detail && detail.jobs) || []).forEach(function(job) {
                var jobKey = runKey + ":" + job.id;
                var steps = job.steps || [];
                var done = steps.filter(function(step) { return step.status === "completed"; }).length;
                result.push({key: jobKey, parent: runKey, kind: "job", depth: 2, title: job.name, subtitle: "",
                    status: state(job), info: done + "/" + steps.length + " steps · " + duration(job, now), repo: repo.repo, run: String(run.id), url: job.html_url});
                if (!expanded[jobKey]) return;
                steps.forEach(function(step) {
                    result.push({key: jobKey + ":" + step.number, parent: jobKey, kind: "step", depth: 3, title: step.name, subtitle: "",
                        status: state(step), info: duration(step, now), repo: repo.repo, run: String(run.id), url: job.html_url});
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
