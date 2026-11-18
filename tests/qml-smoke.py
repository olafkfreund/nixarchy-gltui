"""Exercise the real QML worker with a temporary fake API; no live GitLab requests."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('plugin_dir', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
source = parser.parse_args().plugin_dir.resolve()
required = ('manifest.json', 'PipelinesPanel.qml', 'PipelinesModel.js', 'Polling.js',
            'gitlab.py', 'menu.py', 'menu.example.json', 'keybindings.sh')
if not source.is_dir() or any(not (source / name).is_file() for name in required):
    parser.error('plugin_dir must contain the complete GitLab Pipelines plugin')
shell = Path(os.environ['OMARCHY_PATH']) / 'shell'
colors = tomllib.loads((Path.home() / '.local/state/omarchy/current/theme/colors.toml').read_text())
for scenario in ('fresh', 'managed'):
    with tempfile.TemporaryDirectory(prefix='pipelines-qml-') as directory:
        root = Path(directory)
        for name in ('Commons', 'Ui'):
            (root / name).symlink_to(shell / name)
        for name in ('PipelinesPanel.qml', 'PipelinesModel.js', 'Polling.js', 'keybindings.sh', 'menu.py', 'menu.example.json'):
            (root / name).symlink_to(source / name)
        (root / 'gitlab.py').write_text('''import json, sys, time
request=json.loads(sys.argv[2]); kind=request['kind']
time.sleep(0.1)
host=request.get('host'); assert host in ('gitlab.example.org','gitlab.other.org'), request
run={'id':7,'name':'CI','status':'in_progress','conclusion':'running','run_attempt':'active','head_branch':'main','run_number':1}
if host=='gitlab.other.org': data={} if kind=='run' else [{'repo':'three/repo'}] if kind=='catalogue' else []
elif kind=='catalogue': data=[{'repo':'one/sub/repo','url':'https://gitlab.example.org/one/sub/repo'},{'repo':'two/repo'}]
elif kind=='jobs': data=[{'id':8,'name':'compile','stage':'build','status':'in_progress','conclusion':'running'},{'id':9,'name':'unit','stage':'test','status':'queued','conclusion':'created'},{'id':10,'name':'lint','stage':'test','status':'completed','conclusion':'failed','allow_failure':True,'started_at':'2026-01-01T00:00:00Z','completed_at':'2026-01-01T00:01:02Z'}]
elif kind=='run': data=run
else: data=[run] if request['repo']=='one/sub/repo' and request.get('status','running') in ('recent','running') else []
print(json.dumps({'requestId':request['requestId'],'data':data,'nextPage':0,'error':'','errorType':'','remaining':4000}))
''')
        home = root / 'home'
        home.mkdir()
        theme = home / '.local/state/omarchy/current/theme'
        theme.parent.mkdir(parents=True)
        theme.symlink_to(Path.home() / '.local/state/omarchy/current/theme')
        (home / '.config').mkdir()
        (home / '.config/fontconfig').symlink_to(Path.home() / '.config/fontconfig')
        (home / '.config/omarchy').mkdir()
        (home / '.config/omarchy/shell.toml').symlink_to(Path.home() / '.config/omarchy/shell.toml')
        menu_path = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
        if scenario == 'managed':
            menu_path.parent.mkdir(parents=True)
            (home / 'managed-menu').write_text('{}\n')
            menu_path.symlink_to(home / 'managed-menu')
        (root / 'shell.qml').write_text('''
import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import qs.Commons as Commons
import "Polling.js" as Polling
ShellRoot {
    PipelinesPanel { id: panel }
    FileView {
        id: menuFile
        path: Quickshell.env("HOME") + "/.config/omarchy/extensions/omarchy-menu.jsonc"
        watchChanges: true
        blockLoading: true
        printErrors: false
        onFileChanged: reload()
    }
    Timer {
        interval: 90000; running: true
        onTriggered: { console.error("CHECK FAILED: timeout stage=" + stage + " " + panel.status()); Qt.quit() }
    }
    property int stage: 0
    property string selected: ""
    property double closedAt: 0
    property int closedRequests: 0
    function check(value, label) { if (!value) throw new Error("CHECK FAILED: " + label) }
    // when: false keeps TestCase from running tests and quitting; it is only used for keyClick.
    TestCase { id: tc; when: false }
    property int lintIndex: -1
    property int zi: 0
    property int zRequests: 0
    property var zv: ({})
    function pressKey(key, modifiers) { tc.keyClick(key, modifiers || Qt.NoModifier) }
    function listFocus() { panel.searchItem.parent.parent.forceActiveFocus() }
    function resetZoom() { listFocus(); pressKey(Qt.Key_0, Qt.ControlModifier); check(panel.zoomPercent===100,"Ctrl+0 resets to 100") }
    function zoomIn(times) { for (var i=0;i<times;i++) pressKey(Qt.Key_Equal, Qt.ControlModifier) }
    function screenW() { return panel.cardItem.parent.width }
    function screenH() { return panel.cardItem.parent.height }
    function near(a, b, label) { check(Math.abs(a-b)<=1, label + ": " + a + " vs " + b) }
    property var zsteps: [
        function() {
            // Fixture: a fresh 40-project state under a one-hour cooldown, so no request starts during the zoom stages.
            if (!panel.opened || panel.listItem.count!==40 || screenW()<=0 || !panel.searchItem.parent.parent.activeFocus) return false
            check(panel.entries.length===40,"fixture has 40 rows")
            check(panel.cooldownText!=="","cooldown text shows")
            zRequests=panel.polling.requests
        },
        function() {
            resetZoom()
            panel.cursor=0
            pressKey(Qt.Key_J)
            check(panel.cursor===1,"delivery: j moves the cursor by one")
        },
        function() {
            resetZoom()
            pressKey(Qt.Key_Equal, Qt.ControlModifier); check(panel.zoomPercent===110,"Ctrl+= zooms in")
            pressKey(Qt.Key_Equal, Qt.ControlModifier | Qt.ShiftModifier); check(panel.zoomPercent===120,"Ctrl+Shift+= zooms in")
            pressKey(Qt.Key_Plus, Qt.ControlModifier | Qt.ShiftModifier); check(panel.zoomPercent===130,"Ctrl+Shift++ zooms in")
            pressKey(Qt.Key_Minus, Qt.ControlModifier); check(panel.zoomPercent===120,"Ctrl+- zooms out")
            pressKey(Qt.Key_0, Qt.ControlModifier); check(panel.zoomPercent===100,"Ctrl+0 resets")
        },
        function() {
            resetZoom()
            pressKey(Qt.Key_Equal, Qt.ControlModifier | Qt.AltModifier); check(panel.zoomPercent===100,"Ctrl+Alt+= is not a zoom key")
            pressKey(Qt.Key_Equal, Qt.ControlModifier | Qt.MetaModifier); check(panel.zoomPercent===100,"Ctrl+Meta+= is not a zoom key")
            var before=panel.cursor
            pressKey(Qt.Key_J)
            check(panel.cursor===before+1,"keys are still delivered after the modifier checks")
        },
        function() {
            resetZoom()
            var f=panel.searchItem
            f.forceActiveFocus()
            f.text="ab"
            f.selectAll()
            pressKey(Qt.Key_Minus, Qt.ControlModifier)
            check(panel.zoomPercent===90,"Ctrl+- zooms out from the search field")
            check(f.text==="ab" && f.selectedText==="ab" && f.activeFocus,"search field keeps its text, selection and focus")
            f.text=""
            listFocus()
        },
        function() { resetZoom(); panel.cursor=0 },
        function() {
            var f=panel.searchItem, row=panel.listItem.itemAtIndex(0)
            check(row,"first row exists")
            zv={font:f.font.pixelSize,row:row.height,pad:panel.cardItem.padding,radius:panel.cardItem.radius,hair:panel.hairlineItem.height}
            zoomIn(5)
            check(panel.zoomPercent===150,"five Ctrl+= reach 150")
        },
        function() {
            var f=panel.searchItem, row=panel.listItem.itemAtIndex(0)
            near(f.font.pixelSize, zv.font*1.5, "font scales x1.5")
            near(row.height, zv.row*1.5, "row height scales x1.5")
            near(panel.cardItem.padding, zv.pad*1.5, "card padding scales x1.5")
            check(panel.cardItem.radius===zv.radius,"corner radius unchanged")
            check(panel.hairlineItem.height===zv.hair,"hairline unchanged")
        },
        function() { resetZoom() },
        function() {
            var g=Commons.Style.gapsOut, w=panel.cardItem.width, h=panel.cardItem.height
            zv={w:w,h:h,wFree:w<screenW()-2*g-1,hFree:h<screenH()-2*g-1}
            if (!zv.wFree || !zv.hFree) console.log("SKIP growth: card already capped at 100 (w=" + zv.wFree + " h=" + zv.hFree + " free)")
            zoomIn(2)
            check(panel.zoomPercent===120,"two Ctrl+= reach 120")
        },
        function() {
            if (zv.wFree) check(panel.cardItem.width>zv.w,"card grows wider at 120")
            if (zv.hFree) check(panel.cardItem.height>zv.h,"card grows taller at 120")
            zoomIn(8)
            check(panel.zoomPercent===200,"ten Ctrl+= reach 200")
        },
        function() {
            var g=Commons.Style.gapsOut
            near(panel.cardItem.width, Math.min(Commons.Style.space(900)*2, screenW()-2*g), "card width at 200 is capped to the screen")
            near(panel.cardItem.height, Math.min(Commons.Style.space(680)*2, screenH()-2*g), "card height at 200 is capped to the screen")
        },
        function() { resetZoom(); panel.cursor=0 },
        function() {
            var l=panel.listItem
            panel.cursor=39
            l.positionViewAtIndex(0, ListView.Beginning)
            check(l.contentHeight>l.height,"list overflows at 100")
            var r=l.itemAtIndex(39)
            check(!r || r.y>=l.contentY+l.height,"row 39 is outside the viewport before zooming")
            pressKey(Qt.Key_Equal, Qt.ControlModifier)
            check(panel.zoomPercent===110,"Ctrl+= reaches 110")
        },
        function() {
            var l=panel.listItem, r=l.itemAtIndex(39)
            check(r,"row 39 exists after zooming")
            check(r.y>=l.contentY-1,"row 39 starts inside the viewport")
            check(r.y+r.height<=l.contentY+l.height+1,"row 39 ends inside the viewport")
        },
        function() { resetZoom(); panel.cursor=0 },
        function() {
            zoomIn(2)
            check(panel.zoomPercent===120,"two Ctrl+= reach 120")
            panel.cardItem.width=Commons.Style.space(300)
        },
        function() {
            var h=panel.hintItem, z=panel.zoomItem, footerWidth=z.parent.width
            check(panel.cooldownText!=="","cooldown text is the hint")
            check(h.truncated,"hint is really elided")
            check(z.visible && z.text==="120%","zoom label shows 120%")
            check(z.x+z.width<=footerWidth,"zoom label lies inside the footer")
            check(h.x+h.width<=z.x,"hint does not overlap the zoom label")
            panel.cardItem.width=Qt.binding(function() { return Math.min(panel.zs(Commons.Style.space(900)), screenW()-Commons.Style.gapsOut*2) })
        },
        function() { resetZoom() },
        function() {
            zoomIn(3)
            check(panel.zoomPercent===130,"three Ctrl+= reach 130")
            panel.close()
            panel.open("{}")
            check(panel.zoomPercent===130,"zoom survives close and open")
        },
        function() {
            if (!panel.searchItem.parent.parent.activeFocus) return false
            resetZoom()
            check(panel.polling.requests===zRequests,"the zoom stages made no requests")
            console.log("QML_CHECKS_PASSED")
            Qt.quit()
        }
    ]
    property int ei: 0
    property var live: ({})
    function rowItem(key) { return panel.listItem.itemAtIndex(panel.entries.findIndex(function(r) { return r.key===key })) }
    property double holdSince: 0
    function zRepos() { return Array.from({length:40},function(_, i) { return {repo:"z/p"+(i<10 ? "0" : "")+i,checked:"x",runs:[]} }) }
    function findByName(item, name) {
        if (item.objectName===name) return item
        for (var i=0;i<item.children.length;i++) { var f=findByName(item.children[i], name); if (f) return f }
        return null
    }
    // A delegate's icon and info follow statusColor/statusOpacity, selected or not; icon is checked when given.
    function selCheck(item, status, icon) {
        var parts=[findByName(item,"statusIcon"), findByName(item,"statusInfo")]
        check(parts[0] && parts[1],"delegate has statusIcon and statusInfo: " + status)
        if (icon) eq(parts[0].text,icon,"icon of " + status)
        parts.forEach(function(t) {
            check(Qt.colorEqual(t.color,panel.statusColor(status)),"colour of " + status)
            eq(t.opacity,panel.statusOpacity(status),"opacity of " + status)
            check(t.opacity>=0.5,"opacity at least 0.5: " + status)
        })
    }
    property int gi: 0
    property bool gPlaced: false
    function eq(actual, expected, label) { check(actual===expected, label + ": got " + JSON.stringify(actual)) }
    // True once cond has held for 300 ms, so the strip's Qt.callLater and the list's layout have run.
    function held(cond) {
        if (!cond) { holdSince=0; return false }
        if (!holdSince) { holdSince=Date.now(); return false }
        if (Date.now()-holdSince<300) return false
        holdSince=0
        return true
    }
    function inView() {
        var l=panel.listItem, r=l.itemAtIndex(39)
        check(r,"row 39 exists")
        check(r.y>=l.contentY-1 && r.y+r.height<=l.contentY+l.height+1,"row 39 is inside the viewport")
    }
    function clearStops() { panel.polling.error=""; panel.polling.catalogueError=""; panel.polling.auth=false; panel.polling.cooldown=0 }
    function rkeys() { return panel.entries.map(function(r) { return r.key }) }
    function has(key) { return rkeys().indexOf(key)>=0 }
    function cursorTo(key) { var i=rkeys().indexOf(key); check(i>=0,"row exists: " + key); panel.cursor=i }
    function arrowOf(item) {
        if (item.text && /^[▾▸] /.test(item.text)) return item.text
        for (var i=0;i<item.children.length;i++) { var f=arrowOf(item.children[i]); if (f) return f }
        return ""
    }
    function typeText(t) { for (var i=0;i<t.length;i++) tc.keyClick(t[i]) }
    function nokeys(a, label) { eq(Object.keys(a).sort().join(","),"",label) }
    property double kt: 0
    property int kcur: 0
    property int pasteCode: -1
    Process {
        id: paste
        command: ["wl-paste", "-n"]
        stdout: StdioCollector { id: pasteOut }
        onExited: function(code) { pasteCode = code }
    }
    // Returns true once cond() holds; fails the run after 5 s. Time is wall clock, not ticks.
    function waitUntil(cond, label) {
        if (kt===0) kt=Date.now()
        if (cond()) { kt=0; return true }
        check(Date.now()-kt<5000,"timeout: " + label)
        return false
    }
    function pasteStart() { pasteCode=-1; paste.running=true }
    function kP(n) {
        var u="https://gitlab.example.org/k/one/-/pipelines/" + n
        return n===1 ? {id:1,name:"Bad",status:"completed",conclusion:"failed",run_number:1,head_branch:"main",sha:"a".repeat(40),html_url:u}
                     : {id:2,name:"Good",status:"completed",conclusion:"success",run_number:2,head_branch:"main",sha:"b".repeat(40),html_url:u}
    }
    function kJ(n) {
        var u="https://gitlab.example.org/k/one/-/jobs/" + (20+n)
        return n===1 ? {id:21,name:"lintish",stage:"test",status:"completed",conclusion:"failed",allow_failure:true,html_url:u}
                     : {id:22,name:"broke",stage:"test",status:"completed",conclusion:"failed",html_url:u}
    }
    function kFixture(runs, jobs) {
        panel.filterText=""
        panel.polling.repos=[{repo:"k/one",url:"https://gitlab.example.org/k/one",checked:"x",runs:runs}]
        panel.polling.details={"k/one:2":{jobs:jobs}}
        panel.expanded=({"repo:k/one":true,"k/one:2":true,"k/one:2:stage:test":true})
        panel.adopt()
        listFocus()
        panel.cursor=0
    }
    function kPress(key, mods) { panel.notice=""; listFocus(); pressKey(key, mods) }
    property var esteps: [
        function() {
            var P=panel
            eq(P.errorHint("Authenticate with glab auth login","",true,false),"then press r","hint: glab stop")
            eq(P.errorHint("Authenticate with glab auth login","",true,true),"then press Esc and r","hint: glab stop, searching")
            eq(P.errorHint("python3 not found","",true,true),"see the shell log, then press Esc and r","hint: other stop, searching")
            eq(P.errorHint("python3 not found","",true,false),"see the shell log, then press r","hint: other stop")
            eq(P.errorHint("see the shell log","",true,false),"then press r","hint: shell log stop")
            eq(P.errorHint("x","x",false,false),"check the token's access, then press R","hint: catalogue error")
            eq(P.errorHint("x","x",false,true),"check the token's access, then press Esc and R","hint: catalogue error, searching")
            eq(P.errorHint("x","x",true,false),"check the token's access, then press R","hint: catalogue error beats stop")
            eq(P.errorHint("net","",false,false),"","hint: plain error")
            eq(P.errorHint("net","",false,true),"","hint: plain error, searching")
            eq(P.errorHint("","",false,false),"","hint: no error")
            eq(P.emptyText("e","h","c",false,0,"f"),"e — h","empty 1: error with hint beats everything")
            eq(P.emptyText("e","","c",true,1,""),"e","empty 1: error without hint")
            eq(P.emptyText("","","paused",false,0,"f"),"paused","empty 2: pause beats loading")
            eq(P.emptyText("","","",false,0,"f"),"Still discovering projects… no matches so far","empty 3: loading with filter")
            eq(P.emptyText("","","",false,0,""),"Discovering projects…","empty 3: loading")
            eq(P.emptyText("","","",true,0,""),"No projects found on this account","empty 4")
            eq(P.emptyText("","","",true,0,"x"),"No projects found on this account","empty 4 beats 5")
            eq(P.emptyText("","","",true,3,"zzz"),"No projects or pipelines match “zzz”","empty 5")
            eq(P.emptyText("","","",true,3,""),"No matching projects or pipelines","empty 6")
        },
        function() {
            check(!panel.errorItem.visible,"no strip without an error or pause")
            for (var i=0;i<5;i++) panel.polling.repos[i].checked=""
            panel.adopt()
            check(panel.placeholderItem.text.indexOf("Activity checked 35/40")>=0,"placeholder shows the activity count: " + panel.placeholderItem.text)
            for (var j=0;j<5;j++) panel.polling.repos[j].checked="x"
            panel.adopt()
        },
        function() {
            panel.polling.repos=[]
            panel.polling.catalogueComplete=false
            panel.adopt()
            check(panel.emptyItem.visible,"empty label shows while loading")
            eq(panel.emptyItem.text,"Discovering projects…","loading text")
            var top=panel.emptyItem.mapToItem(panel.listItem,0,0).y
            check(top>=0 && top+panel.emptyItem.height<=panel.listItem.height,"empty label sits inside the list: y=" + top)
        },
        function() {
            panel.polling.catalogueComplete=true
            panel.adopt()
            eq(panel.emptyItem.text,"No projects found on this account","no projects text")
        },
        function() {
            panel.polling.repos=zRepos()
            panel.adopt()
            panel.filterText="zzz"
            check(panel.emptyItem.visible,"empty label shows with no match")
            eq(panel.emptyItem.text,"No projects or pipelines match “zzz”","no match text")
            panel.filterText=""
        },
        function() {
            panel.polling.auth=true
            panel.polling.error="Authenticate with glab auth login"
            panel.adopt()
            panel.searchItem.forceActiveFocus()
            check(panel.filtering,"search box is focused")
            check(panel.errorItem.visible,"strip shows the login stop")
            check(panel.errorItem.text.indexOf("Authenticate with glab auth login")>=0 && panel.errorItem.text.indexOf("Esc and r")>=0,"strip has the error and the hint: " + panel.errorItem.text)
            check(panel.placeholderItem.text.indexOf("Authenticate")<0,"placeholder does not show the error")
        },
        function() {
            for (var i=0;i<3;i++) tc.keyClick("z")
            eq(panel.filterText,"zzz","typed filter")
            check(panel.errorItem.visible,"strip stays while typing")
            check(panel.emptyItem.text.indexOf("Authenticate with glab auth login")===0,"empty label starts with the error: " + panel.emptyItem.text)
            check(Qt.colorEqual(panel.emptyItem.color,Commons.Color.urgent),"empty label is urgent with an error")
        },
        function() {
            clearStops()
            panel.adopt()
            tc.keyClick(Qt.Key_Escape)
            eq(panel.filterText,"","Esc clears the filter")
            panel.polling.cooldown=Date.now()+3600000
            panel.adopt()
        },
        function() {
            check(panel.cooldownText!=="","pause text shows")
            check(panel.errorItem.visible,"strip shows the pause")
            eq(panel.errorItem.text,panel.cooldownText,"strip is only the pause")
            check(panel.errorItem.text.indexOf("·")<0,"no separator without an error")
            check(!panel.filtering,"list has focus")
            check(panel.placeholderItem.text.indexOf("paused")<0,"placeholder does not show the pause: " + panel.placeholderItem.text)
            check(Qt.colorEqual(panel.placeholderItem.color,Commons.Color.menu.text),"placeholder keeps its normal colour")
            panel.polling.error="Project list refused"
            panel.polling.catalogueError="Project list refused"
            panel.adopt()
            eq(panel.errorItem.text,"Project list refused — check the token's access, then press R · "+panel.cooldownText,"strip joins the error, hint and pause")
            panel.polling.error=""
            panel.polling.catalogueError=""
            panel.adopt()
        },
        // 9a
        function() {
            clearStops()
            panel.filterText=""
            panel.adopt()
            listFocus()
            pressKey(Qt.Key_End)
            eq(panel.cursor,39,"End moves the cursor to row 39")
        },
        // 9b: the strip appears
        function() {
            if (panel.errorItem.visible) return false
            panel.polling.error="short error"
            panel.adopt()
        },
        // 9c
        function() {
            if (!held(panel.errorItem.visible)) return false
            inView()
        },
        // 9d: the strip grows
        function() {
            panel.polling.error=""
            panel.polling.cooldown=Date.now()+3600000
            panel.adopt()
        },
        // 9e
        function() {
            if (panel.errorItem.text!==panel.cooldownText) return false
            panel.polling.error="word ".repeat(40)
            panel.adopt()
        },
        // 9f
        function() {
            if (!held(panel.errorItem.lineCount===2)) return false
            inView()
        },
        // 9g
        function() {
            clearStops()
            panel.adopt()
        },
        function() {
            var C=Commons.Color, table=[
                ["running",C.menu.text,1],["canceling",C.menu.text,1],["success",C.accent,1],
                ["failed",C.urgent,1],["error",C.urgent,1],["unavailable",C.urgent,1],["allowed to fail",C.urgent,0.6],
                ["manual",C.accent,1],["scheduled",C.menu.text,1],["created",C.menu.text,1],["pending",C.menu.text,1],
                ["waiting_for_resource",C.menu.text,1],["preparing",C.menu.text,1],["waiting_for_callback",C.menu.text,1],
                ["queued",C.menu.text,1],["awaiting final status",C.menu.text,1],["skipped",C.menu.text,0.5],
                ["canceled",C.menu.text,1],["neutral",C.menu.text,1],["frobnicated",C.menu.text,1]]
            table.forEach(function(r) {
                check(Qt.colorEqual(panel.statusColor(r[0]),r[1]),"statusColor " + r[0])
                eq(panel.statusOpacity(r[0]),r[2],"statusOpacity " + r[0])
            })
        },
        // Selected rows of every group: one repo row per neutral/error, one run per other group.
        function() {
            var runs=["running","success","failed","manual","scheduled","created","skipped","canceled","frobnicated"].map(function(c, i) {
                return {id:100+i,name:"r"+i,status:"completed",conclusion:c,run_number:i}
            })
            panel.polling.repos=[{repo:"g/neutral",checked:"x",runs:[]},{repo:"g/error",error:"boom"},{repo:"g/runs",checked:"x",runs:runs}]
            panel.expanded=({"repo:g/runs":true})
            panel.filterText=""
            panel.adopt()
            panel.rebuild()
            check(panel.entries.length===12,"group fixture has 12 rows: " + panel.entries.length)
            gi=0; gPlaced=false
        },
        function() {
            if (!gPlaced) {
                panel.cursor=gi
                panel.selectionChanged(true)
                panel.listItem.positionViewAtIndex(gi, ListView.Contain)
                gPlaced=true
                return false
            }
            var item=panel.listItem.itemAtIndex(gi)
            if (!item) return false
            selCheck(item,panel.entries[gi].status,"")
            gi++; gPlaced=false
            if (gi<panel.entries.length) return false
        },
        // E1: fixture
        function() {
            panel.polling.repos=[
                {repo:"a/one",checked:"x",runs:[{id:1,name:"CI",status:"completed",conclusion:"success",run_number:1,head_branch:"main"}]},
                {repo:"b/two",checked:"x",runs:[{id:2,name:"CI",status:"completed",conclusion:"success",run_number:2,head_branch:"feature-x"},{id:3,name:"CI",status:"completed",conclusion:"success",run_number:3,head_branch:"fix-y"}]}]
            panel.polling.details={"a/one:1":{jobs:[
                {id:11,name:"compile",stage:"build",status:"completed",conclusion:"success"},
                {id:12,name:"pack",stage:"build",status:"completed",conclusion:"success"},
                {id:13,name:"unit",stage:"test",status:"completed",conclusion:"success"}]}}
            panel.filterText=""
            panel.expanded=({"repo:a/one":true,"a/one:1":true,"a/one:1:stage:build":true})
            panel.adopt()
            eq(rkeys().join(","),"repo:a/one,a/one:1,a/one:1:stage:build,a/one:1:11,a/one:1:12,a/one:1:stage:test,repo:b/two","E1 rows")
            panel.searchItem.forceActiveFocus()
        },
        // E2: type feature
        function() {
            if (!panel.searchItem.activeFocus) return false
            typeText("feature")
            eq(panel.filterText,"feature","E2 typed filter")
            eq(rkeys().join(","),"repo:b/two,b/two:2","E2 rows")
            check(panel.shown["repo:b/two"],"E2 b/two auto-open")
            check(!panel.expanded["repo:b/two"],"E2 filter leaves expanded alone")
            var it=panel.listItem.itemAtIndex(0)
            check(it && arrowOf(it).indexOf("▾")===0,"E2 arrow is open: " + (it && arrowOf(it)))
            check(panel.expanded["repo:a/one"] && panel.expanded["a/one:1"] && panel.expanded["a/one:1:stage:build"],"E2 expanded keeps a/one keys")
            // Enter from the search moves to the list and must not close the auto-open first result.
            pressKey(Qt.Key_Return)
            check(panel.shown["repo:b/two"] && !panel.searchCollapsed["repo:b/two"],"E2 Enter keeps the auto-open result open")
        },
        // E3: auto-only collapse
        function() {
            if (!panel.searchItem.parent.parent.activeFocus) return false
            panel.cursor=0
            pressKey(Qt.Key_Left)
            check(panel.searchCollapsed["repo:b/two"],"E3 searchCollapsed set")
            eq(rkeys().join(","),"repo:b/two","E3 rows")
            check(!panel.expanded["repo:b/two"],"E3 expanded has no b/two")
            panel.adopt()
            eq(rkeys().join(","),"repo:b/two","E3 still collapsed after adopt")
        },
        // E4: a match arrives by poll
        function() {
            panel.polling.repos[0].runs.push({id:4,name:"CI",status:"completed",conclusion:"success",run_number:4,head_branch:"feature-z"})
            // c/three is in neither expanded nor searchCollapsed, so only autoOpen on adopt() can open it.
            panel.polling.repos.push({repo:"c/three",checked:"x",runs:[{id:5,name:"CI",status:"completed",conclusion:"success",run_number:5,head_branch:"feature-q"}]})
            panel.adopt()
            check(has("repo:a/one") && has("a/one:4"),"E4 a/one and pipeline 4 shown")
            check(panel.shown["repo:a/one"],"E4 a/one is open")
            check(!has("a/one:1"),"E4 pipeline 1 hidden")
            check(!panel.expanded["repo:c/three"] && panel.shown["repo:c/three"] && has("c/three:5"),"E4 a poll-arriving project auto-opens")
        },
        // E5: the match disappears
        function() {
            panel.polling.repos[0].runs.pop()
            panel.polling.repos.pop()
            panel.adopt()
            check(!has("repo:a/one"),"E5 a/one gone")
            check(!has("repo:c/three") && !panel.shown["repo:c/three"],"E5 c/three gone and not open")
        },
        // E6: change the search
        function() {
            panel.searchItem.forceActiveFocus()
        },
        function() {
            if (!panel.searchItem.activeFocus) return false
            panel.filterText=""
            typeText("fix")
            eq(panel.filterText,"fix","E6 typed filter")
            nokeys(panel.searchCollapsed,"E6 searchCollapsed is empty")
            check(has("repo:b/two") && has("b/two:3"),"E6 b/two and pipeline 3 shown")
            check(panel.shown["repo:b/two"],"E6 b/two auto-open")
            listFocus()
        },
        function() {
            if (!panel.searchItem.parent.parent.activeFocus) return false
            cursorTo("b/two:3")
            pressKey(Qt.Key_Right)
            check(panel.expanded["b/two:3"],"E6 Right opens pipeline 3")
        },
        // E7: explicit project collapse
        function() {
            cursorTo("repo:b/two")
            pressKey(Qt.Key_Right)
            check(panel.searchCollapsed["repo:b/two"],"E7.1 first Right closes the auto-open row")
            pressKey(Qt.Key_Right)
            check(panel.expanded["repo:b/two"] && !panel.searchCollapsed["repo:b/two"],"E7.2 second Right opens explicitly")
            pressKey(Qt.Key_Left)
            check(!panel.expanded["repo:b/two"] && panel.searchCollapsed["repo:b/two"],"E7.3 Left collapses")
            panel.adopt()
            check(panel.searchCollapsed["repo:b/two"] && !panel.shown["repo:b/two"],"E7.3 still collapsed after adopt")
            pressKey(Qt.Key_Right)
            check(panel.expanded["repo:b/two"],"E7.4 Right opens explicitly again")
            panel.searchItem.forceActiveFocus()
        },
        // E8: clear the filter
        function() {
            if (!panel.searchItem.activeFocus) return false
            pressKey(Qt.Key_Escape)
            eq(panel.filterText,"","E8 Esc clears the filter")
            Object.keys(panel.shown).forEach(function(k) { check(panel.expanded[k],"E8 shown key is expanded: " + k) })
            Object.keys(panel.expanded).forEach(function(k) { check(panel.shown[k],"E8 expanded key is shown: " + k) })
            ;["repo:a/one","a/one:1","a/one:1:stage:build","a/one:1:11","a/one:1:12","repo:b/two","b/two:2","b/two:3"].forEach(function(k) { check(has(k),"E8 row restored: " + k) })
            check(panel.expanded["b/two:3"],"E8 pipeline 3 still expanded")
        },
        // E9: key boundaries on restored rows
        function() {
            var n=Object.keys(panel.expanded).length
            cursorTo("a/one:1:11")
            pressKey(Qt.Key_Right)
            eq(Object.keys(panel.expanded).length,n,"E9 Right on a job adds no key")
            pressKey(Qt.Key_Left)
            eq(panel.current.key,"a/one:1:stage:build","E9 Left moves to the stage")
        },
        // E10: +N more
        function() {
            panel.polling.repos[0].hidden={running:3}
            panel.adopt()
            panel.filterText="a/one"
            var at=panel.entries.findIndex(function(r) { return r.kind==="more" && r.parent==="repo:a/one" })
            check(at>=0,"E10 more row under a/one")
            panel.cursor=at
            var n=Object.keys(panel.expanded).length
            pressKey(Qt.Key_Right)
            eq(Object.keys(panel.expanded).length,n,"E10 Right on more adds no key")
            pressKey(Qt.Key_Left)
            eq(panel.current.key,"repo:a/one","E10 Left moves to the project")
            panel.filterText="main"
            check(has("repo:a/one"),"E10 a/one shown through pipeline 1")
            check(!panel.entries.some(function(r) { return r.kind==="more" }),"E10 no more row")
            panel.filterText=""
        },
        function() {
            // S1: live times. Build the whole fixture, then adopt once.
            var t=Date.now()
            function iso(ms) { return new Date(ms).toISOString() }
            panel.filterText=""
            var R1={id:1,name:"MR",status:"completed",conclusion:"success",run_number:1,head_branch:"refs/merge-requests/42/head",run_started_at:iso(t-70000),completed_at:iso(t-2000)}
            var R2={id:2,name:"Live",status:"in_progress",conclusion:"running",run_number:2,head_branch:"main",run_started_at:iso(t-30000)}
            panel.polling.repos=[{repo:"t/live",checked:iso(t-5000),runs:[R1,R2]}]
            panel.polling.details={"t/live:2":{jobs:[
                {id:21,name:"spin",stage:"build",status:"in_progress",conclusion:"running",started_at:iso(t-30000),duration:5},
                {id:22,name:"boom",stage:"build",status:"completed",conclusion:"failed",failure_reason:"script_failure",duration:62,queued_duration:40,started_at:iso(t-100000),completed_at:iso(t-20000)}]}}
            panel.expanded=({"repo:t/live":true,"t/live:2":true,"t/live:2:stage:build":true})
            panel.adopt()
            eq(panel.entries.length,6,"S1 six rows")
            panel.cursor=0
            panel.listItem.positionViewAtIndex(0, ListView.Beginning)
        },
        function() {
            // S2 baseline and S3 static checks, in one tick.
            var l=panel.listItem
            for (var i=0;i<6;i++) if (!l.itemAtIndex(i)) return false
            var run1=rowItem("t/live:1"), spin=rowItem("t/live:2:21"), boom=rowItem("t/live:2:22")
            check(run1 && spin && boom,"S2 rows exist")
            live={key0:panel.current.key,y0:l.contentY,req0:panel.polling.requests,ents:panel.entries,
                  a1:findByName(run1,"statusInfo").text,aSpin:findByName(spin,"statusInfo").text,t0:Date.now()}
            var sub=findByName(run1,"rowSubtitle").text
            check(sub.indexOf("!42")===0,"S3 subtitle starts with !42: " + sub)
            var b=findByName(boom,"statusInfo").text
            check(b.indexOf("script failure")>=0 && b.indexOf("1m 2s")>=0 && b.indexOf("queued 40s")>=0,"S3 boom info: " + b)
            check(live.a1.indexOf("just now")>=0,"S3 run 1 says just now: " + live.a1)
        },
        function() {
            // S4: both clocks advance, with the view stable on every pass.
            var run1=rowItem("t/live:1"), spin=rowItem("t/live:2:21")
            check(run1 && spin,"S4 rows exist")
            eq(panel.current.key,live.key0,"S4 cursor row")
            eq(panel.listItem.contentY,live.y0,"S4 contentY")
            eq(panel.polling.requests,live.req0,"S4 no requests")
            check(panel.entries===live.ents,"S4 entries not rebuilt")
            var a1=findByName(run1,"statusInfo").text, s=findByName(spin,"statusInfo").text
            if (a1.indexOf("s ago")>=0 && s!==live.aSpin) { live.spin=s; return }
            check(Date.now()-live.t0<15000,"S4 clocks advance within 15 s: " + a1 + " | " + s)
            return false
        },
        function() {
            // S5: the running job ignores the server snapshot (5s).
            var d=live.spin.split(" · ")[1], m=/^(?:(\d+)m )?(\d+)s$/.exec(d)
            check(d!=="5s" && m,"S5 duration part is live: " + d)
            check(m && (+(m[1]||0))*60+(+m[2])>=30,"S5 at least 30 s: " + d)
        },
        function() {
            // K1: fixture. Rows: repo, P1 (failed), P2, stage test (failed), lintish (allowed), broke (failed).
            kFixture([kP(1),kP(2)],[kJ(1),kJ(2)])
            eq(panel.entries.length,6,"K1 six rows")
        },
        function() {
            // K2: g/G, e, Ctrl+e, no failure.
            pressKey(Qt.Key_G, Qt.ShiftModifier); eq(panel.cursor,5,"K2 G")
            pressKey(Qt.Key_G); eq(panel.cursor,0,"K2 g")
            pressKey(Qt.Key_End); eq(panel.cursor,5,"K2 End")
            pressKey(Qt.Key_Home); eq(panel.cursor,0,"K2 Home")
            var want=[1,3,5,1]
            for (var i=0;i<want.length;i++) { pressKey(Qt.Key_E); eq(panel.cursor,want[i],"K2 e step " + i) }
            panel.cursor=0
            pressKey(Qt.Key_E, Qt.ControlModifier); eq(panel.cursor,0,"K2 Ctrl+e does nothing")
            kFixture([kP(2)],[kJ(1)])
            kPress(Qt.Key_E)
            eq(panel.cursor,0,"K2 no failure keeps cursor")
            eq(panel.notice,"No failures in the list","K2 no failure notice")
            kFixture([kP(1),kP(2)],[kJ(1),kJ(2)])
        },
        function() {
            // K3: copy URL.
            panel.cursor=1
            kPress(Qt.Key_Y)
            kt=0
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Copied URL" },"K3 notice")) return false
            pasteStart()
        },
        function() {
            if (!waitUntil(function() { return pasteCode>=0 },"K3 paste")) return false
            eq(pasteCode,0,"K3 wl-paste exit")
            eq(pasteOut.text,kP(1).html_url,"K3 clipboard is the URL")
        },
        function() {
            // K4: copy SHA.
            panel.cursor=5
            kPress(Qt.Key_Y, Qt.ShiftModifier)
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Copied bbbbbbbb" },"K4 notice")) return false
            pasteStart()
        },
        function() {
            if (!waitUntil(function() { return pasteCode>=0 },"K4 paste")) return false
            eq(pasteCode,0,"K4 wl-paste exit")
            eq(pasteOut.text,"b".repeat(40),"K4 clipboard is the SHA")
            panel.cursor=0
            kPress(Qt.Key_Y, Qt.ShiftModifier)
            eq(panel.notice,"No commit for this row","K4 repo row notice")
            pasteStart()
        },
        function() {
            if (!waitUntil(function() { return pasteCode>=0 },"K4 second paste")) return false
            eq(pasteCode,0,"K4 second wl-paste exit")
            eq(pasteOut.text,"b".repeat(40),"K4 clipboard unchanged")
        },
        function() {
            // K5: copy failures.
            panel.cursor=1
            panel.copyCommand=["gltui-no-such-binary"]
            kPress(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Copy failed" },"K5 missing binary")) return false
            panel.copyCommand=["false"]
            kPress(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Copy failed" },"K5 exit code")) return false
        },
        function() {
            // K6: a late copy result after close and reopen is dropped.
            panel.copyCommand=["sh","-c","sleep 1","sh"]
            panel.cursor=1
            kPress(Qt.Key_Y)
            pressKey(Qt.Key_Q)
            check(!panel.opened,"K6 q closes")
            panel.open("{}")
            kt=Date.now()+2000
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            eq(panel.notice,"","K6 no late notice")
            check(!panel.helpOpen,"K6 help closed")
            panel.copyCommand=["wl-copy","--"]
            panel.adopt()
            listFocus()
        },
        function() {
            // K7: help.
            panel.cursor=2
            kcur=panel.cursor
            listFocus()
            tc.keyClick("?")
            check(panel.helpOpen && panel.helpItem.visible,"K7 ? opens help")
        },
        function() {
            if (!waitUntil(function() { return panel.helpText.indexOf("Next failed pipeline")>=0 },"K7 help text")) return false
            for (var i=0;i<30 && panel.zoomPercent<200;i++) pressKey(Qt.Key_Equal, Qt.ControlModifier)
            eq(panel.zoomPercent,200,"K7 zoom works in help")
        },
        function() {
            if (!waitUntil(function() { return panel.helpFlick.contentHeight>panel.helpFlick.height },"K7 help overflows")) return false
            pressKey(Qt.Key_J); check(panel.helpFlick.contentY>0,"K7 j scrolls down")
            pressKey(Qt.Key_K); eq(panel.helpFlick.contentY,0,"K7 k scrolls up")
            pressKey(Qt.Key_E); eq(panel.cursor,kcur,"K7 e ignored in help")
            pressKey(Qt.Key_Escape)
            check(!panel.helpOpen,"K7 Esc closes help")
            check(panel.opened,"K7 Esc keeps the panel open")
            eq(panel.cursor,kcur,"K7 cursor unchanged")
            resetZoom()
            tc.keyClick("?"); check(panel.helpOpen,"K7 ? reopens help")
            check(panel.helpFlick.contentY===0,"K7 help reopens at the top")
            tc.keyClick("?"); check(!panel.helpOpen && panel.opened,"K7 ? closes help only")
            tc.keyClick("?"); pressKey(Qt.Key_Q); check(!panel.helpOpen && panel.opened,"K7 q closes help only")
            // close() itself must reset help and the notice.
            tc.keyClick("?"); panel.notify("x")
            panel.close()
            panel.open("{}")
            check(!panel.helpOpen,"K7 close() resets help")
            eq(panel.notice,"","K7 close() clears the notice")
            panel.adopt()
            listFocus()
        },
        function() {
            // K8: q with a filter closes; q ? g y e type into search.
            panel.filterText="k"
            listFocus()
            panel.notify("x")
            pressKey(Qt.Key_Q)
            check(!panel.opened,"K8 q closes with a filter")
            panel.open("{}")
            check(!panel.helpOpen,"K8 help closed after reopen")
            eq(panel.notice,"","K8 no notice after reopen")
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.parent.parent.activeFocus },"K8 list focus")) return false
            pressKey(Qt.Key_Slash)
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.activeFocus },"K8 search focus")) return false
            typeText("q?gye")
            eq(panel.filterText,"q?gye","K8 typed into search")
            check(panel.opened,"K8 panel stays open")
            eq(panel.footerHint,panel.searchHint,"K8 search hint")
            pressKey(Qt.Key_Escape)
            panel.adopt()
        },
        function() {
            panel.filterText=""
            panel.polling.repos=[{repo:"o/alpha",checked:"x",runs:[]},{repo:"o/beta",checked:"x",runs:[]},{repo:"x/gamma",checked:"x",runs:[]}]
            panel.expanded=({})
            panel.adopt()
            listFocus()
            panel.cursor=2
            panel.open('{"filter":"o/beta"}')
            eq(panel.filterText,"o/beta","O3 filter applied")
            eq(panel.cursor,0,"O3 cursor reset")
            eq(panel.entries[0].key,"repo:o/beta","O3 first row")
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.parent.parent.activeFocus },"O4 list focus")) return false
            panel.searchItem.forceActiveFocus()
        },
        function() {
            check(panel.filtering,"O4 search focused before the open")
            panel.open('{"filter":"o/alpha"}')
            eq(panel.filterText,"o/alpha","O4 filter applied")
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.parent.parent.activeFocus },"O4 list focus again")) return false
            panel.filterText="o"
            panel.adopt()
            panel.cursor=1
            panel.helpOpen=true
            panel.open('{"filter":"o"}')
            check(!panel.helpOpen,"O5 help closed")
            eq(panel.cursor,0,"O5 cursor reset on same filter")
            panel.filterText="o"
            panel.cursor=1
            panel.open("{}")
            panel.open("{bad")
            panel.open('{"filter":"' + "x".repeat(201) + '"}')
            panel.open('[]')
            eq(panel.filterText,"o","O6 filter unchanged")
            eq(panel.cursor,1,"O6 cursor unchanged")
            panel.open('{"filter":"o/alpha"}')
            panel.open('{"filter":"o/beta"}')
            panel.open("{bad")
            eq(panel.filterText,"o/beta","O7 last valid wins")
            panel.open(JSON.stringify({filter:"o/alpha",host:"elsewhere.example"}))
            eq(panel.filterText,"o/beta","O8 mismatch keeps filter")
            check(panel.notice.indexOf("Repository is on elsewhere.example")===0,"O8 mismatch notice")
            panel.open(JSON.stringify({filter:"o/alpha",host:panel.host.toUpperCase()}))
            eq(panel.filterText,"o/alpha","O8 host match filters")
            eq(panel.notice,"","O8 no notice on match")
        },
        function() {
            function cfg(h) { panel.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"' + h + '"}]}') }
            panel.configured=false
            panel.filterText="o"
            panel.open('{"filter":"o/beta"}')
            eq(panel.filterText,"o","O9 queued, filter unchanged")
            eq(panel.pendingOpen.length,1,"O9 queued length")
            cfg("gitlab.example.org")
            check(panel.configured,"O9 configured after configure")
            eq(panel.pendingOpen.length,0,"O9 queue drained")
            eq(panel.filterText,"o/beta","O9 queued filter applied")
            panel.configured=false
            panel.filterText="o"
            panel.open(JSON.stringify({filter:"o/alpha",host:"gitlab.example.org"}))
            cfg("gitlab.other.org")
            eq(panel.host,"gitlab.other.org","O9 host changed")
            eq(panel.filterText,"o","O9 old host rejected")
            check(panel.notice.indexOf("Repository is on gitlab.example.org")===0,"O9 old host notice")
            panel.configured=false
            panel.open(JSON.stringify({filter:"o/beta",host:"gitlab.other.org"}))
            cfg("gitlab.other.org")
            eq(panel.filterText,"o/beta","O9 new host accepted")
            eq(panel.notice,"","O9 no notice on accepted host")
            cfg("gitlab.example.org")
            panel.filterText=""
            panel.adopt()
        },
        function() {
            panel.workerBusy=false
            panel.close()
            panel.polling=Polling.create()
            panel.polling.repos=zRepos()
            panel.polling.discover=false
            panel.polling.catalogueComplete=true
            panel.polling.catalogueAt=Date.now()
            // Set before open(): open() pumps at once and the cooldown is what keeps Polling.next from returning a request.
            panel.polling.cooldown=Date.now()+3600000
            panel.expanded=({})
            panel.filterText=""
            panel.open("{}")
            panel.adopt()
            stage=11
        }
    ]
    Timer {
        interval: 1000; running: true
        onTriggered: {
            check(panel.configured,"configured without shell.json")
            check(Commons.Color.background.toString()===Quickshell.env("EXPECTED_BACKGROUND"),"active Omarchy theme")
            menuFile.reload()
            check(!panel.opened && panel.polling.requests===0,"registration does not open or poll")
            if (Quickshell.env("MENU_SCENARIO") === "fresh")
                check(menuFile.text().indexOf('"apps.gitlab-pipelines"') >= 0,"registered while closed")
            panel.polling=Polling.create()
            panel.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"bad host"}]}')
            check(panel.error.indexOf("Configuration: invalid host")===0 && panel.host==="gitlab.com","invalid host rejected")
            panel.error=""
            panel.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.example.org","projects":["one/sub/repo","two/repo","bad/../x"]}]}')
            check(panel.entries.length===2 && panel.host==="gitlab.example.org","configured projects and host")
            panel.polling.repos[0].runs=[{id:7,name:"CI",status:"in_progress",conclusion:"running",run_attempt:"active"}]
            panel.expanded={"repo:one/sub/repo":true}
            panel.adopt()
            panel.move(1)
            check(panel.current.kind==="run","keyboard selection")
            panel.expand(false)
            check(panel.entries[2].title==="Loading jobs…","expand run")
            panel.expand(true)
            check(panel.entries.length===3,"collapse run retains other repository")
            // Selection sync: a row that drops from the filtered list must not leave a stale inspected run behind.
            panel.polling.repos[0].runs.push({id:8,name:"CI",status:"in_progress",conclusion:"running",run_attempt:"active"})
            panel.polling.wakeAt=0
            panel.adopt()
            panel.filterText="ci"
            panel.expanded={"repo:one/sub/repo":true}
            panel.rebuild()
            for (var i=0;i<panel.entries.length;i++) if (panel.entries[i].run==="7") panel.cursor=i
            panel.selectionChanged(false)
            check(panel.polling.inspected==="7","run 7 inspected before it drops")
            panel.polling.repos[0].runs[0].name="Zed"
            panel.polling.wakeAt=0
            panel.adopt()
            check(!panel.entries.some(function(row) { return row.run==="7" }) && panel.entries.length>0,"filtered row dropped, project stays")
            check(panel.polling.inspected===(panel.current && panel.current.run || ""),"selection follows the visible row")
            var mark={}
            panel.polling.expanded=mark
            panel.adopt()
            check(panel.polling.expanded===mark,"adopt does not reselect when selection is in sync")
            panel.polling.repos[0].runs=[panel.polling.repos[0].runs[0]]
            panel.polling.repos[0].runs[0].name="CI"
            panel.polling.wakeAt=0
            panel.filterText=""
            panel.adopt()
            panel.selectionChanged(false)
            panel.filterText="no-match"
            check(panel.entries.length===0,"filter")
            panel.expanded=({})
            panel.filterText="repo"
            check(panel.cursor===0 && panel.entries.length===2,"name matches are not auto-opened")
            panel.expand(false)
            panel.move(1)
            panel.expand(false)
            selected=panel.current.key
            panel.open("{}")
            stage=1
        }
    }
    Timer {
        interval: 250; running: true; repeat: true
        onTriggered: {
            if(stage===1 && panel.polling.requests>=6 && panel.details["one/sub/repo:7"] && panel.polling.catalogueComplete) {
                check(panel.error==="","async API has no error")
                check(panel.current.key===selected && panel.filterText==="repo","poll preserves searched selection")
                check(panel.details["one/sub/repo:7"].jobs.length===3,"jobs arrive")
                check(panel.entries.filter(function(row) { return row.kind==="stage" }).length===2,"jobs grouped into stages")
                check(panel.polling.catalogueComplete,"catalogue completed")
                panel.expanded["one/sub/repo:7:stage:test"]=true
                panel.rebuild()
                lintIndex=panel.entries.findIndex(function(row) { return row.kind==="job" && row.title==="lint" })
                check(lintIndex>=0,"lint row exists")
                eq(panel.entries[lintIndex].status,"allowed to fail","lint row status")
                eq(panel.entries[lintIndex].info,"1m 2s","lint row info")
                panel.cursor=lintIndex
                panel.selectionChanged(true)
                panel.listItem.positionViewAtIndex(lintIndex, ListView.Contain)
                stage=12
            } else if(stage===12) {
                // A poll reply between ticks can rebuild and shift rows, so find lint again.
                var at=panel.entries.findIndex(function(row) { return row.kind==="job" && row.title==="lint" })
                if (at!==lintIndex) { lintIndex=at; panel.listItem.positionViewAtIndex(at, ListView.Contain); return }
                var lintItem=panel.listItem.itemAtIndex(lintIndex)
                if (!lintItem) return
                selCheck(lintItem,"allowed to fail","!")
                delete panel.expanded["one/sub/repo:7:stage:test"]
                panel.rebuild()
                panel.close()
                closedRequests=panel.polling.requests
                closedAt=Date.now()
                stage=2
            } else if(stage===2 && Date.now()-closedAt>1200) {
                check(!panel.workerBusy && !panel.polling.flight,"close settles worker")
                check(panel.polling.requests===closedRequests,"closed panel starts no requests")
                var history=panel.polling.starts.length
                panel.open("{}")
                check(panel.polling.starts.length>=history,"reopen preserves budget")
                panel.close()
                stage=3
            } else if(stage===3 && !panel.workerBusy && Date.now()-(panel.polling.starts[panel.polling.starts.length-1] || 0)>1100) {
                // Polling.next spaces request starts by at least 1s. open() already pumps, so refresh overlaps that flight and discards its reply.
                panel.open("{}")
                panel.refresh(false)
                panel.pump()
                check(panel.workerBusy && panel.polling.flight,"refresh overlaps a request")
                // open() pumps whichever task is due first; refresh() only discards the reply when that flight is the selected summary.
                var discarded=panel.polling.tasks[panel.polling.flight.key].restart===true
                panel.failedToStart()
                check(!panel.workerBusy,"failed start releases the worker")
                if (discarded) check(panel.polling.error==="" && !panel.polling.auth,"refresh discards the overlapped reply")
                else check(panel.polling.error==="python3 not found" && panel.polling.auth,"a reply refresh did not restart is delivered")
                panel.close()
                stage=4
            } else if(stage===4 && !panel.workerBusy && Date.now()-(panel.polling.starts[panel.polling.starts.length-1] || 0)>1100) {
                panel.open("{}")
                panel.pump()
                check(panel.workerBusy && panel.polling.flight,"open starts a request")
                // Quickshell reports a start failure only as running=false; drive the handler it calls.
                panel.failedToStart()
                check(!panel.workerBusy && panel.polling.error==="python3 not found" && panel.polling.auth,"failed start stops with setup error")
                panel.close()
                stage=5
            } else if(stage===5 && !panel.workerBusy && Date.now()-(panel.polling.starts[panel.polling.starts.length-1] || 0)>1100) {
                panel.open("{}")
                stage=6
            } else if(stage===6 && !panel.workerBusy && !panel.polling.flight) {
                // Worker release: create a flight without a process, then make the rebuild throw.
                panel.polling.expanded={}
                panel.polling.discover=true
                panel.polling.wakeAt=0
                var request=Polling.next(panel.polling, Date.now()+5000)
                check(request,"flight created without a process")
                panel.requestInfo=request
                panel.workerBusy=true
                panel.polling.details["one/sub/repo:7"]={jobs:{}}
                panel.polling.wakeAt=0
                panel.expanded={"repo:one/sub/repo":true,"one/sub/repo:7":true}
                var caught=false
                try {
                    panel.finishRequest(JSON.stringify({requestId:request.requestId,data:request.kind==="catalogue" ? [{repo:"one/sub/repo"},{repo:"two/repo"}] : request.kind==="run" ? {id:7,status:"in_progress"} : [],nextPage:0,error:"",errorType:"",remaining:4000}),0)
                } catch (e) { caught=true }
                check(caught,"rebuild failure reached the caller")
                check(!panel.workerBusy,"worker released after a throwing rebuild")
                delete panel.polling.details["one/sub/repo:7"]
                panel.polling.wakeAt=0
                panel.expanded={}
                panel.adopt()
                stage=7
            } else if(stage===7 && !panel.workerBusy && Date.now()-(panel.polling.starts[panel.polling.starts.length-1] || 0)>1100) {
                // Host change during a real flight.
                panel.refresh(true)
                check(panel.workerBusy && panel.polling.flight,"catalogue refresh starts a real flight")
                var before=panel.polling.generation
                panel.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.other.org","projects":["three/repo"]}]}')
                check(panel.entries.length===1 && panel.entries[0].repo==="three/repo","host change shows only the new host's projects")
                check(Object.keys(panel.expanded).length===0,"host change clears expansion")
                check(panel.polling.generation>before,"host change starts a new generation")
                stage=8
            } else if(stage===8 && panel.requestInfo.host==="gitlab.other.org") {
                check(!panel.repos.some(function(r) { return r.repo==="one/sub/repo" }),"old host data did not reappear")
                panel.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.example.org","projects":["one/sub/repo","two/repo"]}]}')
                stage=9
            } else if(stage===9 && !panel.workerBusy && !panel.polling.flight) {
                panel.close()
                panel.polling=Polling.create()
                panel.polling.repos=zRepos()
                panel.polling.discover=false
                panel.polling.catalogueComplete=true
                panel.polling.catalogueAt=Date.now()
                // workerBusy before open(): open() pumps at once, and with it set nothing starts, so the error and empty states stay put.
                panel.workerBusy=true
                panel.expanded=({})
                panel.filterText=""
                panel.open("{}")
                panel.adopt()
                stage=10
            } else if(stage===10) {
                var estep=esteps[ei]
                if (estep() !== false) ei++
            } else if(stage===11) {
                var step=zsteps[zi]
                if (step() !== false) zi++
            }
        }
    }
}
''')
        try:
            result=subprocess.run(['quickshell','-p',str(root),'--no-color'],capture_output=True,text=True,timeout=110,
                                  env={**os.environ, 'HOME':str(home), 'MENU_SCENARIO':scenario, 'EXPECTED_BACKGROUND':colors['background'].lower()})
        except subprocess.TimeoutExpired as error:
            print(error.stdout, error.stderr)
            raise
        output=result.stdout+result.stderr
        print(output)
        if result.returncode or 'QML_CHECKS_PASSED' not in output or any(term in output for term in ('ERROR:', 'ReferenceError','TypeError','CHECK FAILED','binding loop')):
            raise SystemExit('QML smoke check failed')
        if scenario == 'managed':
            assert 'GitLab Pipelines menu registration failed:' in output and 'Menu is managed:' in output
            assert menu_path.is_symlink() and menu_path.read_text() == '{}\n'
        else:
            assert 'menu registration failed' not in output
            assert '"apps.gitlab-pipelines"' in menu_path.read_text()
