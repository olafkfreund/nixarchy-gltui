// Fixed text only: stderr can hold paths and tracebacks, so it goes to the log, never the panel.
function reply(stdout, code, requestId) {
    if (stdout.trim()) return stdout;
    return JSON.stringify({requestId: requestId, errorType: "setup",
        error: code === 127 ? "python3 not found" : "GitLab helper failed (exit " + code + "); see the shell log"});
}

function hostConfig(entry) {
    var result = {hosts:[], ignored:[], error:""};
    entry = entry || {};
    if (entry.hosts !== undefined && !Array.isArray(entry.hosts)) {
        result.error = "invalid hosts";
        return result;
    }
    var items = entry.hosts && entry.hosts.length ? entry.hosts : [entry];
    var seen = Object.create(null);
    for (var i=0; i<items.length; i++) {
        var item = items[i];
        var host = item && typeof item === "object" && !Array.isArray(item) ? item.host : undefined;
        if (!(entry.hosts && entry.hosts.length) && typeof host !== "string") host = "gitlab.com";
        if (typeof host !== "string" || !/^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?$/.test(host)) {
            result.error = "invalid host " + (host === undefined ? "" : host);
            result.hosts = []; result.ignored = [];
            return result;
        }
        if (seen[host.toLowerCase()]) continue;
        seen[host.toLowerCase()] = true;
        var value = {host:host, actions:item.actions === true,
            projects:Array.isArray(item.projects) ? item.projects : [],
            pinned:Array.isArray(item.pinned) ? item.pinned : []};
        if (result.hosts.length < 4) result.hosts.push(value);
        else result.ignored.push(host);
    }
    return result;
}

// The trailing slash pins the host; no whitespace or Cc control may reach xdg-open's helpers (#15, ghtui #32).
function browsable(url, host) {
    if (typeof url !== "string" || typeof host !== "string") return false;
    var pinned = host.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("^https://" + pinned + "/[^\\s\\x00-\\x1f\\x7f-\\x9f]+$", "i").test(url);
}

function openFilter(payload, panelHost) {
    var multi = Array.isArray(panelHost);
    var empty = multi ? {filter: null, host: "", notice: ""} : {filter: null, notice: ""};
    try {
        var value = typeof payload === "string" ? JSON.parse(payload) : payload;
        if (!value || typeof value !== "object" || Array.isArray(value) || typeof value.filter !== "string") return empty;
        var filter = value.filter.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").trim();
        if (!filter || filter.length > 200) return empty;
        if ("host" in value) {
            if (typeof value.host !== "string" || !value.host) return empty;
            if (multi) {
                var matches = panelHost.filter(function(host) { return value.host.replace(/:[0-9]+$/, "").toLowerCase() === host.replace(/:[0-9]+$/, "").toLowerCase(); });
                if (matches.length) return {filter: filter, host: matches.length === 1 ? matches[0] : "", notice: ""};
                var shownHost = value.host.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").slice(0, 100);
                return {filter: null, host: "", notice: "Repository is on " + shownHost + "; this panel shows " + panelHost.join(", ")};
            }
            if (value.host.toLowerCase() !== panelHost.replace(/:[0-9]+$/, "").toLowerCase()) {
                var shown = value.host.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").slice(0, 100);
                return {filter: null, notice: "Repository is on " + shown + "; this panel shows " + panelHost};
            }
        }
        return multi ? {filter: filter, host: "", notice: ""} : {filter: filter, notice: ""};
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

function barCounts(repos) {
    var running=0, failed=0;
    repos.forEach(function(repo) {
        if (repo.archived || repo.disabled || repo.blocked || repo.error) return;
        running+=repo.active === undefined ? (repo.runs || []).filter(function(run) { return run.status === "in_progress"; }).length : repo.active;
        var last=latest(repo.runs || []);
        if (last && last.conclusion==="failed") failed++;
    });
    return {running:running,failed:failed};
}

function barHost(polling, configError, host, now) {
    var counts=barCounts(polling.repos);
    var reason=configError || (polling.auth ? polling.error : polling.catalogueError) || "";
    var state=configError || polling.auth || polling.catalogueError ? "stopped" :
        polling.cooldown>now ? "rate" : polling.countsAt===undefined ? "none" : "ok";
    return {host:host,state:state,running:counts.running,failed:counts.failed,
        countsAt:polling.countsAt===undefined ? 0 : polling.countsAt,
        cooldownUntil:state==="rate" ? polling.cooldown : 0,reason:reason};
}

function barStatus(polling, configError, host, instance, now, more) {
    var first=barHost(polling, configError, host, now);
    if (!Array.isArray(more) || !more.length) return {version:1,instance:instance,host:host,
        state:first.state,running:first.running,failed:first.failed,countsAt:first.countsAt,
        cooldownUntil:first.cooldownUntil,reason:first.reason,writtenAt:now};
    var hosts=[first].concat(more.map(function(item) { return barHost(item.state, configError, item.host, now); }));
    var running=0, failed=0, countsAt=0, cooldown=0, reason="", hasOk=false, hasRate=false, hasStopped=false;
    hosts.forEach(function(h) {
        if ((h.state==="ok" || h.state==="rate") && h.countsAt>0) {
            running+=h.running;
            failed+=h.failed;
            countsAt=countsAt ? Math.min(countsAt, h.countsAt) : h.countsAt;
        }
        if (h.state==="ok") hasOk=true;
        else if (h.state==="rate") { hasRate=true; cooldown=Math.max(cooldown, h.cooldownUntil); }
        else if (h.state==="stopped") { hasStopped=true; if (!reason && h.reason) reason=h.host+": "+h.reason; }
    });
    var state=configError ? "stopped" : hasOk ? "ok" : hasRate ? "rate" : hasStopped ? "stopped" : "none";
    return {version:1,instance:instance,host:host+" +"+more.length,
        state:state,running:running,failed:failed,countsAt:countsAt,
        cooldownUntil:state==="rate" ? cooldown : 0,reason:configError || reason,writtenAt:now,hosts:hosts};
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
    var host = row.host && (row.hostLabel || row.multi) ? " on " + row.host : "";
    if (row.kind === "more" || row.kind === "message") return row.title + host;
    var kinds = {repo: "project", run: "pipeline", stage: "stage", job: "job", trigger: "downstream pipeline", mr: "merge request"};
    var parts = [row.title, kinds[row.kind]];
    if (row.kind === "repo" && row.pinned) parts.push("pinned");
    if (row.kind === "run" && row.watched) parts.push("watched");
    var status = group(row.status);
    var names = {success: "passed", allowed: "failed, allowed", neutral: "no status", unknown: "no status"};
    parts.push(names[status] || status);
    return parts.join(", ") + host;
}

// Merge-request view (#40). selectedKey is the scheduler key "<project_id>!<iid>".
function mrRows(mrs, filter, now, host, selectedKey, q) {
    q = q || "";
    var query = filter.toLowerCase(), list = (mrs && mrs.list) || [], result = [];
    list.forEach(function(mr) {
        var key = mr.project_id + "!" + mr.iid, st = (mrs.status || {})[key];
        var pipe = st && st.state === "ok" && st.pipeline ? st.pipeline : null;
        var status = pipe ? state(pipe) : "neutral";
        var info = !st ? "not checked" : pipe ? "" : {none: "no pipeline", hidden: "pipeline hidden"}[st.state] || "unavailable";
        if (st) {
            var unfinished = !!pipe && pipe.status !== "completed", selected = key === selectedKey;
            var target = selected ? (unfinished ? 10000 : 60000) : unfinished ? 30000 : 600000;
            if (now - st.at > target) info = (info ? info + " · " : "") + "checked " + ago(new Date(st.at).toISOString(), now);
        }
        var project = mr.project || "unknown project";
        var title = project + " !" + mr.iid + " " + mr.title;
        if (query && [title, mr.source_branch, status, q ? host : ""].join(" ").toLowerCase().indexOf(query) < 0) return;
        result.push({key: "mr:" + q + key, parent: "", kind: "mr", depth: 0, title: (mr.draft ? "Draft · " : "") + title,
            subtitle: mr.source_branch || "", status: status, info: info, repo: mr.project || "", mrKey: key,
            host: host, hostLabel: q ? host : "", multi: !!q,
            url: browsable(mr.web_url, host) ? mr.web_url : ""});
    });
    var total = mrs && typeof mrs.total === "number" ? mrs.total : 0;
    if (!query && (total === -1 || total > list.length)) result.push({key: q ? "mr:more:" + host : "mr:more", parent: "", kind: "more", depth: 0,
        title: (total === -1 ? "more on GitLab" : (total - list.length) + " more on GitLab") + (q ? " · " + host : ""), subtitle: "o opens GitLab",
        status: "", info: "", repo: "", host: host, hostLabel: q ? host : "", multi: !!q,
        url: "https://" + host + "/dashboard/merge_requests?scope=created_by_me&state=opened"});
    return result;
}

function subtitleText(row, now) {
    var fetched = row.kind === "run" ? ago(row.fetched, now) : "";
    return (row.subtitle || "") + (fetched ? " · jobs fetched " + fetched : "");
}

function repoMatches(repo, query) {
    return (repo.repo + " " + (repo.description || "") + (repo.q ? " " + repo.host : "")).toLowerCase().indexOf(query) >= 0;
}

function runMatches(run, query) {
    return [run.name, run.display_title, run.head_branch, shortRef(run.head_branch), state(run)].join(" ").toLowerCase().indexOf(query) >= 0;
}

function autoOpen(repos, filter, openHost) {
    var result = {};
    var query = filter.toLowerCase();
    if (!query) return result;
    repos.forEach(function(repo) {
        if (openHost && repo.host !== openHost) return;
        if (!repoMatches(repo, query) && (repo.runs || []).some(function(run) { return runMatches(run, query); }))
            result["repo:" + (repo.q || "") + repo.repo] = true;
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

function rows(repos, expanded, details, filter, now, pinned, watched, openHost) {
    var result = [];
    var query = filter.toLowerCase();
    pinned = pinned || {};
    watched = watched || {};
    repos.slice().sort(function(a, b) { return (!!pinned[(b.q || "") + b.repo]) - (!!pinned[(a.q || "") + a.repo]) || (b.active || 0) - (a.active || 0); }).forEach(function(repo) {
        if (openHost && repo.host !== openHost) return;
        var q = repo.q || "", host = repo.host || "";
        var repoMatch = repoMatches(repo, query);
        var runs = (repo.runs || []).filter(function(run) {
            return repoMatch || runMatches(run, query);
        });
        if (query && !repoMatch && !runs.length) return;
        var active = repo.active === undefined ? (repo.runs || []).filter(function(run) { return run.status === "in_progress"; }).length : repo.active;
        var last = repo.error ? null : latest(repo.runs || []);
        var repoKey = "repo:" + q + repo.repo;
        result.push({key: repoKey, parent: "", kind: "repo", depth: 0, title: repo.repo, pinned: !!pinned[q + repo.repo],
            subtitle: repo.error || repo.description || "", status: repo.error ? "error" : (active ? "running" : (last ? state(last) : "neutral")),
            info: repo.archived ? "archived" : repo.disabled ? "disabled" : repo.error ? "unavailable" :
                !active && repo.summaryAt !== undefined && !(repo.runs || []).length ? "no pipelines" : repo.checked || repo.runs ? active + " running" : "not checked",
            lastStatus: last ? state(last) : "", lastAt: last ? last.completed_at || last.updated_at || "" : "",
            checked: repo.checked || "", repo: repo.repo, host: host, hostLabel: q ? host : "", multi: !!q,
            url: repo.url ? repo.url + "/-/pipelines" : ""});
        if (!expanded[repoKey]) return;
        // Pipelines past the first page of each unfinished status are counted, not fetched (#15).
        var hidden = repo.hidden || {};
        var parts = ["running", "pending", "created", "waiting_for_resource", "preparing"].filter(function(s) { return hidden[s] > 0 || hidden[s] === -1; })
            .map(function(s) {
                var name = s.replace(/_/g, " ");
                return hidden[s] === -1 ? "+more " + name : "+" + (hidden[s] > 1000 ? "about " : "") + hidden[s] + " more " + name;
            });
        var more = parts.length && (!query || repoMatch) ? {key: repoKey + ":more", parent: repoKey, kind: "more", depth: 1,
            title: parts.join(" · "), subtitle: "o opens GitLab", status: "", info: "", repo: repo.repo, host: host, multi: !!q,
            url: repo.url ? repo.url + "/-/pipelines" : ""} : null;
        runs.forEach(function(run) {
            if (more && run.status === "completed") { result.push(more); more = null; }
            var runKey = q + repo.repo + ":" + run.id;
            var detail = details[runKey];
            result.push({key: runKey, parent: repoKey, kind: "run", depth: 1, title: run.name || "Pipeline",
                subtitle: (shortRef(run.head_branch) || "") + " · #" + run.run_number + " · " + (run.display_title || ""),
                status: state(run), info: duration(run, now), started: run.started_at || run.run_started_at || "",
                ended: run.completed_at || (run.status === "completed" ? run.updated_at : "") || "",
                finished: run.completed_at || "", fetched: detail && detail.updated || "",
                repo: repo.repo, run: String(run.id), host: host, multi: !!q, url: run.html_url, sha: run.sha || "",
                watched: !!watched[runKey]});
            if (!expanded[runKey]) return;
            if (!detail || detail.error || !detail.jobs) result.push({key: runKey + ":message", parent: runKey, kind: "message", depth: 2,
                title: detail && detail.error ? detail.error : "Loading jobs…", subtitle: "", status: detail && detail.error ? "error" : "queued", info: "", repo: repo.repo, run: String(run.id), host: host, multi: !!q});
            var entries = ((detail && detail.jobs) || []).concat((detail && detail.bridges) || []);
            entries.sort(function(a, b) { return Number(a.id) - Number(b.id); });
            stages(entries).forEach(function(stage) {
                var stageKey = runKey + ":stage:" + stage.name;
                var done = stage.jobs.filter(function(job) { return job.status === "completed"; }).length;
                result.push({key: stageKey, parent: runKey, kind: "stage", depth: 2, title: stage.name, subtitle: "",
                    status: stage.status, info: done + "/" + stage.jobs.length + " jobs · " + duration(stage.span, now),
                    started: stage.span.started_at || "", ended: stage.span.completed_at || "", done: done, total: stage.jobs.length,
                    repo: repo.repo, run: String(run.id), host: host, multi: !!q, url: run.html_url, sha: run.sha || ""});
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
                            finished: job.completed_at || "", repo: repo.repo, run: String(run.id), job: String(job.id), host: host, multi: !!q,
                            url: downstream && downstream.url || job.html_url, sha: downstream ? downstream.sha : run.sha || ""});
                        return;
                    }
                    result.push({key: runKey + ":" + job.id, parent: stageKey, kind: "job", job: String(job.id), depth: 3, title: job.name, subtitle: "",
                        status: job.conclusion === "failed" && job.allow_failure ? "allowed to fail" : state(job),
                        info: duration(job, now), started: job.started_at || "", ended: job.completed_at || "",
                        finished: job.completed_at || "", complete: job.status === "completed",
                        serverDuration: job.duration == null ? null : job.duration,
                        queued: job.queued_duration == null ? null : job.queued_duration,
                        reason: job.failure_reason || "", repo: repo.repo, run: String(run.id), host: host, multi: !!q, url: job.html_url,
                        sha: run.sha || ""});
                });
            });
            if (detail && detail.bridgesError) result.push({key: runKey + ":bridges-message", parent: runKey, kind: "message", depth: 2,
                title: "Downstream pipelines: " + detail.bridgesError, subtitle: "", status: "error", info: "", repo: repo.repo, run: String(run.id), host: host, multi: !!q});
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
    "fetched", "done", "total", "complete", "serverDuration", "queued", "reason", "sha", "pinned", "watched", "lastStatus", "lastAt", "host", "hostLabel"];

function watchNotice(code, repo, number, host) {
    var on = host ? " on " + host : "";
    if (code === "watching") return "Watching #" + number + " in " + repo + on;
    if (code === "unwatched") return "Stopped watching #" + number + on;
    if (code === "finished") return "Pipeline already finished";
    if (code === "cap") return "At most 5 watched pipelines";
    return "Select a pipeline to watch";
}

// Notification daemons may read the body as markup; a branch name can contain & or <.
function bodyText(text) { return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function watchMessage(event, oldHost, newHost, host) {
    var m = watchText(event, oldHost, newHost, host);
    return {summary: m.summary, body: bodyText(m.body)};
}

function watchText(event, oldHost, newHost, host) {
    var w = event.watch || {}, n = event.count, on = host ? " on " + host : "";
    var label = (w.repo + " #" + w.number) + (w.ref ? " · " + w.ref : "") + on;
    var many = n + " " + (n === 1 ? "pipeline" : "pipelines");
    if (event.type === "finished") {
        var word = event.conclusion === "success" ? "passed" : event.conclusion;
        return {summary: "Pipeline " + word, body: label};
    }
    if (event.type === "expired") return {summary: "Stopped watching a pipeline", body: w.repo + " #" + w.number + ": still running after 6 hours" + on};
    if (event.type === "unavailable") return {summary: "Pipeline unavailable", body: w.repo + " #" + w.number + on};
    if (event.type === "auth") return {summary: "GitLab sign-in needed", body: "Stopped watching " + many + ". Run glab auth login" + (host ? " --hostname " + host : "") + "."};
    if (event.type === "removed") return {summary: "Stopped watching " + many, body: n + " " + (n === 1 ? "watch" : "watches") + " on " + (host || oldHost) + " ended: the host was removed."};
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
    return {reason: isJob ? "Select a pipeline to start a new one" : "Select a pipeline or job"};
}

function cut(text) {
    text = String(text);
    return text.length > 30 ? text.slice(0, 29) + "…" : text;
}

function describe(action, repo, run, job, host) {
    var ref = cut(run.head_branch || ""), name = cut(run.name || "Pipeline"), on = host ? " on " + host : "";
    var pipe = "#" + run.run_number + " " + name + " (" + ref + ") in " + repo + on;
    var one = job ? cut(job.name) + " (job " + job.id + ") of #" + run.run_number + " in " + repo + on : "";
    var yes = " y yes · Esc no", undone = " Cannot be undone.";
    switch (action) {
    case "retry-pipeline": return {confirm: "Retry pipeline " + pipe + "?" + yes, done: "Retry requested: pipeline " + pipe};
    case "cancel-pipeline": return {confirm: "Cancel pipeline " + pipe + "?" + undone + yes, done: "Cancel requested: pipeline " + pipe};
    case "retry-job": return {confirm: "Retry job " + one + "?" + yes, done: "Retry requested: job " + one};
    case "cancel-job": return {confirm: "Cancel job " + one + "?" + undone + yes, done: "Cancel requested: job " + one};
    case "play-job": return {confirm: "Play manual job " + one + " with its default variables?" + yes, done: "Play requested: job " + one};
    default: return {confirm: "Start a new pipeline on " + ref + " in " + repo + " with default variables" + on + "?" + yes,
        done: "New pipeline requested on " + ref + " in " + repo + on};
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
