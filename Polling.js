// One page at a time; all time is injected so scheduling can be tested without Qt.
var phases = ["recent", "running", "pending", "created", "waiting_for_resource", "preparing"];
var WATCH_CAP=5, WATCH_TTL=21600000, WATCH_EVERY=30000;
var FINISHED=["success","failed","canceled","skipped"];
function create() {
    // Every exported writer invalidates wakeAt; seeds is test-only.
    return {opened:false, generation:0, serial:0, order:0, slot:0, starts:[], cooldown:0,
        rateFailures:0, auth:false, tasks:{}, flight:null, repos:[], details:{}, selected:"", inspected:"",
        stableAt:0, expanded:{}, pinned:{}, catalogueAt:0, catalogueComplete:false, discover:true,
        error:"", catalogueError:"", requests:0, lastRequest:"", lastStarted:0, wakeAt:0, seeds:0,
        watches:{}, events:[]};
}
function resetHost(s) {
    return Object.assign(create(),{opened:s.opened,starts:s.starts,serial:s.serial,generation:s.generation+1});
}
function key(kind, repo, run) { return kind + ":" + (repo || "") + ":" + (run || ""); }
function age(at, interval) { return at === undefined ? -Infinity : at + interval; }
function repoFor(s, name) { return s.repos.filter(function(r) { return r.repo === name })[0]; }
function runFor(s, repo, id) {
    var r = repoFor(s, repo);
    return r && (r.runs || []).filter(function(run) { return String(run.id) === String(id) })[0];
}
function finished(run) { return !!run && FINISHED.indexOf(run.conclusion)>=0; }
function watch(s, repo, run, now) {
    s.wakeAt=0;
    var id=repo+":"+run;
    if (s.watches[id]) { delete s.watches[id]; return "unwatched"; }
    var r=runFor(s,repo,run);
    if (!r) return "missing";
    if (finished(r)) return "finished";
    if (Object.keys(s.watches).length>=WATCH_CAP) return "cap";
    s.watches[id]={repo:repo,run:String(run),number:r.run_number,ref:r.head_branch||"",
        until:now+WATCH_TTL,checkedAt:0};
    return "watching";
}
function settle(s, now) {
    Object.keys(s.watches).forEach(function(id) {
        var w=s.watches[id], type="", run;
        if (now>=w.until) type="expired";
        else if (!repoFor(s,w.repo)) type="unavailable";
        else { run=runFor(s,w.repo,w.run); if (finished(run)) type="finished"; }
        if (type) {
            s.events.push(type==="finished" ? {type:type,watch:w,conclusion:run.conclusion} : {type:type,watch:w});
            delete s.watches[id]; s.wakeAt=0;
        }
    });
}
function ensure(s, kind, repo, run, group, due) {
    s.wakeAt=0;
    var id = key(kind, repo, run), t = s.tasks[id];
    if (!t) {
        t = {key:id, kind:kind, repo:repo || "", run:String(run || ""), group:group,
            due:isFinite(due) ? due : s.clock || 0, order:++s.order, page:1, phase:0, items:[], all:[], failures:0};
        s.tasks[id] = t;
    } else t.group = group;
    return t;
}
function restart(s,t,now) {
    s.wakeAt=0;
    if (s.flight && s.flight.key===t.key) { t.restart=true; return; }
    t.page=1; t.phase=0; t.items=[]; t.all=[]; t.failures=0; t.due=now;
}
function open(s, now) {
    s.wakeAt=0;
    s.opened = true; s.generation++; s.auth = false;
    if (s.flight) s.flight.generation=s.generation;
    if ((!s.catalogueComplete || now - s.catalogueAt >= 300000) && !s.catalogueError) s.discover = true;
    s.stableAt = now;
}
function close(s) {
    s.wakeAt=0;
    s.opened = false; s.generation++; s.tasks = {}; s.flight = null;
    if (s.auth && Object.keys(s.watches).length) {
        s.events.push({type:"auth",count:Object.keys(s.watches).length});
        s.watches={}; s.wakeAt=0;
    }
}
function select(s, repo, run, expanded, now, immediate) {
    s.wakeAt=0;
    if (s.selected !== repo) s.stableAt = now + (immediate ? 0 : 250);
    else if (immediate) s.stableAt = now;
    s.selected = repo || ""; s.inspected = String(run || ""); s.expanded = expanded || {};
}
function pin(s, names) {
    s.wakeAt=0;
    s.pinned={};
    names.forEach(function(name) {
        s.pinned[name]=true;
        if (!s.catalogueComplete && !repoFor(s,name)) s.repos.push({repo:name});
    });
}
function manual(s, now, catalogue) {
    s.wakeAt=0;
    s.auth = false;
    if (catalogue) { s.catalogueError = ""; s.discover = true; return; }
    var r = repoFor(s, s.selected);
    if (r) {
        r.blocked = false; r.error = ""; s.stableAt = now;
        restart(s,ensure(s, "summary", r.repo, "", "interactive", now),now);
        if (s.inspected && s.expanded[r.repo + ":" + s.inspected]) {
            if (s.details[r.repo+":"+s.inspected]) s.details[r.repo+":"+s.inspected].unavailable=false;
            restart(s,ensure(s, "jobs", r.repo, s.inspected, "interactive", now),now);
        }
    }
}
function seed(s, now) {
    s.seeds++;
    var wake=Infinity;
    Object.keys(s.tasks).forEach(function(id) {
        var t = s.tasks[id];
        if (s.flight && s.flight.key === id) return;
        var owner=repoFor(s,t.repo);
        var watched=t.kind==="run" && s.watches[t.repo+":"+t.run];
        if (owner && owner.blocked && !watched) { delete s.tasks[id]; return; }
        if (t.repo && !owner && !watched) { delete s.tasks[id]; return; }
        if ((t.kind === "summary" && t.repo !== s.selected) ||
            (t.kind === "jobs" && (t.repo !== s.selected || t.run !== s.inspected || !s.expanded[t.repo + ":" + t.run])))
            delete s.tasks[id];
    });
    if (s.discover) ensure(s, "catalogue", "", "", "background", now);
    if (s.stableAt>now) wake=Math.min(wake,s.stableAt);
    var backgroundQueued=Object.keys(s.tasks).some(function(id) { var t=s.tasks[id]; return t.kind==="activity" && t.group==="background" });
    s.repos.slice().sort(function(a,b) { return (a.activityAt === undefined ? -Infinity : a.activityAt) - (b.activityAt === undefined ? -Infinity : b.activityAt) }).forEach(function(r) {
        if (r.archived || r.disabled || r.blocked) return;
        var selected = r.repo === s.selected && now >= s.stableAt;
        if (selected && now >= age(r.summaryAt, 60000)) ensure(s, "summary", r.repo, "", "interactive", age(r.summaryAt,60000));
        else if (selected) wake=Math.min(wake,age(r.summaryAt,60000));
        var summary = s.tasks[key("summary",r.repo)];
        var activityKey = key("activity",r.repo);
        if (summary && !(s.flight && s.flight.key === activityKey)) delete s.tasks[activityKey];
        if (!summary) {
            var pinned = !selected && !(r.active > 0) && !!s.pinned[r.repo];
            var interval = selected ? 10000 : r.active > 0 ? 15000 : pinned ? 60000 : 600000;
            var group = selected ? "interactive" : r.active > 0 ? "active" : pinned ? "pinned" : "background";
            if (now >= age(r.activityAt, interval) && (group!=="background" || !backgroundQueued || s.tasks[activityKey])) {
                ensure(s, "activity",r.repo,"",group,age(r.activityAt,interval));
                if (group==="background") backgroundQueued=true;
            }
            else if (s.tasks[activityKey] && !(s.flight && s.flight.key === activityKey) && !s.tasks[activityKey].failures)
                delete s.tasks[activityKey];
            if (age(r.activityAt,interval)>now) wake=Math.min(wake,age(r.activityAt,interval));
            if (s.tasks[activityKey]) s.tasks[activityKey].group = group;
        }
        (r.runs || []).forEach(function(run) {
            if (run.status==="queued" && run.followupAt===undefined && !run.lookupError && r.repo!==s.selected) run.followupAt=now;
            if (run.awaitingFinal || run.followupAt !== undefined && run.status !== "completed" && run.status !== "in_progress")
                if (now >= age(run.followupAt,15000)) ensure(s,"run",r.repo,run.id,selected ? "interactive" : run.status==="queued" ? "background" : "active",age(run.followupAt,15000));
                else wake=Math.min(wake,age(run.followupAt,15000));
        });
        if (selected && s.inspected && s.expanded[r.repo + ":" + s.inspected]) {
            var run = runFor(s,r.repo,s.inspected), detail = s.details[r.repo + ":" + s.inspected];
            var attempt = run && (run.run_attempt || 1);
            if (detail && detail.unavailable) return;
            var final = run && run.status === "completed" && detail && detail.finalAttempt === attempt;
            if (!final && now >= age(detail && detail.jobsAt,5000)) ensure(s,"jobs",r.repo,s.inspected,"interactive",age(detail && detail.jobsAt,5000));
            else if (!final) wake=Math.min(wake,age(detail && detail.jobsAt,5000));
        }
    });
    wake=Math.min(wake,seedWatches(s,now));
    Object.keys(s.tasks).forEach(function(id) { var due=s.tasks[id].due; if (due>now) wake=Math.min(wake,due); });
    s.wakeAt=wake;
}
function seedWatches(s, now) {
    var wake=Infinity;
    Object.keys(s.watches).forEach(function(id) {
        var w=s.watches[id], taskKey=key("run",w.repo,w.run);
        if (s.flight && s.flight.key===taskKey) return;
        var at=w.checkedAt+WATCH_EVERY;
        if (now>=at) ensure(s,"run",w.repo,w.run,"active",at).group="active";
        else wake=Math.min(wake,at);
    });
    return wake;
}
function next(s, now) {
    settle(s,now);
    var watching=Object.keys(s.watches).length>0;
    if ((!s.opened && !watching) || s.flight || s.auth || now < s.cooldown) return null;
    s.starts = s.starts.filter(function(at) { return now - at < 60000 });
    if (s.starts.length >= 60 || s.starts.length && now - s.starts[s.starts.length-1] < 1000) return null;
    s.clock=now;
    if (s.opened) { if (now>=s.wakeAt) seed(s,now); }
    else {
        Object.keys(s.tasks).forEach(function(id) { var t=s.tasks[id];
            if (t.kind!=="run" || !s.watches[t.repo+":"+t.run]) delete s.tasks[id]; });
        seedWatches(s,now);
    }
    var due = Object.keys(s.tasks).map(function(id) { return s.tasks[id] }).filter(function(t) { return t.due <= now });
    due.sort(function(a,b) { return a.due === b.due ? a.order-b.order : a.due-b.due });
    var group = ["interactive","interactive","interactive","active","background"][s.slot % 5];
    var order = group === "active" ? ["active","pinned"] : [group];
    var t;
    order.concat(["interactive","active","pinned","background"]).some(function(g) {
        t = due.filter(function(x) { return x.group === g })[0]; return !!t;
    });
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
    s.wakeAt=0;
    incoming.forEach(function(run) {
        var old=runFor(s,r.repo,run.id);
        var jobs=s.tasks[key("jobs",r.repo,run.id)];
        if (old && (old.run_attempt || 1)!==(run.run_attempt || 1) && jobs) restart(s,jobs,s.clock || 0);
        if (s.opened && old && old.status!=="completed" && run.status==="completed" && s.selected===r.repo && s.inspected===String(run.id) && s.expanded[r.repo+":"+run.id])
            ensure(s,"jobs",r.repo,run.id,"interactive",s.clock || 0);
    });
    invalidateJobs(s,r,incoming);
    trimRuns(s,r,union(r.runs || [], incoming));
}
function trimRuns(s,r,runs) {
    s.wakeAt=0;
    var completed=0, old=(r.runs || []).map(function(run) { return run.id });
    r.runs=runs.sort(function(a,b) { return (a.status==="completed")-(b.status==="completed") || b.id-a.id }).filter(function(run) { return run.status!=="completed" || ++completed<=10 || kept(s,r,run) });
    old.forEach(function(id) { if (!r.runs.some(function(run) { return run.id===id })) delete s.details[r.repo+":"+id]; });
}
function kept(s,r,run) {
    return s.expanded[r.repo+":"+run.id] || r.repo===s.selected && String(run.id)===s.inspected || s.watches[r.repo+":"+run.id];
}
// ponytail: total -1 means "more than one page, count unknown" (GitLab omits X-Total above 10,000).
function hiddenCount(total,items) { return total<0 ? -1 : Math.max(0,total-items.length); }
function activity(s,r,items,now,total) {
    s.wakeAt=0;
    var ids={}; items.forEach(function(run) { ids[run.id]=true });
    var previous=r.runs || [], partial=total<0 || total>items.length, dropped={};
    mergeRuns(s,r,items);
    previous.forEach(function(run) {
        if (run.status === "in_progress" && !ids[run.id]) {
            var missing=r.runs.filter(function(x) { return x.id===run.id })[0];
            // A partial page can't tell finished from not fetched: look up only runs the user is looking at.
            if (partial && missing && !kept(s,r,missing)) dropped[run.id]=true;
            else if (missing && missing.status!=="completed") { missing.awaitingFinal=true; delete missing.followupAt; }
        }
    });
    r.runs=r.runs.filter(function(run) { return !dropped[run.id] });
    Object.keys(dropped).forEach(function(id) { delete s.details[r.repo+":"+id]; });
    items.forEach(function(run) { var cached=runFor(s,r.repo,run.id); delete cached.awaitingFinal; delete cached.followupAt; });
    r.activeFromTotal=typeof total==="number" && total>=0;
    r.active=typeof total==="number" && total>=0 ? total : items.filter(function(run) { return run.status==="in_progress" }).length;
    if (typeof total==="number") r.hidden=Object.assign({},r.hidden,{running:hiddenCount(total,items)});
    r.activityAt=now; r.checked=new Date(now).toISOString(); r.error="";
}
function complete(s,reply,now) {
    var flight=s.flight;
    if (!flight || reply.requestId!==flight.request.requestId) return false;
    // A matching reply that is no longer wanted still ends its flight, or the scheduler would wait on it forever.
    if ((!s.opened && !Object.keys(s.watches).length) || flight.generation!==s.generation) { s.flight=null; return false; }
    var t=s.tasks[flight.key]; s.flight=null;
    if (!t) return false;
    s.wakeAt=0;
    var bad=reply.data===null || typeof reply.data!=="object" || Array.isArray(reply.data)!==(t.kind!=="run")
        || Array.isArray(reply.data) && !reply.data.every(function(x) { return x && typeof x==="object" });
    if (!reply.errorType && !reply.error && bad) reply={requestId:reply.requestId,error:"GitLab helper returned invalid data",errorType:"setup"};
    if (reply.errorType==="rate" || reply.remaining===0 || reply.retryAt>now) {
        var deadline=Math.max(reply.retryAt || 0,reply.remaining===0 ? reply.resetAt || 0 : 0);
        if (deadline<=now) deadline=now+Math.min(900000,60000*Math.pow(2,s.rateFailures));
        s.cooldown=Math.max(s.cooldown,Math.min(deadline,now+3600000)); // ponytail: 1h cap, a real longer limit just 429s again
        if (reply.errorType==="rate") s.rateFailures++;
    }
    if (t.restart) { restart(s,t,now); delete t.restart; return true; }
    var r=repoFor(s,t.repo);
    if (reply.errorType || reply.error) {
        var watched=t.kind==="run" && s.watches[t.repo+":"+t.run];
        if (watched) watched.checkedAt=now;
        s.error=reply.error || "Invalid GitLab response";
        // ponytail: s.auth now means "stopped until manual refresh"; rename if a third stop reason appears
        // A setup error while closed (a crashed or missing helper) is retried like a network error: only a sign-in problem ends the watches.
        if (reply.errorType==="setup" && !s.opened) reply=Object.assign({},reply,{errorType:"network"});
        if (reply.errorType==="auth" || reply.errorType==="setup") {
            s.auth=true;
            if (!s.opened && Object.keys(s.watches).length) {
                s.events.push({type:"auth",count:Object.keys(s.watches).length}); s.watches={};
            }
        }
        if (reply.errorType==="permission") {
            if (watched) { s.events.push({type:"unavailable",watch:watched}); delete s.watches[t.repo+":"+t.run]; }
            if (t.kind==="catalogue") { s.discover=false; s.catalogueError=s.error; }
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
        if (s.watches[t.repo+":"+t.run]) s.watches[t.repo+":"+t.run].checkedAt=now;
        if (r) {
            var resolved=Object.assign({},data,{awaitingFinal:false,followupAt:now});
            mergeRuns(s,r,[resolved]);
            var running=(r.runs || []).filter(function(run) { return run.status==="in_progress" && !run.awaitingFinal }).length;
            // GitLab's total already excludes runs that left; a lookup can only add running ones it has not counted yet.
            r.active=r.activeFromTotal ? Math.max(r.active || 0,running) : running;
            if (s.opened && resolved.status==="completed" && t.repo===s.selected && t.run===s.inspected && s.expanded[t.repo+":"+t.run])
                ensure(s,"jobs",t.repo,t.run,"interactive",now);
        }
        delete s.tasks[t.key]; settle(s,now); return true;
    }
    t.items=t.kind==="catalogue" ? t.items.concat(data) : union(t.items,data);
    if (t.kind==="catalogue") {
        data.forEach(function(repo) {
            var existing=repoFor(s,repo.repo);
            if (existing) { Object.assign(existing,repo); existing.blocked=false; existing.error=""; }
            else s.repos.push(repo);
        });
    } else if (r && t.kind==="summary") mergeRuns(s,r,data);
    if (reply.nextPage) { t.page=reply.nextPage; t.due=now; t.order=++s.order; settle(s,now); return true; }
    if (t.kind==="catalogue") {
        var names=t.items.map(function(repo) { return repo.repo });
        var gone=s.repos.filter(function(repo) { return names.indexOf(repo.repo)<0 }).map(function(repo) { return repo.repo });
        Object.keys(s.details).forEach(function(id) { if (gone.indexOf(id.slice(0,id.lastIndexOf(":")))>=0) delete s.details[id]; });
        s.repos=s.repos.filter(function(repo) { return names.indexOf(repo.repo)>=0 });
        // Most recently active first; gitlab.com cannot sort membership by activity server-side.
        s.repos.sort(function(a,b) { return String(b.lastActivity || "").localeCompare(String(a.lastActivity || "")) || names.indexOf(a.repo)-names.indexOf(b.repo) });
        s.catalogueComplete=true; s.catalogueAt=now; s.discover=false;
    } else if (r && t.kind==="activity") activity(s,r,t.items,now,reply.total);
    else if (r && t.kind==="summary") {
        t.all=union(t.all,t.items);
        if (phases[t.phase]==="running") activity(s,r,t.items,now,reply.total);
        if (typeof reply.total==="number") (t.hidden=t.hidden || {})[phases[t.phase]]=hiddenCount(reply.total,t.items);
        t.phase++; t.items=[]; t.page=1;
        if (t.phase<phases.length) { t.due=now; t.order=++s.order; settle(s,now); return true; }
        var keep=(r.runs || []).filter(function(run) { return run.awaitingFinal || kept(s,r,run) });
        trimRuns(s,r,union(t.all,keep));
        r.hidden=t.hidden || {};
        r.summaryAt=now;
    } else if (r && t.kind==="jobs") {
        var run=runFor(s,t.repo,t.run);
        s.details[t.repo+":"+t.run]={jobs:t.items,updated:new Date(now).toISOString(),jobsAt:now,
            finalAttempt:run && run.status==="completed" && t.items.every(function(job) { return job.status==="completed" }) ? run.run_attempt || 1 : 0};
    }
    delete s.tasks[t.key]; settle(s,now); return true;
}
