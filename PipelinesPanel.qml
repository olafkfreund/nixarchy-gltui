import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "PipelinesModel.js" as Model
import "Polling.js" as Polling

Item {
    id: root
    property var shell: null
    property var manifest: null
    property bool opened: false
    property bool configured: false
    property var pendingOpen: []
    property var targetScreen: null
    property var repos: []
    property var details: ({})
    property var expanded: ({})
    property var shown: ({})
    property var searchCollapsed: ({})
    property var entries: []
    property int cursor: 0
    property int zoomPercent: 100
    property bool helpOpen: false
    property string helpText: ""
    property string notice: ""
    property var copyCommand: ["wl-copy", "--"]
    property var pinState: ({})
    property string pinsError: ""
    property var pinned: ({})
    property string pinsLoadHost: ""
    property int pinsLoadLife: 0
    property bool pinsLoadStarted: false
    property var pinsQueue: ({})
    property bool pinsSaveStarted: false
    property var sessionPins: ({})
    property var pinsCommand: ["python3"]
    property int copySerial: 0
    property var traceCommand: ["python3", localPath("menu.py"), "trace"]
    property bool traceStarted: false
    property int traceSerial: 0
    property bool copyStarted: false
    property string copyLabel: ""
    readonly property string searchHint: "↑↓ select  Enter open  Tab navigate  Esc clear"
    readonly property string listHint: "↑↓ move  ←→ expand  g/G ends  / search  e failure  y/Y copy  p pin  t log  w watch" +
        (actionsFor(current ? current.host : host) ? "  a/c/x/n act" : "") + "  m MRs  o GitLab  ? help  q close"
    readonly property string mrHint: "↑↓ move  Enter pipeline  / search  y copy  o GitLab  r refresh  m projects  ? help  q close"
    property string view: "projects"
    property bool switching: false
    property var viewState: ({projects: {filter: "", openHost: "", collapsed: {}, key: ""}, mrs: {filter: "", collapsed: {}, key: ""}})
    property bool actionsOn: false
    property var confirm: null
    property var pendingAction: null
    property bool actionBusy: false
    property int actionId: 0
    property int actionSerial: 0
    property bool actionStarted: false
    property bool actionFailed: false
    property int hostEpoch: 0
    property int hostLife: 1
    property int lifeSerial: 1
    property var more: []
    property int panelSlot: 0
    property var lastServed: ({})
    property var hostBudget: ({})
    property var hostsList: []
    property var ignoredHosts: []
    property string loggedIgnored: ""
    property string openHost: ""
    property bool settingOpen: false
    property string missedAction: ""
    property bool missedFailed: false
    property var actionCommand: ["python3", localPath("gitlab.py"), "act"]
    readonly property real borderWidth: Math.max(1, Style.space(2))
    property alias filterText: searchField.text
    readonly property bool filtering: searchField.activeFocus
    property string error: ""
    property string configError: ""
    property string host: "gitlab.com"
    property string statusPath: {
        var runtime = Quickshell.env("XDG_RUNTIME_DIR")
        var display = Quickshell.env("WAYLAND_DISPLAY")
        return runtime && display ? runtime + "/omarchy-gitlab-pipelines-" + display + ".json" : ""
    }
    property string statusInstance: ""
    property string lastStatus: ""
    property string pendingStatus: ""
    onStatusPathChanged: { lastStatus = ""; pendingStatus = "" }
    property string updated: ""
    property var polling: Polling.create()
    readonly property bool watching: pollers().some(function(p) { return Object.keys(p.state.watches || {}).length > 0 })
    property var notifyCommand: ["notify-send", "--app-name=GitLab Pipelines"]
    property var notifyQueue: []
    property var missedNotices: []
    property bool notifyStarted: false
    property var watched: ({})
    property var requestInfo: null
    property bool workerBusy: false
    property bool helperStarted: false
    property double now: Date.now()
    readonly property bool discoveryComplete: multi() ? !!configError || pollers().every(function(p) { return p.state.catalogueComplete || !!p.state.error || !!p.state.catalogueError || !!p.state.auth }) : polling.catalogueComplete
    readonly property string cooldownText: multi() ? pollers().filter(function(p) { return now < p.state.cooldown }).map(function(p) { return p.host + ": GitLab paused until " + new Date(p.state.cooldown).toLocaleTimeString() }).join("\n") : now < polling.cooldown ? "GitLab paused until " + new Date(polling.cooldown).toLocaleTimeString() : ""
    readonly property string errorHintText: multi() ? pollers().map(function(p) { return errorHint(p.state.error || p.state.catalogueError || "", p.state.catalogueError || "", !!p.state.auth, filtering) }).filter(function(x) { return !!x })[0] || "" : errorHint(error, polling.catalogueError || "", !!polling.auth, filtering)
    readonly property int checkedCount: repos.filter(function(repo) { return !!repo.checked || repo.archived || repo.disabled }).length
    readonly property var current: entries[cursor] || null
    readonly property string helper: localPath("gitlab.py")
    function localPath(name) { return decodeURIComponent(Qt.resolvedUrl(name).toString().replace(/^file:\/\//, "")) }
    function pollers() { return [{host: host, life: hostLife, state: polling}].concat(more) }
    function pollerFor(h, life) { return pollers().filter(function(p) { return p.host === h && (life === undefined || p.life === life) })[0] || null }
    function setState(i, s) {
        if (i === 0) { polling = s; return }
        var next = more.slice()
        next[i - 1] = Object.assign({}, next[i - 1], {state: s})
        more = next
    }
    function multi() { return more.length > 0 }
    // Keys are "repo:<host>|path" or "<host>|path:...": match the prefix only, so gitlab.com never claims corp.gitlab.com.
    function ownsKey(k, h) { return k.indexOf("repo:" + h + "|") === 0 || k.indexOf(h + "|") === 0 }
    function qOf(h) { return multi() ? h + "|" : "" }
    function actionsFor(h) { return !configError && hostsList.some(function(x) { return x.host === h && x.actions }) }
    function stateOf(row) { var p = pollerFor(row ? row.host : host); return p ? p.state : null }
    function errorLines() {
        if (!multi()) return error ? [error + (errorHintText ? " — " + errorHintText : "")] : []
        if (configError) return [configError]
        return pollers().map(function(p) {
            var s = p.state, e = s.error || (view === "mrs" ? s.mrs.error : s.catalogueError)
            var hint = errorHint(e || "", s.catalogueError || "", !!s.auth, filtering)
            if (e) return p.host + ": " + e + (hint ? " — " + hint : "")
            if (now < s.cooldown) return p.host + ": GitLab paused until " + new Date(s.cooldown).toLocaleTimeString()
            return ""
        }).filter(function(x) { return !!x })
    }
    onFilterTextChanged: {
        if (switching) return
        if (!settingOpen) openHost = ""
        searchCollapsed = ({})
        rebuild(true)
        selectionChanged(false)
    }

    function zf(v) { return Math.round(v * zoomPercent / 100) }
    function zs(v) { return v * zoomPercent / 100 }
    // Ctrl + = / + zooms in, Ctrl + - out, Ctrl + 0 resets; Alt or Meta (AltGr, Super) is not a zoom key.
    function zoomKey(event) {
        if (!(event.modifiers & Qt.ControlModifier) || (event.modifiers & (Qt.AltModifier | Qt.MetaModifier))) return false
        var dir = event.key === Qt.Key_Equal || event.key === Qt.Key_Plus ? 1 : event.key === Qt.Key_Minus ? -1 : event.key === Qt.Key_0 ? 0 : null
        if (dir === null) return false
        zoomPercent = Model.zoomStep(zoomPercent, dir)
        return true
    }
    // Keep the cursor row in view once the zoomed layout has run; rebuild() is not safe here (it reads list geometry).
    onZoomPercentChanged: {
        zoomSettle.restart()
        Qt.callLater(function() {
            list.forceLayout()
            if (cursor >= 0 && cursor < list.count) list.positionViewAtIndex(cursor, ListView.Contain)
        })
    }
    // The footer settles after the zoom's callLater; only that settle, or an error strip change (keepOnResize), may move the view, not other resizes or scrolling.
    Timer { id: zoomSettle; interval: 300 }
    // Test hooks for tests/qml-smoke.py.
    readonly property Item cardItem: card
    readonly property Item listItem: list
    readonly property Item searchItem: searchField
    readonly property bool notifyBusy: notifyProc.running
    readonly property Item hintItem: hint
    readonly property Item zoomItem: zoomLabel
    readonly property Item hairlineItem: hairline
    readonly property Item errorItem: errorStrip
    readonly property Item emptyItem: emptyLabel
    readonly property Item placeholderItem: placeholder
    readonly property Item helpItem: helpOverlay
    readonly property Item helpFlick: helpFlickable
    readonly property alias footerHint: hint.text

    function open(payload) {
        root.now = Date.now()
        var monitor = Hyprland.focusedMonitor
        targetScreen = null
        for (var i = 0; i < Quickshell.screens.length; i++)
            if (monitor && Quickshell.screens[i].name === monitor.name) targetScreen = Quickshell.screens[i]
        if (!opened) pollers().forEach(function(p) { Polling.open(p.state, Date.now()) })
        opened = true
        if (configured) applyOpen(payload)
        else pendingOpen = pendingOpen.concat([payload])
        if (pinsError) { notify(pinsError); pinsError = "" }
        showMissed()
        if (missedAction) {
            // Keep missed watch notices from showMissed() beside the action result.
            notify((notice ? notice + " · " : "") + missedAction, 10000)
            actionFailed = missedFailed
            missedAction = ""
        }
        if (ignoredHosts.length) notify((notice ? notice + " · " : "") + "Ignored hosts: " + ignoredHosts.join(", ") + "; at most 4 are shown")
        selectionChanged(true)
        pump()
        Qt.callLater(function() { keys.forceActiveFocus() })
    }
    function applyOpen(payload) {
        var request = Model.openFilter(payload, multi() ? hostsList.map(function(h) { return h.host }) : host)
        if (request.filter !== null) {
            helpOpen = false
            notice = ""; noticeTimer.stop()
            // An explicit project filter always opens the projects view, even if merge requests were shown last.
            settingOpen = true
            openHost = request.host || ""
            if (view === "mrs") switchView("projects", request.filter)
            else if (filterText === request.filter) { rebuild(true); selectionChanged(false) }
            else filterText = request.filter
            settingOpen = false
        } else openHost = ""
        if (request.notice) notify(request.notice)
    }
    function markConfigured() {
        if (configured) return
        configured = true
        var queued = pendingOpen
        pendingOpen = []
        for (var i = 0; i < queued.length; i++) applyOpen(queued[i])
        applyPins()
        showMissed()
    }
    function showMissed() {
        if (!missedNotices.length) return
        notify(missedNotices.join(" · "))
        missedNotices = []
    }
    function missed(m) { missedNotices = missedNotices.concat([m.summary + ": " + m.body]) }
    function drainEvents() {
        var queue = notifyQueue.slice()
        pollers().forEach(function(p) {
            p.state.events.forEach(function(e) { queue.push(Model.watchMessage(e, p.host, p.host, multi() ? p.host : undefined)) })
            p.state.events = []
        })
        notifyQueue = queue
        sendNext()
    }
    function sendNext() {
        if (notifyProc.running || !notifyQueue.length) return
        var queue = notifyQueue.slice()
        var m = queue.shift()
        notifyQueue = queue
        notifyProc.message = m
        notifyStarted = false
        notifyProc.command = notifyCommand.concat([m.summary, m.body])
        notifyProc.running = true
    }
    function toggleWatch() {
        if (!current || current.kind === "repo") { notify("Select a pipeline to watch"); return }
        if (current.kind === "trigger") { notify("Watch the parent pipeline row instead"); return }
        var s = stateOf(current)
        if (!s) return
        var others = pollers().reduce(function(n, p) { return n + (p.state === s ? 0 : Object.keys(p.state.watches || {}).length) }, 0)
        var code = Polling.watch(s, current.repo, current.run, Date.now(), others)
        var r = (s.repos.filter(function(x) { return x.repo === current.repo })[0] || {}).runs || []
        var run = r.filter(function(x) { return String(x.id) === current.run })[0]
        notify(Model.watchNotice(code, current.repo, run ? run.run_number : current.run, multi() ? current.host : undefined))
        adopt()
    }
    function close() {
        opened = false
        helpOpen = false
        notice = ""
        noticeTimer.stop()
        copySerial++
        traceSerial++
        pollers().forEach(function(p) { Polling.close(p.state) })
        if (pollers().some(function(p) { return p.state.events.length })) { drainEvents(); adopt() }
        requestProc.running = false
        dropAction("")
    }
    function toggle() { opened ? close() : open("{}") }
    function status() {
        var out = {opened: opened, rows: entries.length, repositories: repos.length,
            checked: checkedCount, discoveryComplete: discoveryComplete, error: error, updated: updated,
            requests: polling.requests, inFlight: workerBusy, cooldown: polling.cooldown,
            lastRequest: polling.lastRequest, lastStarted: polling.lastStarted,
            filter: filterText, editing: filtering, selected: current ? current.key : "", scrollY: list.contentY,
            actionsOn: actionsOn, confirm: confirm ? confirm.text : "", actionBusy: actionBusy,
            view: view, mrs: ((polling.mrs || {}).list || []).length,
            statusPath: statusPath, statusState: lastStatus ? JSON.parse(lastStatus).state : ""}
        if (multi()) {
            var ps = pollers()
            out.hosts = ps.map(function(p) { var s = p.state; return {host: p.host,
                discoveryComplete: !!configError || s.catalogueComplete || !!s.error || !!s.catalogueError || !!s.auth,
                error: s.error || (view === "mrs" ? s.mrs.error : s.catalogueError) || "", requests: s.requests,
                cooldown: s.cooldown, lastRequest: s.lastRequest, lastStarted: s.lastStarted,
                actionsOn: actionsFor(p.host), mrs: ((s.mrs || {}).list || []).length} })
            out.error = error
            out.requests = out.hosts.reduce(function(n, h) { return n + h.requests }, 0)
            out.mrs = out.hosts.reduce(function(n, h) { return n + h.mrs }, 0)
            out.cooldown = Math.max.apply(null, out.hosts.map(function(h) { return h.cooldown }))
            var latest = out.hosts.slice().sort(function(a, b) { return b.lastStarted - a.lastStarted })[0]
            out.lastStarted = latest.lastStarted; out.lastRequest = latest.lastRequest
            out.actionsOn = out.hosts.some(function(h) { return h.actionsOn })
        }
        return JSON.stringify(out)
    }
    function publishStatus() {
        if (!statusPath || !statusInstance) return
        var payload = Model.barStatus(polling, configError, host, statusInstance, Date.now(), multi() ? more : undefined)
        var writtenAt = payload.writtenAt
        delete payload.writtenAt
        var next = JSON.stringify(payload)
        if (next === lastStatus) return
        pendingStatus = next
        payload.writtenAt = writtenAt
        statusFile.setText(JSON.stringify(payload) + "\n")
    }

    function rebuild(resetSelection, selectKey) {
        if (view === "projects") shown = Model.merge(expanded, Model.autoOpen(repos, filterText, openHost), searchCollapsed)
        var key = selectKey !== undefined ? selectKey : current ? current.key : ""
        var topIndex = list.indexAt(1, list.contentY + 1)
        var topItem = list.itemAtIndex(topIndex)
        var topKey = entries[topIndex] ? entries[topIndex].key : ""
        var topOffset = topItem ? topItem.y - list.contentY : 0
        var next = view === "mrs" ? pollers().reduce(function(rows, p) { return rows.concat(Model.mrRows(p.state.mrs, filterText, now, p.host, p.state.mrSelected, qOf(p.host))) }, [])
            : Model.rows(repos, shown, details, filterText, now, pinned, watched, openHost)
        var structureChanged = Model.syncRows(visibleRows, next)
        entries = next
        cursor = resetSelection ? 0 : Model.selection(entries, key, cursor)
        if (resetSelection) {
            list.forceLayout()
            list.positionViewAtBeginning()
        } else if (structureChanged && topKey) {
            var index = entries.findIndex(function(row) { return row.key === topKey })
            list.forceLayout()
            if (index >= 0) {
                list.positionViewAtIndex(index, ListView.Beginning)
                list.forceLayout()
                var item = list.itemAtIndex(index)
                if (item) list.contentY = item.y - topOffset
                list.returnToBounds()
            }
        }
    }
    // Saves this view's state, shows `next` with its saved filter, collapsed set and row (or the given ones).
    function switchView(next, filter, key) {
        var saved = Object.assign({}, viewState)
        saved[view] = {filter: filterText, openHost: openHost, collapsed: searchCollapsed, key: current ? current.key : ""}
        viewState = saved
        var target = saved[next]
        switching = true
        view = next
        pollers().forEach(function(p) { Polling.view(p.state, next === "mrs", Date.now()) })
        openHost = next === "projects" ? (filter !== undefined ? settingOpen ? openHost : "" : target.openHost || "") : ""
        filterText = filter !== undefined ? filter : target.filter
        searchCollapsed = filter !== undefined ? ({}) : target.collapsed
        switching = false
        cursor = 0
        adopt(key !== undefined ? key : target.key)
        list.forceLayout()
        list.positionViewAtIndex(cursor, ListView.Contain)
        selectionChanged(true)
        pump()
    }
    function toggleView() { switchView(view === "mrs" ? "projects" : "mrs") }
    // Keys that mean a project, pipeline or job; in the merge-request view they only explain themselves.
    function mrKey(event, plain, shift) {
        var letters = [Qt.Key_P, Qt.Key_T, Qt.Key_W, Qt.Key_E, Qt.Key_A, Qt.Key_C, Qt.Key_X, Qt.Key_N]
        if (!plain || !((!shift && letters.indexOf(event.key) >= 0) || (shift && event.key === Qt.Key_Y) ||
            (!shift && (event.key === Qt.Key_Left || event.key === Qt.Key_H)))) return false
        notify("Not on a merge request; press Enter for its pipeline")
        return true
    }
    function jumpMr() {
        var row = current
        if (!row) return
        if (row.kind === "more") { notify("Open it with o"); return }
        var s = stateOf(row)
        var st = s && s.mrs.status[row.mrKey]
        if (!st) { notify("Not checked yet"); return }
        if (st.state === "unavailable") { notify("Merge request unavailable; o opens it"); return }
        if (st.state === "hidden") { notify("Pipeline hidden"); return }
        if (st.state === "none" || !st.pipeline) { notify("No pipeline yet"); return }
        var pipe = st.pipeline
        var repo = s.repos.filter(function(r) { return r.id === pipe.project_id && !r.archived && !r.disabled })[0]
        if (!repo) { notify("Project not in your list; o opens the merge request"); return }
        var next = Object.assign({}, expanded)
        next["repo:" + qOf(row.host) + repo.repo] = true
        next[qOf(row.host) + repo.repo + ":" + pipe.id] = true
        expanded = next
        var local = {}
        Object.keys(next).forEach(function(k) { if (!multi() || k.indexOf("repo:" + qOf(row.host)) === 0 || k.indexOf(qOf(row.host)) === 0) local[k.replace(qOf(row.host), "")] = next[k] })
        Polling.jump(s, repo.repo, pipe, local, Date.now())
        openHost = ""
        switchView("projects", "", qOf(row.host) + repo.repo + ":" + pipe.id)
    }
    function move(delta) {
        cursor = Math.max(0, Math.min(entries.length - 1, cursor + delta))
        list.positionViewAtIndex(cursor, ListView.Contain)
        selectionChanged(false)
    }
    function nextFailure() {
        var i = Model.nextFailure(entries, cursor)
        if (i < 0) { notify("No failures in the list"); return }
        cursor = i
        list.positionViewAtIndex(i, ListView.Contain)
        selectionChanged(false)
    }
    function notify(t, ms) { actionFailed = false; notice = t; noticeTimer.interval = ms || 2000; noticeTimer.restart() }
    onActionsOnChanged: if (!actionsOn && !multi()) dropAction("Actions are off")

    function clock(t) {
        var d = new Date(t)
        return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2)
    }
    function pausedText(s) { return "GitLab paused until " + clock((s || polling).cooldown) + "; try again then" }
    function rawJob(row) {
        var s = stateOf(row)
        var d = s && s.details[row.repo + ":" + row.run]
        return ((d && d.jobs) || []).filter(function(j) { return String(j.id) === row.job })[0]
    }
    function startAction(key) {
        var row = current
        if (!actionsFor(row ? row.host : host)) { notify("Actions are off: set \"actions\": true for this plugin in shell.json"); return }
        if (actionBusy) { notify("An action is already running"); return }
        var s = stateOf(row)
        var run = row && (row.kind === "run" || row.kind === "job") ? Polling.runFor(s, row.repo, row.run) : null
        var job = row && row.kind === "job" ? rawJob(row) : null
        var a = Model.actionFor(key, row, row && row.kind === "job" ? job : run)
        if (!a.action) { notify(a.reason); return }
        if (row.kind === "job" && !run) { notify("Select the row again"); return }
        if (Date.now() < s.cooldown) { notify(pausedText(s)); return }
        var d = Model.describe(a.action, row.repo, run, job, multi() ? row.host : undefined)
        var jobAction = a.action.slice(-3) === "job"
        var p = pollerFor(row.host)
        confirm = {action: a.action, host: row.host, life: p.life, epoch: hostEpoch, repo: row.repo, run: String(row.run),
            job: jobAction ? String(row.job) : "", ref: a.action === "new-pipeline" ? String(run.ref) : "",
            source: a.action === "new-pipeline" ? String(run.source || "") : "", text: d.confirm, done: d.done}
    }
    function confirmAction() {
        pendingAction = confirm
        confirm = null
        actionBusy = true
        sendAction()
    }
    function confirmKey(e) {
        e.accepted = true
        if (e.key === Qt.Key_Y && e.modifiers === Qt.NoModifier && !e.isAutoRepeat) confirmAction()
        else if (e.key === Qt.Key_Escape) dropAction("Nothing was sent")
    }
    function dropAction(text) {
        confirm = null
        pendingAction = null
        actionWait.stop()
        actionBusy = actionProc.running
        if (text) notify(text)
    }
    function sendAction() {
        var t = pendingAction
        if (!t) return
        if (configError) { dropAction("Actions are off"); return }
        var p = pollerFor(t.host, t.life)
        if (!p || !multi() && t.epoch !== hostEpoch) { dropAction("Host changed; nothing was sent"); return }
        if (!actionsFor(t.host)) { dropAction("Actions are off"); return }
        var s = p.state
        if (Date.now() < s.cooldown) { dropAction(pausedText(s)); return }
        var wait = 1000 - (Date.now() - Math.max(s.lastStarted || 0, s.writeAt || 0))
        if (wait > 0) { actionWait.interval = wait; actionWait.restart(); return }
        actionId = ++actionSerial
        actionStarted = false
        var task = {action: t.action, host: t.host, repo: t.repo, run: t.run, requestId: actionId}
        if (t.job) task.job = t.job
        if (t.ref) { task.ref = t.ref; task.source = t.source }
        actionProc.command = actionCommand.concat([JSON.stringify(task)])
        actionProc.epoch = t.epoch
        actionProc.life = t.life
        actionProc.host = t.host
        actionProc.requestId = actionId
        actionProc.target = t
        pendingAction = null
        actionProc.running = true
        Polling.writeStarted(s, Date.now())
    }
    // Reads only the snapshot on actionProc: close, setting off and a host change may have cleared the rest.
    function finishAction(code, text) {
        var target = actionProc.target
        var r = Model.actionReply(text, code, actionProc.requestId)
        actionBusy = false
        var p = pollerFor(actionProc.host, actionProc.life)
        var same = !!p && (multi() || actionProc.epoch === hostEpoch)
        if (same) {
            Polling.noteWrite(p.state, r, Date.now())
            if (r.ok) Polling.touch(p.state, target.repo, target.run, Date.now())
            adopt(); pump()
        }
        var msg = r.error || "GitLab helper failed; see the shell log"
        if (r.ok) {
            msg = target.done
            if (same && Date.now() < p.state.cooldown) msg += " · refresh waits until " + clock(p.state.cooldown)
            if (r.created && r.created.iid) msg += " · new pipeline #" + r.created.iid
        }
        if (!same || multi() && !r.ok) msg = "on " + actionProc.host + ": " + msg
        if (opened) { notify(msg, 10000); actionFailed = !r.ok }
        else { missedAction = msg; missedFailed = !r.ok }
    }
    function copy(what) {
        var r = Model.copyText(current, what)
        if (!r.text && view === "mrs" && current && !current.url) r.label = "No link"
        if (!r.text) { notify(r.label); return }
        if (copyProc.running) return
        copyStarted = false
        copyLabel = r.label
        copyProc.serial = copySerial
        copyProc.command = copyCommand.concat([r.text])
        copyProc.running = true
    }
    function trace() {
        if (current && current.kind === "trigger") { notify("Job logs are not available for a trigger row"); return }
        if (!current || current.kind !== "job" || !current.job) { notify("Select a job to open its log"); return }
        if (traceProc.running) return
        traceStarted = false
        traceProc.serial = traceSerial
        traceProc.command = traceCommand.concat([current.host, current.repo, current.job])
        traceProc.running = true
    }
    function toggleHelp() {
        helpOpen = !helpOpen
        if (helpOpen) helpFlickable.contentY = 0
        if (helpOpen && !helpText && !helpProc.running) helpProc.running = true
    }
    function scrollHelp(delta) {
        var f = helpFlickable
        f.contentY = Math.max(0, Math.min(Math.max(0, f.contentHeight - f.height), f.contentY + delta))
    }
    function expand(collapse) {
        var row = current
        if (!row) return
        if (view === "mrs") { jumpMr(); return }
        var next = Object.assign({}, expanded)
        var collapsed = Object.assign({}, searchCollapsed)
        var expandable = ["repo", "run", "stage"].indexOf(row.kind) >= 0
        if (collapse || expandable) {
            if (expandable && shown[row.key]) {
                delete next[row.key]
                if (row.kind === "repo" && filterText) collapsed[row.key] = true
            } else if (collapse) {
                cursor = Model.selection(entries, row.parent, cursor)
                list.positionViewAtIndex(cursor, ListView.Contain)
                selectionChanged(false)
                return
            } else {
                next[row.key] = true
                delete collapsed[row.key]
            }
        }
        expanded = next
        searchCollapsed = collapsed
        rebuild()
        selectionChanged(true)
        pump()
    }
    function applyPins() {
        if (!configured) return
        var map = {}
        pollers().forEach(function(p) {
            var pin = pinState[p.host] || {config: [], saved: []}
            var result = Model.pins(pin.config, pin.saved)
            result.names.forEach(function(n) { map[qOf(p.host) + n] = true })
            Polling.pin(p.state, result.names)
        })
        pinned = map
        adopt()
    }
    function loadPins() {
        if (pinsLoad.running) return
        var p = pollers().filter(function(x) { var pin = pinState[x.host]; return pin && !pin.loaded })[0]
        if (!p) return
        pinsLoadHost = p.host
        pinsLoadLife = p.life
        pinsLoadStarted = false
        pinsLoad.command = pinsCommand.concat([helper, "pins", JSON.stringify({host: p.host})])
        pinsLoad.running = true
    }
    function finishPinsLoad(code, text) {
        var p = pollerFor(pinsLoadHost, pinsLoadLife)
        if (!p) { Qt.callLater(loadPins); return }
        var reply = null
        try { reply = JSON.parse(text) } catch (e) {}
        var pin = Object.assign({}, pinState[p.host])
        pin.loadFailed = !(code === 0 && reply && Array.isArray(reply.pins))
        if (!pin.loadFailed) pin.saved = reply.pins
        else {
            pin.saved = []
            pinsError = "Pins not loaded: " + (reply && reply.error || "helper failed")
        }
        var own = sessionPins[p.host.toLowerCase()]
        if (own) { pin.saved = own; pin.loadFailed = false }
        pin.loaded = true
        var changed = Object.assign({}, pinState)
        changed[p.host] = pin
        pinState = changed
        applyPins()
        Qt.callLater(loadPins)
    }
    function togglePin() {
        if (!current) return
        var h = current.host, pin = pinState[h] || {config: [], saved: [], loaded: false, loadFailed: false}
        if (!pin.loaded) { notify("Pins are still loading"); return }
        // A save after a failed load would replace this host's saved pins with only the new one.
        if (pin.loadFailed) { notify("Pins not loaded; trying again"); pin.loaded = false; var retry = Object.assign({}, pinState); retry[h] = pin; pinState = retry; loadPins(); return }
        var r = Model.togglePin(current.repo, pin.config, pin.saved)
        notify(r.notice)
        if (r.saved) {
            pin.saved = r.saved
            var changed = Object.assign({}, pinState)
            changed[h] = pin
            pinState = changed
            var s = Object.assign({}, sessionPins)
            s[h.toLowerCase()] = r.saved
            sessionPins = s
            applyPins()
            savePins(h, r.saved)
            list.positionViewAtIndex(cursor, ListView.Contain)
        }
    }
    function savePins(h, names) {
        var q = Object.assign({}, pinsQueue)
        q[h.toLowerCase()] = names
        pinsQueue = q
        nextSave()
    }
    function nextSave() {
        if (pinsSave.running) return
        var h = Object.keys(pinsQueue)[0]
        if (h === undefined) return
        var names = pinsQueue[h]
        var q = Object.assign({}, pinsQueue)
        delete q[h]
        pinsQueue = q
        pinsSaveStarted = false
        pinsSave.command = pinsCommand.concat([helper, "pins", JSON.stringify({host: h, save: names})])
        pinsSave.running = true
    }
    function finishPinsSave(code, text) {
        var reply = null
        try { reply = JSON.parse(text) } catch (e) {}
        if (!(code === 0 && reply && Array.isArray(reply.pins)))
            notify("Pins not saved: " + (reply && reply.error || "helper failed"))
        Qt.callLater(nextSave)
    }
    function configure(text) {
        try {
            var config = JSON.parse(text)
            var entry = (config.plugins || []).filter(function(p) { return p.id === "olafkfreund.gitlab-pipelines" })[0]
            var parsed = Model.hostConfig(entry)
            if (parsed.error) throw new Error(parsed.error)
            configError = ""
            var old = pollers(), nextHosts = parsed.hosts
            var oldMulti = multi(), newMulti = nextHosts.length > 1
            var configuredHost = nextHosts[0].host
            var hostChanged = !oldMulti && !newMulti && configuredHost !== host
            var budget = Object.assign({}, hostBudget), pins = Object.assign({}, pinState), now = Date.now()
            if (hostChanged) {
                hostEpoch++
                dropAction("Host changed; nothing was sent")
                var n = Object.keys(polling.watches || {}).length
                if (n) {
                    notifyQueue = notifyQueue.concat([Model.watchMessage({type: "host", count: n}, host, configuredHost)])
                    sendNext()
                }
                polling = Polling.resetHost(polling)
                expanded = ({}); searchCollapsed = ({}); details = ({}); updated = ""; error = ""; cursor = 0
                viewState = ({projects: {filter: "", openHost: "", collapsed: {}, key: ""}, mrs: {filter: "", collapsed: {}, key: ""}})
                hostLife = ++lifeSerial
                delete pins[host]
                old = []
            }
            old.forEach(function(p) {
                if (nextHosts.some(function(h) { return h.host === p.host })) return
                var count = Object.keys(p.state.watches || {}).length
                if (count && !hostChanged) notifyQueue = notifyQueue.concat([Model.watchMessage({type: "removed", count: count}, p.host, "", p.host)])
                budget[p.host] = {starts: p.state.starts, lastStarted: p.state.lastStarted, writeAt: p.state.writeAt, until: now + 60000}
                if (confirm && confirm.host === p.host || pendingAction && pendingAction.host === p.host) dropAction("Host changed; nothing was sent")
                delete pins[p.host]
            })
            var next = nextHosts.map(function(h) {
                var found = old.filter(function(p) { return p.host === h.host })[0]
                if (found) return found
                var s = Polling.create(), b = budget[h.host]
                if (b && now < b.until) { s.starts = b.starts; s.lastStarted = b.lastStarted; s.writeAt = b.writeAt }
                if (opened) Polling.open(s, now)
                Polling.view(s, view === "mrs", now)
                return {host: h.host, life: ++lifeSerial, state: s}
            })
            if (hostChanged) next[0] = {host: configuredHost, life: hostLife, state: polling}
            if (oldMulti !== newMulti) {
                expanded = ({}); searchCollapsed = ({}); shown = ({}); cursor = 0; openHost = ""
                viewState = ({projects: {filter: "", openHost: "", collapsed: {}, key: ""}, mrs: {filter: "", collapsed: {}, key: ""}})
                panelSlot = 0; lastServed = ({})
            } else if (newMulti) {
                var retained = {}
                Object.keys(expanded).forEach(function(k) { if (next.some(function(p) { return ownsKey(k, p.host) })) retained[k] = expanded[k] })
                expanded = retained
                retained = {}
                Object.keys(searchCollapsed).forEach(function(k) { if (next.some(function(p) { return ownsKey(k, p.host) })) retained[k] = searchCollapsed[k] })
                searchCollapsed = retained
            }
            host = configuredHost
            hostLife = next[0].life
            polling = next[0].state
            more = next.slice(1)
            hostsList = nextHosts
            actionsOn = !!nextHosts[0].actions
            nextHosts.forEach(function(h, i) {
                var s = next[i].state, names = h.projects
                if (!s.repos.length && names.length) {
                    s.wakeAt = 0
                    s.repos = names.filter(function(name) { return Model.validProject(name) }).map(function(name) { return {repo: name} })
                }
                var pin = Object.assign({config: [], saved: [], loaded: false, loadFailed: false}, pins[h.host] || {})
                pin.config = h.pinned
                pins[h.host] = pin
                if (pin.config.filter(function(name) { return Model.validProject(name) }).length > 10) console.warn("GitLab Pipelines: only the first 10 pins apply")
            })
            pinState = pins
            if (confirm && !actionsFor(confirm.host) || pendingAction && !actionsFor(pendingAction.host)) dropAction("Actions are off")
            var ignored = parsed.ignored.join("\u0000")
            if (ignored && ignored !== loggedIgnored) console.warn("GitLab Pipelines: ignored hosts " + parsed.ignored.join(", "))
            loggedIgnored = ignored
            ignoredHosts = parsed.ignored
            hostBudget = budget
            if (notifyQueue.length) sendNext()
            adopt()
            applyPins()
            loadPins()
        } catch (e) { configError = error = "Configuration: " + e.message; actionsOn = false; dropAction("") }
        markConfigured()
        publishStatus()
    }
    function selectionChanged(immediate) {
        if (!polling) return
        pollers().forEach(function(p) {
            var selected = current && current.host === p.host && view === "projects"
            var local = shown
            if (multi()) {
                local = {}
                Object.keys(shown).forEach(function(k) { if (ownsKey(k, p.host)) local[k.replace(p.host + "|", "")] = shown[k] })
            }
            Polling.select(p.state, selected ? current.repo : "", selected ? current.run : "", local, Date.now(), immediate)
            if (view === "mrs") Polling.selectMr(p.state, current && current.host === p.host && current.kind === "mr" ? current.mrKey : "")
        })
    }
    function adopt(selectKey) {
        var all = pollers(), rs = [], ds = {}, ws = {}, lines = []
        all.forEach(function(p) {
            var q = qOf(p.host), s = p.state
            s.repos.forEach(function(r) { rs.push(Object.assign({}, r, {host: p.host, q: q})) })
            Object.keys(s.details).forEach(function(k) { ds[q + k] = s.details[k] })
            Object.keys(s.watches || {}).forEach(function(k) { ws[q + k] = true })
            var e = s.error || (view === "mrs" ? s.mrs.error : s.catalogueError)
            if (e) lines.push(multi() ? p.host + ": " + e : e)
        })
        repos = rs
        details = ds
        watched = ws
        error = configError || lines[0] || ""
        // Reassign the state reference to notify bindings after pure-JS mutations.
        polling = Object.assign({}, polling)
        if (more.length) more = more.map(function(p) { return Object.assign({}, p, {state: Object.assign({}, p.state)}) })
        rebuild(false, selectKey)
        if (pollers().some(function(p) {
            var chosen = current && current.host === p.host
            return view === "mrs" ? (chosen && current.kind === "mr" ? current.mrKey : "") !== p.state.mrSelected :
                (chosen ? current.repo : "") !== p.state.selected || (chosen ? current.run || "" : "") !== p.state.inspected
        })) selectionChanged(false)
        publishStatus()
    }
    function refresh(catalogue) {
        selectionChanged(true)
        pollers().forEach(function(p) { if (catalogue || !multi() || (current ? current.host : host) === p.host) Polling.manual(p.state, Date.now(), !!catalogue) })
        pump()
    }
    function pump() {
        if (configError || workerBusy || (!opened && !watching)) return
        var request = null, chosen = null, at = Date.now()
        if (!multi()) { request = Polling.next(polling, at); chosen = pollers()[0] }
        else {
            var order = Polling.orderFor(panelSlot), groups = order.concat(["interactive", "active", "pinned", "background"])
            var offers = pollers().map(function(p) { return {poller: p, task: Polling.choose(p.state, at, order)} })
            for (var g = 0; g < groups.length && !chosen; g++) {
                var candidates = offers.filter(function(x) { return x.task && x.task.group === groups[g] })
                if (!candidates.length) continue
                var names = pollers().map(function(p) { return p.host }), start = names.indexOf(lastServed[groups[g]])
                for (var step = 1; step <= names.length; step++) {
                    var h = names[(start + step) % names.length]
                    var pick = candidates.filter(function(x) { return x.poller.host === h })[0]
                    if (pick) { chosen = pick.poller; request = Polling.commit(chosen.state, pick.task, at); break }
                }
                var served = Object.assign({}, lastServed)
                served[groups[g]] = chosen.host
                lastServed = served
                panelSlot++
            }
        }
        if (pollers().some(function(p) { return p.state.events.length })) { drainEvents(); adopt() }
        if (!request) return
        request.host = chosen.host
        request.life = chosen.life
        requestInfo = request
        workerBusy = true
        helperStarted = false
        requestProc.command = ["python3", helper, "page", JSON.stringify(request)]
        requestProc.running = true
    }
    function failedToStart() {
        console.warn("GitLab Pipelines helper: python3 failed to start")
        finishRequest("", 127)
    }
    function finishRequest(text, code) {
        try { receivePage(Model.reply(text, code, requestInfo.requestId), requestInfo) }
        finally { workerBusy = false }
    }
    function receivePage(text, request) {
        var p = request.host ? pollerFor(request.host, request.life) : pollers()[0]
        if (!p) { workerBusy = false; return }
        var reply
        try {
            reply = JSON.parse(text)
            if (!reply || reply.requestId !== request.requestId)
                throw new Error("GitLab helper returned an invalid request identity")
        } catch (e) {
            console.warn("GitLab Pipelines helper reply rejected: " + String(text).slice(0, 300))
            reply = {requestId:request.requestId, error:"GitLab helper returned invalid data; see the shell log", errorType:"setup"}
        }
        var accepted = Polling.complete(p.state, reply, Date.now())
        drainEvents()
        if (accepted) {
            if (!reply.error) updated = new Date().toISOString()
        }
        adopt()
    }
    function statusColor(status) {
        switch (Model.group(status)) {
        case "success": case "manual": return Commons.Color.accent
        case "failed": case "allowed": return Commons.Color.urgent
        default: return Commons.Color.menu.text
        }
    }
    function statusOpacity(status) {
        var g = Model.group(status)
        return g === "allowed" ? 0.6 : g === "skipped" ? 0.5 : 1
    }
    function errorHint(error, catalogueError, stopped, filtering) {
        var escape = filtering ? "Esc and " : ""
        if (error !== "" && error === catalogueError) return "check the token's access, then press " + escape + "R"
        if (stopped && error.indexOf("glab") < 0 && error.indexOf("shell log") < 0) return "see the shell log, then press " + escape + "r"
        if (stopped) return "then press " + escape + "r"
        return ""
    }
    function emptyText(error, hint, cooldownText, discoveryComplete, repoCount, filter, mrView, mrs) {
        if (error) return error + (hint ? " — " + hint : "")
        if (cooldownText) return cooldownText
        if (mrView) return filter ? "No merge requests match “" + filter + "”" : !mrs.list ? "Loading merge requests…" : "No open merge requests"
        if (!discoveryComplete && filter) return "Still discovering projects… no matches so far"
        if (!discoveryComplete) return "Discovering projects…"
        if (repoCount === 0) return "No projects found on this account"
        if (filter) return "No projects or pipelines match “" + filter + "”"
        return "No matching projects or pipelines"
    }
    function openBrowser() {
        if (current && Model.browsable(current.url, current.host))
            Quickshell.execDetached(["xdg-open", current.url])
        else if (view === "mrs") notify("No link")
    }

    Component.onCompleted: {
        statusInstance = String(Date.now()) + "-" + Math.random().toString(36).slice(2)
        publishStatus()
        rebuild()
        loadPins()
        registrationProc.running = true
    }
    Component.onDestruction: {
        if (statusPath) {
            var payload = Model.barStatus(polling, "", host, statusInstance, Date.now())
            payload.state = "none"
            var writtenAt = payload.writtenAt
            delete payload.writtenAt
            pendingStatus = JSON.stringify(payload)
            payload.writtenAt = writtenAt
            statusFile.setText(JSON.stringify(payload) + "\n")
        }
    }
    Process {
        id: registrationProc
        command: ["python3", root.localPath("menu.py"), "register"]
        stderr: StdioCollector { id: registrationErrors }
        onExited: function(code) {
            if (code !== 0) console.warn("GitLab Pipelines menu registration failed: " + registrationErrors.text.trim())
        }
    }
    Process {
        id: pinsLoad
        stdout: StdioCollector { id: pinsLoadOutput }
        onStarted: root.pinsLoadStarted = true
        onExited: function(code) { root.finishPinsLoad(code, pinsLoadOutput.text) }
        // Quickshell 0.3.1: a failed start emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && !root.pinsLoadStarted) root.finishPinsLoad(127, "")
    }
    Process {
        id: pinsSave
        stdout: StdioCollector { id: pinsSaveOutput }
        onStarted: root.pinsSaveStarted = true
        onExited: function(code) { root.finishPinsSave(code, pinsSaveOutput.text) }
        onRunningChanged: if (!running && !root.pinsSaveStarted) root.finishPinsSave(127, "")
    }
    Timer { id: noticeTimer; interval: 2000; onTriggered: root.notice = "" }
    Timer { id: actionWait; repeat: false; onTriggered: root.sendAction() }
    Process {
        id: actionProc
        property int epoch
        property int life
        property string host
        property int requestId
        property var target
        stdout: StdioCollector { id: actionOut }
        onStarted: root.actionStarted = true
        onExited: function(code) { root.finishAction(code, actionOut.text) }
        // Quickshell 0.3.1: a failed start emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && !root.actionStarted) root.finishAction(127, "")
    }
    Process {
        id: notifyProc
        property var message
        onStarted: root.notifyStarted = true
        onExited: function(code) {
            if (code !== 0) root.missed(message)
            Qt.callLater(root.sendNext)
        }
        // Quickshell 0.3.1: a missing binary emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && !root.notifyStarted) { root.missed(message); Qt.callLater(root.sendNext) }
    }
    Process {
        id: copyProc
        property int serial: 0
        onStarted: root.copyStarted = true
        onExited: function(code) {
            if (serial === root.copySerial) root.notify(code === 0 ? root.copyLabel : "Copy failed")
        }
        // Quickshell 0.3.1: a missing binary emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && !root.copyStarted && serial === root.copySerial) root.notify("Copy failed")
    }
    Process {
        id: traceProc
        property int serial: 0
        onStarted: if (serial === root.traceSerial) root.traceStarted = true
        onExited: function(code) {
            if (serial !== root.traceSerial) return
            if (code === 0) root.close()
            else root.notify("Could not open a terminal")
        }
        // Quickshell 0.3.1: a missing binary emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && !root.traceStarted && serial === root.traceSerial) root.notify("Could not open a terminal")
    }
    Process {
        id: helpProc
        command: ["bash", root.localPath("keybindings.sh"), "--print"]
        stdout: StdioCollector { id: helpOutput }
        onExited: function(code) { if (code === 0) root.helpText = helpOutput.text.trim() }
    }
    ListModel { id: visibleRows; dynamicRoles: true }
    FileView {
        id: statusFile
        path: root.statusPath
        atomicWrites: true
        blockWrites: true
        printErrors: false
        onSaved: root.lastStatus = root.pendingStatus
    }
    FileView {
        path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
        watchChanges: true
        printErrors: false
        onLoaded: root.configure(text())
        onLoadFailed: { root.configError = ""; root.markConfigured(); root.publishStatus() }
        onFileChanged: reload()
    }
    Timer { interval: root.opened ? 100 : 1000; running: root.opened || root.watching; repeat: true; onTriggered: root.pump() }
    Timer { interval: 1000; running: root.opened; repeat: true; onTriggered: root.now = Date.now() }
    Process {
        id: requestProc
        stdout: StdioCollector { id: pageOutput }
        stderr: StdioCollector { id: pageErrors }
        onExited: function(code) {
            if (pageErrors.text.trim()) console.warn("GitLab Pipelines helper (exit " + code + "): " + pageErrors.text.trim())
            root.finishRequest(pageOutput.text, code)
        }
        onStarted: root.helperStarted = true
        // Quickshell 0.3.1: a failed start emits neither started nor exited, only running=false.
        onRunningChanged: if (!running && root.workerBusy && !root.helperStarted) root.failedToStart()
    }

    PanelWindow {
        id: window
        visible: root.opened
        screen: root.targetScreen
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "omarchy-gitlab-pipelines"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        BorderSurface {
            id: card
            anchors.centerIn: parent
            width: Math.min(root.zs(Style.space(900)), window.width - Style.gapsOut * 2)
            height: Math.min(root.zs(Style.space(680)), window.height - Style.gapsOut * 2)
            color: Commons.Color.menu.background
            radius: Style.cornerRadius
            borderSpec: Border.surfaceSpec("menu", "border", Commons.Color.menu.border, root.borderWidth)
            padding: root.zs(Style.spacing.panelPadding)

            Item {
                id: keys
                anchors.fill: parent
                anchors.leftMargin: card.contentLeftInset
                anchors.rightMargin: card.contentRightInset
                anchors.topMargin: card.contentTopInset
                anchors.bottomMargin: card.contentBottomInset
                focus: true
                Keys.onPressed: function(event) {
                    if (root.confirm) { root.confirmKey(event); return }
                    if (root.zoomKey(event)) { event.accepted = true; return }
                    event.accepted = true
                    if (root.helpOpen) {
                        var line = root.zf(Style.font.body) * 1.4
                        var bare = !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier | Qt.ShiftModifier))
                        if (event.text === "?" || event.key === Qt.Key_Escape || (bare && event.key === Qt.Key_Q)) root.helpOpen = false
                        else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) root.scrollHelp(line)
                        else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) root.scrollHelp(-line)
                        else if (event.key === Qt.Key_PageDown) root.scrollHelp(helpFlickable.height)
                        else if (event.key === Qt.Key_PageUp) root.scrollHelp(-helpFlickable.height)
                        return
                    }
                    var plain = !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
                    var shift = !!(event.modifiers & Qt.ShiftModifier)
                    if (plain && event.text === "?") root.toggleHelp()
                    else if (plain && !shift && event.key === Qt.Key_M) root.toggleView()
                    else if (root.view === "mrs" && root.mrKey(event, plain, shift)) {}
                    else if (plain && event.key === Qt.Key_Y) root.copy(shift ? "sha" : "url")
                    else if (plain && event.key === Qt.Key_G) root.move(shift ? root.entries.length : -root.entries.length)
                    else if (plain && event.key === Qt.Key_Q && !shift) root.close()
                    else if (plain && event.key === Qt.Key_E && !shift) root.nextFailure()
                    else if (plain && event.key === Qt.Key_P && !shift) root.togglePin()
                    else if (plain && event.key === Qt.Key_T && !shift) root.trace()
                    else if (plain && event.key === Qt.Key_W && !shift) root.toggleWatch()
                    else if (plain && !shift && [Qt.Key_A, Qt.Key_C, Qt.Key_X, Qt.Key_N].indexOf(event.key) >= 0)
                        root.startAction(String.fromCharCode(event.key).toLowerCase())
                    else if (event.key === Qt.Key_Escape) {
                        if (root.filterText) root.filterText = ""
                        else root.close()
                    } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) root.move(1)
                    else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) root.move(-1)
                    else if (event.key === Qt.Key_PageDown) root.move(8)
                    else if (event.key === Qt.Key_PageUp) root.move(-8)
                    else if (event.key === Qt.Key_Home) root.move(-root.entries.length)
                    else if (event.key === Qt.Key_End) root.move(root.entries.length)
                    else if (event.key === Qt.Key_Left || event.key === Qt.Key_H) root.expand(true)
                    else if ([Qt.Key_Right, Qt.Key_L, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space].indexOf(event.key) >= 0) root.expand(false)
                    else if (event.key === Qt.Key_Slash) { searchField.forceActiveFocus(); searchField.selectAll() }
                    else if (event.key === Qt.Key_R) {
                        root.refresh(!!(event.modifiers & Qt.ShiftModifier))
                    }
                    else if (event.key === Qt.Key_O) root.openBrowser()
                    else event.accepted = false
                }

                Column {
                    anchors.fill: parent
                    spacing: root.zs(Style.spacing.md)
                    Text {
                        width: parent.width
                        text: root.view === "mrs" ? "My merge requests  ·  " + (root.multi() ? root.pollers().reduce(function(n, p) { return n + ((p.state.mrs.list || []).length) }, 0) : (root.polling.mrs.list || []).length) + " open"
                            : "GitLab Pipelines  ·  " + root.repos.length + (root.repos.length === 1 ? " project" : " projects") + (root.multi() ? " on " + root.pollers().length + " hosts" : "")
                        color: Commons.Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.title); bold: true }
                        textFormat: Text.PlainText
                    }
                    TextInput {
                        id: searchField
                        Accessible.role: Accessible.EditableText
                        Accessible.name: root.view === "mrs" ? "Search merge requests" : "Search projects"
                        width: parent.width
                        height: Math.ceil(font.pixelSize * 1.4)
                        color: Commons.Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                        clip: true
                        selectByMouse: true
                        selectionColor: Commons.Color.menu.selectedBackground
                        selectedTextColor: Commons.Color.menu.selectedText
                        Keys.onPressed: function(event) {
                            if (root.confirm) { root.confirmKey(event); return }
                            if (root.zoomKey(event)) { event.accepted = true; return }
                            if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
                                root.move(event.key === Qt.Key_Up ? -1 : 1)
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                keys.forceActiveFocus()
                                // Enter from the search only opens: the first result may already be auto-open (#27).
                                if (!(root.current && root.shown[root.current.key])) root.expand(false)
                            } else if (event.key === Qt.Key_Escape) {
                                root.filterText = ""
                                keys.forceActiveFocus()
                            } else if (event.key === Qt.Key_Tab) {
                                keys.forceActiveFocus()
                            } else return
                            event.accepted = true
                        }
                        Text {
                            id: placeholder
                            anchors.fill: parent
                            visible: searchField.text.length === 0
                            text: root.view === "mrs" ? (root.filtering ? "Search merge requests…" : "/ search merge requests") : root.filtering ? "Search projects…" :
                                (root.discoveryComplete ? "Activity checked " + root.checkedCount + "/" + root.repos.length + " · pinned and running first · / search projects" : "Discovering projects… " + root.repos.length + " found")
                            color: Commons.Color.menu.text
                            opacity: 0.75
                            font: searchField.font
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                        }
                    }
                    Text {
                        id: errorStrip
                        width: parent.width
                        visible: root.errorLines().length > 0 || !root.multi() && root.cooldownText !== ""
                        text: {
                            var parts = root.errorLines()
                            if (!root.multi() && root.cooldownText !== "") parts.push(root.cooldownText)
                            return parts.join(root.multi() ? "\n" : " · ")
                        }
                        color: Commons.Color.urgent
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                        wrapMode: Text.Wrap
                        maximumLineCount: root.multi() ? root.pollers().length + 1 : 2
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        // The strip changes the list's height; keep the cursor row in view.
                        function keepCursor() {
                            // The Column can resize the list after this callLater; the list's next height change repositions too.
                            list.keepOnResize = true
                            Qt.callLater(function() {
                                // forceLayout: the Column may not have resized the list yet when this runs.
                                if (root.opened && root.cursor >= 0 && root.cursor < list.count) { list.forceLayout(); list.positionViewAtIndex(root.cursor, ListView.Contain) }
                            })
                        }
                        onVisibleChanged: keepCursor()
                        onHeightChanged: keepCursor()
                    }
                    Rectangle { id: hairline; width: parent.width; height: Style.spacing.hairline; color: Commons.Color.menu.border; opacity: 0.4 }
                    ListView {
                        id: list
                        Accessible.role: Accessible.List
                        Accessible.name: root.view === "mrs" ? "My merge requests" : "GitLab pipelines"
                        width: parent.width
                        height: Math.max(0, parent.height - y - footer.height - root.zs(Style.spacing.md))
                        clip: true
                        model: visibleRows
                        boundsBehavior: Flickable.StopAtBounds
                        // The footer settles after the zoom's callLater, which shrinks the list a few px; keep the cursor row contained.
                        property bool keepOnResize: false
                        onHeightChanged: {
                            var keep = zoomSettle.running || keepOnResize
                            keepOnResize = false
                            if (keep && root.opened && root.cursor >= 0 && root.cursor < count) positionViewAtIndex(root.cursor, ListView.Contain)
                        }
                        delegate: Rectangle {
                            required property var rowData
                            readonly property var modelData: rowData
                            required property int index
                            Accessible.role: Accessible.ListItem
                            Accessible.name: Model.accessibleName(modelData)
                            Accessible.selected: index === root.cursor
                            width: list.width
                            height: modelData.subtitle ? Math.max(root.zs(Style.space(64)), root.zf(Style.font.body) + root.zf(Style.font.caption) + root.zs(Style.space(16))) : Math.max(root.zs(Style.space(40)), root.zf(Style.font.body) + root.zs(Style.space(12)))
                            color: index === root.cursor ? Commons.Color.menu.selectedBackground : "transparent"
                            radius: 0
                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: root.zs(Style.space(8)) + modelData.depth * root.zs(Style.space(18))
                                anchors.rightMargin: root.zs(Style.space(8))
                                spacing: root.zs(Style.spacing.sm)
                                Text {
                                    id: statusIcon
                                    objectName: "statusIcon"
                                    opacity: root.statusOpacity(modelData.status)
                                    width: root.zs(Style.space(18))
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: Model.icon(modelData.status)
                                    color: root.statusColor(modelData.status)
                                    font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.body) }
                                }
                                Column {
                                    width: Math.max(0, parent.width - statusIcon.width - info.width - parent.spacing * 2)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Row {
                                        width: parent.width
                                        spacing: root.zs(Style.spacing.sm)
                                        Text {
                                            width: Math.max(0, Math.min(implicitWidth, parent.width - (hostName.visible ? hostName.width + parent.spacing : 0)))
                                            text: (["repo", "run", "stage"].indexOf(modelData.kind) >= 0 ? (root.shown[modelData.key] ? "▾ " : "▸ ") : "") + (modelData.kind === "repo" && modelData.pinned ? "★ " : "") + (modelData.kind === "run" && modelData.watched ? "◉ " : "") + modelData.title
                                            color: index === root.cursor ? Commons.Color.menu.selectedText : Commons.Color.menu.text
                                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.body); bold: modelData.kind === "repo" }
                                            elide: Text.ElideRight
                                            textFormat: Text.PlainText
                                        }
                                        Text {
                                            id: hostName
                                            visible: !!modelData.hostLabel
                                            width: Math.min(implicitWidth, parent.width * 0.4)
                                            text: modelData.hostLabel
                                            color: index === root.cursor ? Commons.Color.menu.selectedText : Commons.Color.menu.text
                                            opacity: 0.55
                                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                                            elide: Text.ElideRight
                                            textFormat: Text.PlainText
                                        }
                                    }
                                    Text {
                                        objectName: "rowSubtitle"
                                        visible: !!modelData.subtitle
                                        width: parent.width
                                        text: Model.subtitleText(modelData, root.now)
                                        color: index === root.cursor ? Commons.Color.menu.selectedText : Commons.Color.menu.text
                                        opacity: 0.65
                                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                                        elide: Text.ElideRight
                                        textFormat: Text.PlainText
                                    }
                                }
                                Text {
                                    id: info
                                    objectName: "statusInfo"
                                    opacity: root.statusOpacity(modelData.status)
                                    width: Math.min(implicitWidth, list.width * 0.35)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: Model.infoText(modelData, root.now)
                                    color: root.statusColor(modelData.status)
                                    font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                                    elide: Text.ElideRight
                                    textFormat: Text.PlainText
                                }
                            }
                        }
                        Text {
                            id: emptyLabel
                            anchors.centerIn: parent
                            width: parent.width - 2 * root.zs(Style.space(16))
                            visible: root.entries.length === 0
                            text: root.multi() && root.repos.length === 0 && root.errorLines().length ? "" : root.emptyText(root.multi() ? "" : root.error, root.multi() ? "" : root.errorHintText, root.multi() && root.errorLines().length ? "" : root.cooldownText, root.discoveryComplete, root.repos.length, root.filterText, root.view === "mrs", root.multi() ? {list: root.pollers().reduce(function(a, p) { return a.concat(p.state.mrs.list || []) }, [])} : root.polling.mrs)
                            color: root.error && !root.multi() ? Commons.Color.urgent : Commons.Color.menu.text
                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.body) }
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                            textFormat: Text.PlainText
                        }
                    }
                    Item {
                        id: footer
                        width: parent.width
                        height: Math.max(hint.implicitHeight, zoomLabel.visible ? zoomLabel.implicitHeight : 0)
                        Text {
                            id: hint
                            Accessible.role: Accessible.StaticText
                            Accessible.name: hint.text
                            width: parent.width - (zoomLabel.visible ? zoomLabel.implicitWidth + root.zs(Style.spacing.sm) : 0)
                            text: root.confirm ? root.confirm.text : (root.notice || root.cooldownText || (root.filtering ? root.searchHint : root.view === "mrs" ? root.mrHint : root.listHint))
                            color: root.actionFailed && root.notice ? Commons.Color.urgent : Commons.Color.menu.text
                            opacity: 0.65
                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                            wrapMode: root.confirm ? Text.Wrap : Text.NoWrap
                            elide: root.confirm ? Text.ElideNone : Text.ElideRight
                            textFormat: Text.PlainText
                        }
                        Text {
                            id: zoomLabel
                            anchors.right: parent.right
                            visible: root.zoomPercent !== 100
                            text: root.zoomPercent + "%"
                            color: Commons.Color.menu.text
                            opacity: 0.65
                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                            textFormat: Text.PlainText
                        }
                    }
                }
                Rectangle {
                    id: helpOverlay
                    anchors.fill: parent
                    color: Commons.Color.menu.background
                    visible: root.helpOpen
                    Text {
                        id: helpCaption
                        width: parent.width
                        text: "? or Esc to close"
                        color: Commons.Color.menu.text
                        opacity: 0.65
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                        textFormat: Text.PlainText
                    }
                    Flickable {
                        id: helpFlickable
                        anchors { top: helpCaption.bottom; topMargin: root.zs(Style.spacing.md); left: parent.left; right: parent.right; bottom: parent.bottom }
                        clip: true
                        contentHeight: helpBody.implicitHeight
                        Text {
                            id: helpBody
                            width: helpFlickable.width
                            wrapMode: Text.Wrap
                            text: root.helpText || "Help unavailable — see the README"
                            color: Commons.Color.menu.text
                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.body) }
                            textFormat: Text.PlainText
                        }
                    }
                }
            }
        }
    }
}
