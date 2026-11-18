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
    property var configPins: []
    property var savedPins: []
    property bool pinsLoaded: false
    property bool pinsLoadFailed: false
    property string pinsError: ""
    property var pinned: ({})
    property string pinsLoadHost: ""
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
    readonly property string listHint: "↑↓ move  ←→ expand  g/G ends  / search  e failure  y/Y copy  p pin  t log  w watch  o GitLab  ? help  q close"
    readonly property real borderWidth: Math.max(1, Style.space(2))
    property alias filterText: searchField.text
    readonly property bool filtering: searchField.activeFocus
    property string error: ""
    property string host: "gitlab.com"
    property string updated: ""
    property var polling: Polling.create()
    readonly property bool watching: Object.keys(polling.watches || {}).length > 0
    property var notifyCommand: ["notify-send", "--app-name=GitLab Pipelines"]
    property var notifyQueue: []
    property var missedNotices: []
    property bool notifyStarted: false
    property var watched: ({})
    property var requestInfo: null
    property bool workerBusy: false
    property bool helperStarted: false
    property double now: Date.now()
    readonly property bool discoveryComplete: polling.catalogueComplete
    readonly property string cooldownText: now < polling.cooldown ? "GitLab paused until " + new Date(polling.cooldown).toLocaleTimeString() : ""
    readonly property string errorHintText: errorHint(error, polling.catalogueError || "", !!polling.auth, filtering)
    readonly property int checkedCount: repos.filter(function(repo) { return !!repo.checked || repo.archived || repo.disabled }).length
    readonly property var current: entries[cursor] || null
    readonly property string helper: localPath("gitlab.py")
    function localPath(name) { return decodeURIComponent(Qt.resolvedUrl(name).toString().replace(/^file:\/\//, "")) }
    onFilterTextChanged: {
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
    // The footer settles after the zoom's callLater; only that settle may move the view, not later resizes or scrolling.
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
        if (!opened) Polling.open(polling, Date.now())
        opened = true
        if (configured) applyOpen(payload)
        else pendingOpen = pendingOpen.concat([payload])
        if (pinsError) { notify(pinsError); pinsError = "" }
        showMissed()
        selectionChanged(true)
        pump()
        Qt.callLater(function() { keys.forceActiveFocus() })
    }
    function applyOpen(payload) {
        var request = Model.openFilter(payload, host)
        if (request.filter !== null) {
            helpOpen = false
            notice = ""; noticeTimer.stop()
            if (filterText === request.filter) { rebuild(true); selectionChanged(false) }
            else filterText = request.filter
        }
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
        polling.events.forEach(function(e) { queue.push(Model.watchMessage(e, host, host)) })
        notifyQueue = queue
        polling.events = []
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
        var code = Polling.watch(polling, current.repo, current.run, Date.now())
        var r = (polling.repos.filter(function(x) { return x.repo === current.repo })[0] || {}).runs || []
        var run = r.filter(function(x) { return String(x.id) === current.run })[0]
        notify(Model.watchNotice(code, current.repo, run ? run.run_number : current.run))
        adopt()
    }
    function close() {
        opened = false
        helpOpen = false
        notice = ""
        noticeTimer.stop()
        copySerial++
        traceSerial++
        Polling.close(polling)
        if (polling.events.length) { drainEvents(); adopt() }
        requestProc.running = false
    }
    function toggle() { opened ? close() : open("{}") }
    function status() {
        return JSON.stringify({opened: opened, rows: entries.length, repositories: repos.length,
            checked: checkedCount, discoveryComplete: discoveryComplete, error: error, updated: updated,
            requests: polling.requests, inFlight: workerBusy, cooldown: polling.cooldown,
            lastRequest: polling.lastRequest, lastStarted: polling.lastStarted,
            filter: filterText, editing: filtering, selected: current ? current.key : "", scrollY: list.contentY})
    }

    function rebuild(resetSelection) {
        shown = Model.merge(expanded, Model.autoOpen(repos, filterText), searchCollapsed)
        var key = current ? current.key : ""
        var topIndex = list.indexAt(1, list.contentY + 1)
        var topItem = list.itemAtIndex(topIndex)
        var topKey = entries[topIndex] ? entries[topIndex].key : ""
        var topOffset = topItem ? topItem.y - list.contentY : 0
        var next = Model.rows(repos, shown, details, filterText, now, pinned, watched)
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
    function notify(t) { notice = t; noticeTimer.restart() }
    function copy(what) {
        var r = Model.copyText(current, what)
        if (!r.text) { notify(r.label); return }
        if (copyProc.running) return
        copyStarted = false
        copyLabel = r.label
        copyProc.serial = copySerial
        copyProc.command = copyCommand.concat([r.text])
        copyProc.running = true
    }
    function trace() {
        if (!current || current.kind !== "job" || !current.job) { notify("Select a job to open its log"); return }
        if (traceProc.running) return
        traceStarted = false
        traceProc.serial = traceSerial
        traceProc.command = traceCommand.concat([host, current.repo, current.job])
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
        var p = Model.pins(configPins, savedPins)
        var map = {}
        p.names.forEach(function(n) { map[n] = true })
        pinned = map
        Polling.pin(polling, p.names)
        adopt()
    }
    function loadPins() {
        if (pinsLoad.running) return
        pinsLoadHost = host
        pinsLoadStarted = false
        pinsLoad.command = pinsCommand.concat([helper, "pins", JSON.stringify({host: host})])
        pinsLoad.running = true
    }
    function finishPinsLoad(code, text) {
        if (pinsLoadHost !== host) { Qt.callLater(loadPins); return }
        var reply = null
        try { reply = JSON.parse(text) } catch (e) {}
        pinsLoadFailed = !(code === 0 && reply && Array.isArray(reply.pins))
        if (!pinsLoadFailed) savedPins = reply.pins
        else {
            savedPins = []
            pinsError = "Pins not loaded: " + (reply && reply.error || "helper failed")
        }
        var own = sessionPins[host.toLowerCase()]
        if (own) { savedPins = own; pinsLoadFailed = false }
        pinsLoaded = true
        applyPins()
    }
    function togglePin() {
        if (!current) return
        if (!pinsLoaded) { notify("Pins are still loading"); return }
        // A save after a failed load would replace this host's saved pins with only the new one.
        if (pinsLoadFailed) { notify("Pins not loaded; trying again"); pinsLoaded = false; loadPins(); return }
        var r = Model.togglePin(current.repo, configPins, savedPins)
        notify(r.notice)
        if (r.saved) {
            savedPins = r.saved
            var s = Object.assign({}, sessionPins)
            s[host.toLowerCase()] = r.saved
            sessionPins = s
            applyPins()
            savePins(host, r.saved)
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
            var configuredHost = entry && typeof entry.host === "string" ? entry.host : "gitlab.com"
            if (!/^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?$/.test(configuredHost)) throw new Error("invalid host " + configuredHost)
            var hostChanged = configuredHost !== host
            if (hostChanged) {
                savedPins = []; pinsLoaded = false
                var n = Object.keys(polling.watches || {}).length
                if (n) {
                    notifyQueue = notifyQueue.concat([Model.watchMessage({type: "host", count: n}, host, configuredHost)])
                    sendNext()
                }
                polling = Polling.resetHost(polling)
                expanded = ({}); searchCollapsed = ({}); details = ({}); updated = ""; error = ""; cursor = 0
            }
            host = configuredHost
            var names = entry && Array.isArray(entry.projects) ? entry.projects : []
            if (!polling.repos.length && names.length) {
                polling.wakeAt = 0
                polling.repos = names.filter(function(name) { return Model.validProject(name) }).map(function(name) { return {repo:name} })
            }
            configPins = entry && Array.isArray(entry.pinned) ? entry.pinned : []
            if (configPins.filter(function(name) { return Model.validProject(name) }).length > 10) console.warn("GitLab Pipelines: only the first 10 pins apply")
            adopt()
            applyPins()
            // After configPins and projects are set, so even a synchronous failed start sees this host's config.
            if (hostChanged) loadPins()
        } catch (e) { error = "Configuration: " + e.message }
        markConfigured()
    }
    function selectionChanged(immediate) {
        if (!polling) return
        Polling.select(polling, current ? current.repo : "", current ? current.run : "", shown, Date.now(), immediate)
    }
    function adopt() {
        repos = polling.repos.slice()
        details = Object.assign({}, polling.details)
        var map = {}
        Object.keys(polling.watches || {}).forEach(function(id) { map[id] = true })
        watched = map
        error = polling.error || polling.catalogueError
        // Reassign the state reference to notify bindings after pure-JS mutations.
        polling = Object.assign({}, polling)
        rebuild()
        if ((current && current.repo || "") !== polling.selected || (current && current.run || "") !== polling.inspected) selectionChanged(false)
    }
    function refresh(catalogue) {
        selectionChanged(true)
        Polling.manual(polling, Date.now(), !!catalogue)
        pump()
    }
    function pump() {
        if (workerBusy || (!opened && !watching)) return
        var request = Polling.next(polling, Date.now())
        if (polling.events.length) { drainEvents(); adopt() }
        if (!request) return
        request.host = host
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
        var reply
        try {
            reply = JSON.parse(text)
            if (!reply || reply.requestId !== request.requestId)
                throw new Error("GitLab helper returned an invalid request identity")
        } catch (e) {
            console.warn("GitLab Pipelines helper reply rejected: " + String(text).slice(0, 300))
            reply = {requestId:request.requestId, error:"GitLab helper returned invalid data; see the shell log", errorType:"setup"}
        }
        var accepted = Polling.complete(polling, reply, Date.now())
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
    function emptyText(error, hint, cooldownText, discoveryComplete, repoCount, filter) {
        if (error) return error + (hint ? " — " + hint : "")
        if (cooldownText) return cooldownText
        if (!discoveryComplete && filter) return "Still discovering projects… no matches so far"
        if (!discoveryComplete) return "Discovering projects…"
        if (repoCount === 0) return "No projects found on this account"
        if (filter) return "No projects or pipelines match “" + filter + "”"
        return "No matching projects or pipelines"
    }
    function openBrowser() {
        if (current && Model.browsable(current.url, host))
            Quickshell.execDetached(["xdg-open", current.url])
    }

    Component.onCompleted: {
        rebuild()
        loadPins()
        registrationProc.running = true
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
        path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
        watchChanges: true
        printErrors: false
        onLoaded: root.configure(text())
        onLoadFailed: root.markConfigured()
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
                    else if (plain && event.key === Qt.Key_Y) root.copy(shift ? "sha" : "url")
                    else if (plain && event.key === Qt.Key_G) root.move(shift ? root.entries.length : -root.entries.length)
                    else if (plain && event.key === Qt.Key_Q && !shift) root.close()
                    else if (plain && event.key === Qt.Key_E && !shift) root.nextFailure()
                    else if (plain && event.key === Qt.Key_P && !shift) root.togglePin()
                    else if (plain && event.key === Qt.Key_T && !shift) root.trace()
                    else if (plain && event.key === Qt.Key_W && !shift) root.toggleWatch()
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
                        text: "GitLab Pipelines  ·  " + root.repos.length + (root.repos.length === 1 ? " project" : " projects")
                        color: Commons.Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.title); bold: true }
                        textFormat: Text.PlainText
                    }
                    TextInput {
                        id: searchField
                        width: parent.width
                        height: Math.ceil(font.pixelSize * 1.4)
                        color: Commons.Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                        clip: true
                        selectByMouse: true
                        selectionColor: Commons.Color.menu.selectedBackground
                        selectedTextColor: Commons.Color.menu.selectedText
                        Keys.onPressed: function(event) {
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
                            text: root.filtering ? "Search projects…" :
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
                        visible: root.error !== "" || root.cooldownText !== ""
                        text: {
                            var parts = []
                            if (root.error !== "") parts.push(root.error + (root.errorHintText ? " — " + root.errorHintText : ""))
                            if (root.cooldownText !== "") parts.push(root.cooldownText)
                            return parts.join(" · ")
                        }
                        color: Commons.Color.urgent
                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        // The strip changes the list's height; keep the cursor row in view.
                        function keepCursor() {
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
                        width: parent.width
                        height: Math.max(0, parent.height - y - footer.height - root.zs(Style.spacing.md))
                        clip: true
                        model: visibleRows
                        boundsBehavior: Flickable.StopAtBounds
                        // The footer settles after the zoom's callLater, which shrinks the list a few px; keep the cursor row contained.
                        onHeightChanged: if (zoomSettle.running && root.opened && root.cursor >= 0 && root.cursor < count) positionViewAtIndex(root.cursor, ListView.Contain)
                        delegate: Rectangle {
                            required property var rowData
                            readonly property var modelData: rowData
                            required property int index
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
                                    Text {
                                        width: parent.width
                                        text: (["repo", "run", "stage"].indexOf(modelData.kind) >= 0 ? (root.shown[modelData.key] ? "▾ " : "▸ ") : "") + (modelData.kind === "repo" && modelData.pinned ? "★ " : "") + (modelData.kind === "run" && modelData.watched ? "◉ " : "") + modelData.title
                                        color: index === root.cursor ? Commons.Color.menu.selectedText : Commons.Color.menu.text
                                        font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.body); bold: modelData.kind === "repo" }
                                        elide: Text.ElideRight
                                        textFormat: Text.PlainText
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
                            text: root.emptyText(root.error, root.errorHintText, root.cooldownText, root.discoveryComplete, root.repos.length, root.filterText)
                            color: root.error ? Commons.Color.urgent : Commons.Color.menu.text
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
                            width: parent.width - (zoomLabel.visible ? zoomLabel.implicitWidth + root.zs(Style.spacing.sm) : 0)
                            text: root.notice || root.cooldownText || (root.filtering ? root.searchHint : root.listHint)
                            color: Commons.Color.menu.text
                            opacity: 0.65
                            font { family: Style.font.menuFamily; pixelSize: root.zf(Style.font.caption) }
                            elide: Text.ElideRight
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
