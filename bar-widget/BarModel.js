function view(text, now, vertical) {
    var glyph="\uF296";
    var none={state:"none",label:glyph,tooltip:"Open GitLab Pipelines to load",
        accessible:"Open GitLab Pipelines to load",active:false,dimmed:true,recheckAt:0};
    var status;
    try { status=JSON.parse(text); } catch (error) { return none; }
    if (!status || status.version !== 1 || !["none","ok","stopped","rate"].includes(status.state)) return none;
    function count(value) {
        var n=Number(value);
        return isFinite(n) ? Math.max(0,Math.floor(n)) : 0;
    }
    function clock(t) {
        var d=new Date(t);
        return ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2);
    }
    var running=count(status.running), failed=count(status.failed);
    var countsAt=count(status.countsAt), cooldownUntil=count(status.cooldownUntil);
    var reason=typeof status.reason==="string" ? status.reason.slice(0,120) : "";
    var host=typeof status.host==="string" ? status.host.slice(0,100) : "";
    var state=status.state;
    if (state==="rate" && cooldownUntil<=now) state=countsAt>0 ? "ok" : "none";
    var hostLines=[], recheckAt=state==="rate" ? cooldownUntil : 0;
    if (Array.isArray(status.hosts) && status.hosts.length>1) {
        recheckAt=0;
        status.hosts.forEach(function(item) {
            if (!item || typeof item !== "object") return;
            var h=typeof item.host==="string" ? item.host.slice(0,100) : "";
            var s=["none","ok","stopped","rate"].includes(item.state) ? item.state : "none";
            var r=count(item.running), f=count(item.failed);
            var c=count(item.countsAt), u=count(item.cooldownUntil);
            var rs=typeof item.reason==="string" ? item.reason.slice(0,120) : "";
            if (s==="rate" && u<=now) s=c>0 ? "ok" : "none";
            if (s==="rate" && u>now) recheckAt=recheckAt ? Math.min(recheckAt,u) : u;
            if (s==="ok") hostLines.push(h+": ●"+r+" ✕"+f);
            else if (s==="rate") hostLines.push(h+": paused until "+clock(u));
            else if (s==="stopped") hostLines.push(h+": stopped"+(rs ? " — "+rs : ""));
            else hostLines.push(h+": no data");
        });
    }
    if (state==="none") {
        if (!hostLines.length) return none;
        var noneLines=[none.tooltip].concat(hostLines);
        return {state:"none",label:glyph,tooltip:noneLines.join("\n"),
            accessible:noneLines.join(", "),active:false,dimmed:true,recheckAt:recheckAt};
    }
    var parts=[glyph];
    if (state==="stopped") parts.push("!");
    else {
        if (running>0) parts.push("●"+running);
        if (failed>0) parts.push("✕"+failed);
    }
    var lines=[];
    if (state==="stopped") lines.push("GitLab Pipelines stopped"+(reason ? ": "+reason : "")+". Open the panel to fix it.");
    else {
        if (state==="rate") lines.push("GitLab paused until "+clock(cooldownUntil));
        if (state==="ok" || countsAt>0) {
            lines.push("GitLab Pipelines"+(host ? " · "+host : ""));
            lines.push(running+" running "+(running===1 ? "pipeline" : "pipelines")+", "+failed+" failed "+(failed===1 ? "project" : "projects"));
            if (countsAt>0) lines.push("Project counts from "+clock(countsAt)+"; watched pipelines are live");
        }
    }
    lines=lines.concat(hostLines);
    return {state:state,label:parts.join(vertical ? "\n" : " "),tooltip:lines.join("\n"),
        accessible:lines.join(", "),active:state==="stopped" || failed>0,
        dimmed:state==="rate",recheckAt:recheckAt};
}
