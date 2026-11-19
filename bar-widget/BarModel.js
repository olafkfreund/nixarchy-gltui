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
    var running=count(status.running), failed=count(status.failed);
    var countsAt=count(status.countsAt), cooldownUntil=count(status.cooldownUntil);
    var reason=String(status.reason || "").slice(0,120);
    var state=status.state;
    if (state==="rate" && cooldownUntil<=now) state=countsAt>0 ? "ok" : "none";
    if (state==="none") return none;
    function clock(t) {
        var d=new Date(t);
        return ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2);
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
            lines.push("GitLab Pipelines"+(status.host ? " · "+status.host : ""));
            lines.push(running+" running "+(running===1 ? "pipeline" : "pipelines")+", "+failed+" failed "+(failed===1 ? "project" : "projects"));
            if (countsAt>0) lines.push("Project counts from "+clock(countsAt)+"; watched pipelines are live");
        }
    }
    return {state:state,label:parts.join(vertical ? "\n" : " "),tooltip:lines.join("\n"),
        accessible:lines.join(", "),active:state==="stopped" || failed>0,
        dimmed:state==="rate",recheckAt:state==="rate" ? cooldownUntil : 0};
}
