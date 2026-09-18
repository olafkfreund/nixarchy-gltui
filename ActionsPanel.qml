import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui
import "ActionsModel.js" as Model
import "Polling.js" as Polling

Item {
    id: root
    property var shell: null
    property var manifest: null
    property bool opened: false
    property var targetScreen: null
    property var repositories: []
    property var repos: []
    property var details: ({})
    property var expanded: ({})
    property var entries: []
    property int cursor: 0
    property alias filterText: searchField.text
    readonly property bool filtering: searchField.activeFocus
    property string error: ""
    property string updated: ""
    property var polling: Polling.create()
    property var requestInfo: null
    property bool workerBusy: false
    property double now: Date.now()
    readonly property bool loading: workerBusy
    readonly property bool discoveryComplete: polling.catalogueComplete
    readonly property string cooldownText: now < polling.cooldown ? "GitHub paused until " + new Date(polling.cooldown).toLocaleTimeString() : ""
    readonly property int checkedCount: repos.filter(function(repo) { return !!repo.checked || repo.archived || repo.disabled }).length
    readonly property real textScale: 1.5
    readonly property var current: entries[cursor] || null
    readonly property string helper: decodeURIComponent(Qt.resolvedUrl("actions.py").toString().replace(/^file:\/\//, ""))
    onFilterTextChanged: {
        expanded = ({})
        rebuild(true)
        selectionChanged(false)
    }

    function open(payload) {
        var monitor = Hyprland.focusedMonitor
        targetScreen = null
        for (var i = 0; i < Quickshell.screens.length; i++)
            if (monitor && Quickshell.screens[i].name === monitor.name) targetScreen = Quickshell.screens[i]
        if (!opened) Polling.open(polling, Date.now())
        opened = true
        selectionChanged(true)
        pump()
        Qt.callLater(function() { keys.forceActiveFocus() })
    }
    function close() {
        opened = false
        Polling.close(polling)
        requestProc.running = false
    }
    function toggle() { opened ? close() : open("{}") }
    function status() {
        return JSON.stringify({opened: opened, rows: entries.length, repositories: repositories.length,
            checked: checkedCount, discoveryComplete: discoveryComplete, error: error, updated: updated,
            requests: polling.requests, inFlight: workerBusy, cooldown: polling.cooldown,
            lastRequest: polling.lastRequest, lastStarted: polling.lastStarted,
            filter: filterText, editing: filtering, selected: current ? current.key : "", scrollY: list.contentY})
    }

    function rebuild(resetSelection) {
        var key = current ? current.key : ""
        var topIndex = list.indexAt(1, list.contentY + 1)
        var topItem = list.itemAtIndex(topIndex)
        var topKey = entries[topIndex] ? entries[topIndex].key : ""
        var topOffset = topItem ? topItem.y - list.contentY : 0
        var next = Model.rows(repos, expanded, details, filterText, now)
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
    function expand(collapse) {
        var row = current
        if (!row) return
        var next = Object.assign({}, expanded)
        if (collapse) {
            if (next[row.key]) delete next[row.key]
            else {
                cursor = Model.selection(entries, row.parent, cursor)
                list.positionViewAtIndex(cursor, ListView.Contain)
                selectionChanged(false)
                return
            }
        } else if (["repo", "run", "job"].indexOf(row.kind) >= 0) {
            next[row.key] = !next[row.key]
        }
        expanded = next
        rebuild()
        selectionChanged(true)
        pump()
    }
    function configure(text) {
        try {
            var config = JSON.parse(text)
            var entry = (config.plugins || []).filter(function(p) { return p.id === "olafkfreund.github-actions" })[0]
            var names = entry && Array.isArray(entry.repositories) ? entry.repositories : []
            if (!polling.repos.length && names.length)
                polling.repos = names.filter(function(name) { return typeof name === "string" && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(name) }).map(function(name) { return {repo:name} })
            adopt()
        } catch (e) { error = "Configuration: " + e.message }
    }
    function selectionChanged(immediate) {
        if (!polling) return
        Polling.select(polling, current ? current.repo : "", current ? current.run : "", expanded, Date.now(), immediate)
    }
    function adopt() {
        repos = polling.repos.slice()
        repositories = repos.map(function(repo) { return repo.repo })
        details = Object.assign({}, polling.details)
        error = polling.error
        // Reassign the state reference to notify bindings after pure-JS mutations.
        polling = Object.assign({}, polling)
        rebuild()
        if (!polling.selected || !Polling.repoFor(polling, polling.selected)) selectionChanged(false)
    }
    function refresh(catalogue) {
        selectionChanged(true)
        Polling.manual(polling, Date.now(), !!catalogue)
        pump()
    }
    function pump() {
        if (!opened || workerBusy) return
        var request = Polling.next(polling, Date.now())
        if (!request) return
        requestInfo = request
        workerBusy = true
        requestProc.command = ["python3", helper, "page", JSON.stringify(request)]
        requestProc.running = true
    }
    function receivePage(text, request) {
        var reply
        try {
            reply = JSON.parse(text)
            if (!reply || reply.requestId !== request.requestId)
                throw new Error("Workflow helper returned an invalid request identity")
        } catch (e) {
            reply = {requestId:request.requestId, error:"Workflow helper returned invalid data", errorType:"network"}
        }
        if (Polling.complete(polling, reply, Date.now())) {
            if (!reply.error) updated = new Date().toISOString()
            adopt()
        }
    }
    function statusColor(status) {
        if (["failure", "timed_out", "startup_failure", "error"].indexOf(status) >= 0) return Color.urgent
        if (status === "in_progress" || status === "success") return Color.accent
        return Color.menu.text
    }
    function openBrowser() {
        if (current && /^https:\/\/github\.com\//.test(current.url || ""))
            Quickshell.execDetached(["xdg-open", current.url])
    }

    Component.onCompleted: {
        rebuild()
        registrationProc.running = true
    }
    Process {
        id: registrationProc
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("menu.py").toString().replace(/^file:\/\//, "")), "register"]
        stderr: StdioCollector { id: registrationErrors }
        onExited: function(code) {
            if (code !== 0) console.warn("GitHub Actions menu registration failed: " + registrationErrors.text.trim())
        }
    }
    ListModel { id: visibleRows; dynamicRoles: true }
    FileView {
        path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
        watchChanges: true
        printErrors: false
        onLoaded: root.configure(text())
        onFileChanged: reload()
    }
    Timer { interval: 100; running: root.opened; repeat: true; onTriggered: root.pump() }
    Timer { interval: 1000; running: root.opened; repeat: true; onTriggered: root.now = Date.now() }
    Process {
        id: requestProc
        stdout: StdioCollector { id: pageOutput }
        stderr: StdioCollector { id: pageErrors }
        onExited: function(code) {
            root.receivePage(Model.reply(pageOutput.text, pageErrors.text, code), root.requestInfo)
            root.workerBusy = false
        }
    }

    PanelWindow {
        id: window
        visible: root.opened
        screen: root.targetScreen
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "omarchy-github-actions"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        BorderSurface {
            id: card
            anchors.centerIn: parent
            width: Math.min(Style.space(900), window.width - Style.gapsOut * 2)
            height: Math.min(Style.space(680), window.height - Style.gapsOut * 2)
            color: Color.menu.background
            radius: Style.cornerRadius
            borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
            padding: Style.spacing.panelPadding

            Item {
                id: keys
                anchors.fill: parent
                anchors.leftMargin: card.contentLeftInset
                anchors.rightMargin: card.contentRightInset
                anchors.topMargin: card.contentTopInset
                anchors.bottomMargin: card.contentBottomInset
                focus: true
                Keys.onPressed: function(event) {
                    event.accepted = true
                    if (event.key === Qt.Key_Escape) {
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
                    spacing: Style.spacing.md
                    Text {
                        width: parent.width
                        text: "GitHub Actions  ·  " + root.repositories.length + (root.repositories.length === 1 ? " repository" : " repositories")
                        color: Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.title * root.textScale); bold: true }
                        textFormat: Text.PlainText
                    }
                    TextInput {
                        id: searchField
                        width: parent.width
                        height: Math.ceil(font.pixelSize * 1.4)
                        color: Color.menu.text
                        font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * root.textScale) }
                        clip: true
                        selectByMouse: true
                        selectionColor: Color.menu.selectedBackground
                        selectedTextColor: Color.menu.selectedText
                        Keys.onPressed: function(event) {
                            if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
                                root.move(event.key === Qt.Key_Up ? -1 : 1)
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                keys.forceActiveFocus()
                                root.expand(false)
                            } else if (event.key === Qt.Key_Escape) {
                                root.filterText = ""
                                keys.forceActiveFocus()
                            } else if (event.key === Qt.Key_Tab) {
                                keys.forceActiveFocus()
                            } else return
                            event.accepted = true
                        }
                        Text {
                            anchors.fill: parent
                            visible: searchField.text.length === 0
                            text: root.filtering ? "Search repositories…" : root.cooldownText || root.error ||
                                (root.discoveryComplete ? "Activity checked " + root.checkedCount + "/" + root.repositories.length + " · running first · / search repositories" : "Discovering repositories… " + root.repositories.length + " found")
                            color: root.error || root.cooldownText ? Color.urgent : Color.menu.text
                            opacity: 0.75
                            font: searchField.font
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Color.menu.border; opacity: 0.4 }
                    ListView {
                        id: list
                        width: parent.width
                        height: Math.max(0, parent.height - y - footer.height - Style.spacing.md)
                        clip: true
                        model: visibleRows
                        boundsBehavior: Flickable.StopAtBounds
                        delegate: Rectangle {
                            required property var rowData
                            readonly property var modelData: rowData
                            required property int index
                            width: list.width
                            height: modelData.subtitle ? Math.max(Style.space(64), (Style.font.body + Style.font.caption) * root.textScale + Style.space(16)) : Math.max(Style.space(40), Style.font.body * root.textScale + Style.space(12))
                            color: index === root.cursor ? Color.menu.selectedBackground : "transparent"
                            radius: 0
                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: Style.space(8) + modelData.depth * Style.space(18)
                                anchors.rightMargin: Style.space(8)
                                spacing: Style.spacing.sm
                                Text {
                                    width: Style.space(18)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: Model.icon(modelData.status)
                                    color: root.statusColor(modelData.status)
                                    font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.body * root.textScale) }
                                }
                                Column {
                                    width: Math.max(0, parent.width - Style.space(26) - info.width - parent.spacing * 2)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        width: parent.width
                                        text: (["repo", "run", "job"].indexOf(modelData.kind) >= 0 ? (root.expanded[modelData.key] ? "▾ " : "▸ ") : "") + modelData.title
                                        color: index === root.cursor ? Color.menu.selectedText : Color.menu.text
                                        font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.body * root.textScale); bold: modelData.kind === "repo" }
                                        elide: Text.ElideRight
                                        textFormat: Text.PlainText
                                    }
                                    Text {
                                        visible: !!modelData.subtitle
                                        width: parent.width
                                        text: modelData.subtitle || ""
                                        color: index === root.cursor ? Color.menu.selectedText : Color.menu.text
                                        opacity: 0.65
                                        font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * root.textScale) }
                                        elide: Text.ElideRight
                                        textFormat: Text.PlainText
                                    }
                                }
                                Text {
                                    id: info
                                    width: Math.min(implicitWidth, list.width * 0.35)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.kind === "repo" ? modelData.info : modelData.status + (modelData.info ? " · " + modelData.info : "")
                                    color: root.statusColor(modelData.status)
                                    font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * root.textScale) }
                                    elide: Text.ElideRight
                                    textFormat: Text.PlainText
                                }
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: root.entries.length === 0
                            text: "No matching repositories or workflows"
                            color: Color.menu.text
                            font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.body * root.textScale) }
                        }
                    }
                    Text {
                        id: footer
                        width: parent.width
                        text: root.cooldownText || "↑↓ move  ←→ expand  / search  r refresh  R repos  o GitHub  Esc close"
                        color: Color.menu.text
                        opacity: 0.65
                        font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * root.textScale) }
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }
                }
            }
        }
    }
}
