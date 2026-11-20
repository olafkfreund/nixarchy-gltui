import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "BarModel.js" as BarModel

Ui.BarWidget {
    id: root
    moduleName: "olafkfreund.gitlab-pipelines-bar"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    property string statusPath: {
        var runtime=Quickshell.env("XDG_RUNTIME_DIR")
        var display=Quickshell.env("WAYLAND_DISPLAY")
        return runtime && display ? runtime+"/omarchy-gitlab-pipelines-"+display+".json" : ""
    }
    property string statusText: ""
    property var statusView: BarModel.view("",Date.now(),vertical)

    function updateView(text) {
        statusText=text
        statusView=BarModel.view(text,Date.now(),vertical)
        recheck.stop()
        if (statusView.recheckAt>0) {
            recheck.interval=Math.max(100,Math.min(86400000,statusView.recheckAt-Date.now()))
            recheck.start()
        }
    }
    function toggle() {
        Quickshell.execDetached(["omarchy-shell","shell","toggle","olafkfreund.gitlab-pipelines","{}"])
    }
    onVerticalChanged: updateView(statusText)
    onStatusPathChanged: updateView("")

    FileView {
        path: root.statusPath
        watchChanges: true
        printErrors: false
        onLoaded: root.updateView(text())
        onLoadFailed: root.updateView("")
        onFileChanged: reload()
    }
    Timer {
        id: recheck
        repeat: false
        onTriggered: root.updateView(root.statusText)
    }
    Ui.WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.statusView.label
        active: root.statusView.active
        dimmed: root.statusView.dimmed
        tooltipText: root.statusView.tooltip
        pressFeedbackButtons: Qt.LeftButton
        Accessible.name: root.statusView.accessible
        onPressed: function(button) { if (button === Qt.LeftButton) root.toggle() }
    }
}
