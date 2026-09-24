// One page at a time; all time is injected so scheduling can be tested without Qt.
var phases = ["recent", "running", "pending", "created", "waiting_for_resource", "preparing"];
function create() {
    return {opened:false, generation:0, serial:0, order:0, slot:0, starts:[], cooldown:0,
        rateFailures:0, auth:false, tasks:{}, flight:null, repos:[], details:{}, selected:"", inspected:"",
        stableAt:0, expanded:{}, catalogueAt:0, catalogueComplete:false, discover:true,
        error:"", requests:0, lastRequest:"", lastStarted:0};
}
function key(kind, repo, run) { return kind + ":" + (repo || "") + ":" + (run || ""); }
function age(at, interval) { return at === undefined ? -Infinity : at + interval; }
function repoFor(s, name) { return s.repos.filter(function(r) { return r.repo === name })[0]; }
function runFor(s, repo, id) {
    var r = repoFor(s, repo);
    return r && (r.runs || []).filter(function(run) { return String(run.id) === String(id) })[0];
}
function ensure(s, kind, repo, run, group, due) {
    var id = key(kind, repo, run), t = s.tasks[id];
    if (!t) {
        t = {key:id, kind:kind, repo:repo || "", run:String(run || ""), group:group,
            due:isFinite(due) ? due : s.clock || 0, order:++s.order, page:1, phase:0, items:[], all:[], failures:0};
        s.tasks[id] = t;
    } else t.group = group;
    return t;
}
function open(s, now) {
    s.opened = true; s.generation++; s.auth = false;
    if (!s.catalogueComplete || now - s.catalogueAt >= 300000) s.discover = true;
    s.stableAt = now;
}
function close(s) {
    s.opened = false; s.generation++; s.tasks = {}; s.flight = null;
}
function select(s, repo, run, expanded, now, immediate) {
    if (s.selected !== repo) s.stableAt = now + (immediate ? 0 : 250);
    else if (immediate) s.stableAt = now;
    s.selected = repo || ""; s.inspected = String(run || ""); s.expanded = expanded || {};
}
function manual(s, now, catalogue) {
    s.auth = false;
    if (catalogue) { s.discover = true; return; }
    var r = repoFor(s, s.selected);
    if (r) {
        r.blocked = false; r.error = ""; s.stableAt = now;
        ensure(s, "summary", r.repo, "", "interactive", now);
        if (s.inspected && s.expanded[r.repo + ":" + s.inspected]) {
            if (s.details[r.repo+":"+s.inspected]) s.details[r.repo+":"+s.inspected].unavailable=false;
            ensure(s, "jobs", r.repo, s.inspected, "interactive", now);
        }
    }
}
function seed(s, now) {
    Object.keys(s.tasks).forEach(function(id) {
        var t = s.tasks[id];
        if (s.flight && s.flight.key === id) return;
        var owner=repoFor(s,t.repo);
        if (owner && owner.blocked) { delete s.tasks[id]; return; }
        if ((t.kind === "summary" && t.repo !== s.selected) ||
            (t.kind === "jobs" && (t.repo !== s.selected || t.run !== s.inspected || !s.expanded[t.repo + ":" + t.run])))
            delete s.tasks[id];
    });
    if (s.discover) ensure(s, "catalogue", "", "", "background", now);
    var backgroundQueued=Object.keys(s.tasks).some(function(id) { var t=s.tasks[id]; return t.kind==="activity" && t.group==="background" });
    s.repos.slice().sort(function(a,b) { return (a.activityAt === undefined ? -Infinity : a.activityAt) - (b.activityAt === undefined ? -Infinity : b.activityAt) }).forEach(function(r) {
        if (r.archived || r.disabled || r.blocked) return;
        var selected = r.repo === s.selected && now >= s.stableAt;
        if (selected && now >= age(r.summaryAt, 60000)) ensure(s, "summary", r.repo, "", "interactive", age(r.summaryAt,60000));
        var summary = s.tasks[key("summary",r.repo)];
        var activityKey = key("activity",r.repo);
        if (summary && !(s.flight && s.flight.key === activityKey)) delete s.tasks[activityKey];
        if (!summary) {
            var interval = selected ? 10000 : r.active > 0 ? 15000 : 600000;
            var group = selected ? "interactive" : r.active > 0 ? "active" : "background";
            if (now >= age(r.activityAt, interval) && (group!=="background" || !backgroundQueued || s.tasks[activityKey])) {
                ensure(s, "activity",r.repo,"",group,age(r.activityAt,interval));
                if (group==="background") backgroundQueued=true;
            }
            else if (s.tasks[activityKey] && !(s.flight && s.flight.key === activityKey) && !s.tasks[activityKey].failures)
                delete s.tasks[activityKey];
            if (s.tasks[activityKey]) s.tasks[activityKey].group = group;
        }
        (r.runs || []).forEach(function(run) {
            if (run.awaitingFinal || run.followupAt !== undefined && run.status !== "completed" && run.status !== "in_progress")
                if (now >= age(run.followupAt,15000)) ensure(s,"run",r.repo,run.id,selected ? "interactive" : "active",age(run.followupAt,15000));
        });
        if (selected && s.inspected && s.expanded[r.repo + ":" + s.inspected]) {
            var run = runFor(s,r.repo,s.inspected), detail = s.details[r.repo + ":" + s.inspected];
            var attempt = run && (run.run_attempt || 1);
            if (detail && detail.unavailable) return;
            var final = run && run.status === "completed" && detail && detail.finalAttempt === attempt;
            if (!final && now >= age(detail && detail.jobsAt,5000)) ensure(s,"jobs",r.repo,s.inspected,"interactive",age(detail && detail.jobsAt,5000));
        }
    });
}
function next(s, now) {
    if (!s.opened || s.flight || s.auth || now < s.cooldown) return null;
    s.starts = s.starts.filter(function(at) { return now - at < 60000 });
    if (s.starts.length >= 60 || s.starts.length && now - s.starts[s.starts.length-1] < 1000) return null;
    s.clock=now;
    seed(s,now);
    var due = Object.keys(s.tasks).map(function(id) { return s.tasks[id] }).filter(function(t) { return t.due <= now });
    due.sort(function(a,b) { return a.due === b.due ? a.order-b.order : a.due-b.due });
    var group = ["interactive","interactive","interactive","active","background"][s.slot % 5];
    var t = due.filter(function(t) { return t.group === group })[0];
    if (!t) {
        ["interactive","active","background"].some(function(g) { t=due.filter(function(t) { return t.group===g })[0]; return !!t });
    }
    if (!t) return null;
    s.slot++; s.starts.push(now); s.requests++; s.lastStarted=now; s.lastRequest=t.kind + (t.repo ? " " + t.repo : "");
    var request = {kind:t.kind,repo:t.repo,run:t.run,page:t.page,requestId:++s.serial};
    if (t.kind === "summary") request.status = phases[t.phase];
    s.flight = {key:t.key, request:request, generation:s.generation};
    return request;
}
function union(a,b) {
    var map={};
    a.concat(b).forEach(function(item) {
        var id=String(item.id), old=map[id];
        if (!old || !old.updated_at || !item.updated_at || Date.parse(item.updated_at)>=Date.parse(old.updated_at)) map[id]=item;
    });
    return Object.keys(map).map(function(id) { return map[id] });
}
function invalidateJobs(s,r,incoming) {
    incoming.forEach(function(run) {
        var old=(r.runs || []).filter(function(x) { return x.id===run.id })[0];
        // Only a finished pipeline can be rerun; active pipelines change attempt when they finish.
        if (old && old.status==="completed" && ((old.run_attempt || 1)!==(run.run_attempt || 1) || run.status!=="completed"))
            delete s.details[r.repo + ":" + run.id];
    });
}
function mergeRuns(s,r,incoming) {
    incoming.forEach(function(run) {
        var old=runFor(s,r.repo,run.id);
        if (old && old.status!=="completed" && run.status==="completed" && s.selected===r.repo && s.inspected===String(run.id) && s.expanded[r.repo+":"+run.id])
            ensure(s,"jobs",r.repo,run.id,"interactive",s.clock || 0);
    });
    invalidateJobs(s,r,incoming);
    trimRuns(s,r,union(r.runs || [], incoming));
}
function trimRuns(s,r,runs) {
    var completed=0;
    r.runs=runs.sort(function(a,b) { return (a.status==="completed")-(b.status==="completed") || b.id-a.id }).filter(function(run) { return run.status!=="completed" || ++completed<=10 || s.expanded[r.repo+":"+run.id] });
}
function activity(s,r,items,now) {
    var ids={}; items.forEach(function(run) { ids[run.id]=true });
    var previous=r.runs || [];
    mergeRuns(s,r,items);
    previous.forEach(function(run) {
        if (run.status === "in_progress" && !ids[run.id]) {
            var missing=r.runs.filter(function(x) { return x.id===run.id })[0];
            if (missing.status!=="completed") { missing.awaitingFinal=true; delete missing.followupAt; }
        }
    });
    items.forEach(function(run) { var cached=runFor(s,r.repo,run.id); delete cached.awaitingFinal; delete cached.followupAt; });
    r.active=items.filter(function(run) { return run.status==="in_progress" }).length;
    r.activityAt=now; r.checked=new Date(now).toISOString(); r.error="";
}
function complete(s,reply,now) {
    var flight=s.flight;
    if (!s.opened || !flight || flight.generation!==s.generation || reply.requestId!==flight.request.requestId) return false;
    var t=s.tasks[flight.key]; s.flight=null;
    if (!t) return false;
    if (reply.errorType==="rate" || reply.remaining===0 || reply.retryAt>now) {
        var deadline=Math.max(reply.retryAt || 0,reply.remaining===0 ? reply.resetAt || 0 : 0);
        if (deadline<=now) deadline=now+Math.min(900000,60000*Math.pow(2,s.rateFailures));
        s.cooldown=Math.max(s.cooldown,deadline);
        if (reply.errorType==="rate") s.rateFailures++;
    }
    var r=repoFor(s,t.repo);
    if (reply.errorType || reply.error) {
        s.error=reply.error || "Invalid GitLab response";
        if (reply.errorType==="auth") s.auth=true;
        if (reply.errorType==="permission") {
            if (r && t.kind!=="jobs" && t.kind!=="run") { r.blocked=true; r.error=s.error; }
            else if (r && t.kind==="jobs") s.details[t.repo+":"+t.run]=Object.assign({},s.details[t.repo+":"+t.run] || {},{error:s.error,jobsAt:now,unavailable:true});
            else if (r) { var failed=runFor(s,t.repo,t.run); if(failed){ failed.awaitingFinal=false; delete failed.followupAt; failed.lookupError=s.error; } }
            delete s.tasks[t.key];
        } else {
            t.failures++; t.due=reply.errorType==="rate" ? s.cooldown : now+Math.min(300000,5000*Math.pow(2,t.failures-1));
            // Retry a failed snapshot from page one; keep already published cache data.
            t.page=1; t.phase=0; t.items=[]; t.all=[];
            if (r) r.error=s.error;
        }
        return true;
    }
    s.error=""; s.rateFailures=0; t.failures=0;
    if (r) r.error="";
    var data=reply.data;
    if (t.kind==="run") {
        if (r) {
            var resolved=Object.assign({},data,{awaitingFinal:false,followupAt:now});
            mergeRuns(s,r,[resolved]);
            r.active=(r.runs || []).filter(function(run) { return run.status==="in_progress" && !run.awaitingFinal }).length;
            if (resolved.status==="completed" && t.repo===s.selected && t.run===s.inspected && s.expanded[t.repo+":"+t.run])
                ensure(s,"jobs",t.repo,t.run,"interactive",now);
        }
        delete s.tasks[t.key]; return true;
    }
    t.items=t.kind==="catalogue" ? t.items.concat(data) : union(t.items,data);
    if (t.kind==="catalogue") {
        data.forEach(function(repo) {
            var existing=repoFor(s,repo.repo);
            if (existing) { Object.assign(existing,repo); existing.blocked=false; existing.error=""; }
            else s.repos.push(repo);
        });
    } else if (r && t.kind==="summary") mergeRuns(s,r,data);
    if (reply.nextPage) { t.page=reply.nextPage; t.due=now; t.order=++s.order; return true; }
    if (t.kind==="catalogue") {
        var names=t.items.map(function(repo) { return repo.repo });
        s.repos=s.repos.filter(function(repo) { return names.indexOf(repo.repo)>=0 });
        // Most recently active first; gitlab.com cannot sort membership by activity server-side.
        s.repos.sort(function(a,b) { return String(b.lastActivity || "").localeCompare(String(a.lastActivity || "")) || names.indexOf(a.repo)-names.indexOf(b.repo) });
        s.catalogueComplete=true; s.catalogueAt=now; s.discover=false;
    } else if (r && t.kind==="activity") activity(s,r,t.items,now);
    else if (r && t.kind==="summary") {
        t.all=union(t.all,t.items);
        if (phases[t.phase]==="running") activity(s,r,t.items,now);
        t.phase++; t.items=[]; t.page=1;
        if (t.phase<phases.length) { t.due=now; t.order=++s.order; return true; }
        var keep=(r.runs || []).filter(function(run) { return run.awaitingFinal || s.expanded[r.repo+":"+run.id] });
        trimRuns(s,r,union(t.all,keep));
        r.summaryAt=now;
    } else if (r && t.kind==="jobs") {
        var run=runFor(s,t.repo,t.run);
        s.details[t.repo+":"+t.run]={jobs:t.items,updated:new Date(now).toISOString(),jobsAt:now,
            finalAttempt:run && run.status==="completed" && t.items.every(function(job) { return job.status==="completed" }) ? run.run_attempt || 1 : 0};
    }
    delete s.tasks[t.key]; return true;
}
