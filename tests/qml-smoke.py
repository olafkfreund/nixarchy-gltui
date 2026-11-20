"""Exercise the real QML worker with a temporary fake API; no live GitLab requests."""
import argparse
import os
from pathlib import Path
import shlex
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
        widget_source = source / 'bar-widget'
        widget_available = widget_source.is_dir()
        if widget_available:
            widget_target = root / 'bar-widget'
            widget_target.mkdir()
            for name in ('manifest.json', 'BarWidget.qml', 'BarModel.js', 'LICENSE'):
                assert (widget_source / name).is_file(), f'missing widget file: {name}'
                (widget_target / name).symlink_to(widget_source / name)
        for name in ('Commons', 'Ui'):
            (root / name).symlink_to(shell / name)
        for name in ('PipelinesPanel.qml', 'PipelinesModel.js', 'Polling.js', 'keybindings.sh', 'menu.py', 'menu.example.json'):
            (root / name).symlink_to(source / name)
        (root / 'gitlab.py').write_text("REAL = " + repr(str(source / 'gitlab.py')) + '''
import importlib.util, json, os, sys, time
if sys.argv[1] == 'pins':
    # Only saves are delayed, so a load can overtake a pending save.
    if 'save' in json.loads(sys.argv[2]) and os.path.exists(os.environ['PINS_DELAY']): time.sleep(1.5)
    spec = importlib.util.spec_from_file_location('real_gitlab', REAL)
    real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)
    sys.exit(real.main())
request=json.loads(sys.argv[2]); kind=request['kind']
with open(os.environ['HOST_LOG'], 'a') as log: log.write(request.get('host', '') + '\\n')
time.sleep(0.1)
host=request.get('host'); assert host in ('gitlab.example.org','gitlab.other.org'), request
multi=os.path.exists(os.environ['MULTI']) and host=='gitlab.other.org'
delayed=host=='gitlab.other.org' and os.path.exists(os.environ['OTHER_DELAY'])
if delayed: time.sleep(1.5)
if host=='gitlab.other.org' and os.path.exists(os.environ['OTHER_AUTH']):
    print(json.dumps({'requestId':request['requestId'],'error':'Authenticate with glab auth login','errorType':'auth','remaining':4000})); sys.exit()
run={'id':7,'name':'LATE' if delayed else 'CI','status':'in_progress','conclusion':'running','run_attempt':'active','head_branch':'main','run_number':1}
if multi: run['html_url']='https://gitlab.other.org/one/sub/repo/-/pipelines/7'
if kind=='mr' and os.path.exists(os.environ['MR_DELAY']): time.sleep(1.5)
if host=='gitlab.other.org' and not multi: data={} if kind in ('run','mr') else [{'id':3,'repo':'three/repo'}] if kind=='catalogue' else []
elif multi and kind=='catalogue': data=[{'id':1,'repo':'one/sub/repo','url':'https://gitlab.other.org/one/sub/repo','description':'LATE' if delayed else ''},{'id':2,'repo':'two/repo','url':'https://gitlab.other.org/two/repo'}]
elif multi and kind=='mrs': data=[{'id':101,'iid':1,'project_id':1,'project':'one/sub/repo','title':'Update CI','source_branch':'ci','draft':False,'web_url':'https://gitlab.other.org/one/sub/repo/-/merge_requests/1','updated_at':'2026-11-19T00:00:00Z'}]
elif kind=='catalogue': data=[{'id':1,'repo':'one/sub/repo','url':'https://gitlab.example.org/one/sub/repo'},{'id':2,'repo':'two/repo'}]
elif kind=='mrs': data=[{'id':101,'iid':1,'project_id':1,'project':'one/sub/repo','title':'Update CI','source_branch':'ci','draft':False,'web_url':'https://gitlab.example.org/one/sub/repo/-/merge_requests/1','updated_at':'2026-11-19T00:00:00Z'},
                        {'id':102,'iid':2,'project_id':99,'project':'outside/repo','title':'Outside change','source_branch':'other','draft':False,'web_url':'https://gitlab.example.org/outside/repo/-/merge_requests/2','updated_at':'2026-11-19T00:00:00Z'}]
elif kind=='mr': data={'iid':request['iid'],'project_id':request['project'],'pipelineState':'ok','pipeline':dict(run,id=7 if request['project']==1 else 8,project_id=request['project'])}
elif kind=='jobs': data=[{'id':8,'name':'compile','stage':'build','status':'in_progress','conclusion':'running'},{'id':9,'name':'unit','stage':'test','status':'queued','conclusion':'created'},{'id':10,'name':'lint','stage':'test','status':'completed','conclusion':'failed','allow_failure':True,'started_at':'2026-01-01T00:00:00Z','completed_at':'2026-01-01T00:01:02Z'}]
elif kind=='bridges': data=[{'id':11,'name':'deploy','stage':'test','status':'in_progress','conclusion':'running','downstream':{'id':501,'iid':5,'project_id':2,'parent_project_id':1,'status':'in_progress','conclusion':'running','ref':'main','sha':'','url':'https://gitlab.example.org/two/repo/-/pipelines/501','project':'two/repo'}}]
elif kind=='run':
    if os.path.exists(os.environ['RUN_DELAY']): time.sleep(1.5)
    data=dict(run,status='completed',conclusion='success') if os.path.exists(os.environ['RUN_DONE']) else run
else: data=[run] if request['repo']=='one/sub/repo' and request.get('status','running') in ('recent','running') else []
if delayed and kind in ('jobs','bridges') and data: data[0]['name']='LATE'
if delayed and kind=='mrs' and data: data[0]['title']='LATE'
if delayed and kind=='mr' and isinstance(data,dict) and data.get('pipeline'): data['pipeline']['name']='LATE'
print(json.dumps({'requestId':request['requestId'],'data':data,'total':len(data) if kind=='mrs' else 0,'nextPage':0,'error':'','errorType':'','remaining':4000}))
''')
        (root / 'actions.log').write_text('')
        (root / 'host.log').write_text('')
        (root / 'omarchy-shell.log').write_text('')
        (root / 'bin').mkdir()
        toggle = root / 'bin' / 'omarchy-shell'
        toggle.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TOGGLE_LOG"\n')
        toggle.chmod(0o755)
        (root / 'action.sh').write_text('''#!/bin/sh
reply=$1
delay=$2
for task; do :; done
printf '%s\\n' "$task" >> ACTION_LOG
id=$(printf '%s\\n' "$task" | sed -n 's/.*"requestId":\\([0-9]*\\).*/\\1/p')
sleep "$delay"
printf '%s\\n' "$reply" | sed "s/@ID@/$id/g"
'''.replace('ACTION_LOG', shlex.quote(str(root / 'actions.log'))))
        home = root / 'home'
        home.mkdir()
        theme = home / '.local/state/omarchy/current/theme'
        theme.parent.mkdir(parents=True)
        theme.symlink_to(Path.home() / '.local/state/omarchy/current/theme')
        state = home / '.local/state/omarchy-gitlab-pipelines'
        state.mkdir()
        (state / 'pinned.json').write_text('{"version":1,"hosts":{"gitlab.com":["zz/saved"]}}')
        (home / '.config').mkdir()
        (home / '.config/fontconfig').symlink_to(Path.home() / '.config/fontconfig')
        (home / '.config/omarchy').mkdir()
        (home / '.config/omarchy/shell.toml').symlink_to(Path.home() / '.config/omarchy/shell.toml')
        menu_path = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
        if scenario == 'managed':
            menu_path.parent.mkdir(parents=True)
            (home / 'managed-menu').write_text('{}\n')
            menu_path.symlink_to(home / 'managed-menu')
        widget_objects = '''
    QtObject {
        id: fakeBarA
        property bool vertical: false
        property int barSize: 32
        property string fontFamily: "sans"
        property color barForeground: "white"
        property color urgent: "red"
        property bool foregroundAnimationEnabled: false
        property var lastTarget: null
        property string lastTooltip: ""
        function showTooltip(target, text) { lastTarget=target; lastTooltip=text }
        function hideTooltip(target) { if (lastTarget===target) lastTarget=null }
        function registerClickTarget(target) {}
        function unregisterClickTarget(target) {}
    }
    QtObject {
        id: fakeBarB
        property bool vertical: true
        property int barSize: 32
        property string fontFamily: "sans"
        property color barForeground: "white"
        property color urgent: "red"
        property bool foregroundAnimationEnabled: false
        property var lastTarget: null
        property string lastTooltip: ""
        function showTooltip(target, text) { lastTarget=target; lastTooltip=text }
        function hideTooltip(target) { if (lastTarget===target) lastTarget=null }
        function registerClickTarget(target) {}
        function unregisterClickTarget(target) {}
    }
    BarPlugin.BarWidget { id: widgetA; bar: fakeBarA; statusPath: Quickshell.env("WIDGET_STATUS_PATH"); width: implicitWidth; height: implicitHeight }
    BarPlugin.BarWidget { id: widgetB; bar: fakeBarB; statusPath: Quickshell.env("WIDGET_STATUS_PATH"); width: implicitWidth; height: implicitHeight }
    Loader {
        id: widgetPanelLoader
        active: false
        sourceComponent: Component { PipelinesPanel { statusPath: Quickshell.env("WIDGET_STATUS_PATH") } }
    }
    FileView { id: widgetFile; path: Quickshell.env("WIDGET_STATUS_PATH"); blockLoading: true; printErrors: false }
    FileView { id: widgetWriter; path: Quickshell.env("WIDGET_STATUS_PATH"); atomicWrites: true; printErrors: false }
    FileView { id: toggleLog; path: Quickshell.env("TOGGLE_LOG"); blockLoading: true; printErrors: false }
''' if widget_available else ''
        (root / 'shell.qml').write_text('''
import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import qs.Commons as Commons
import "Polling.js" as Polling
import "PipelinesModel.js" as Model
''' + ('import "bar-widget" as BarPlugin\n' if widget_available else '') + '''
ShellRoot {
    PipelinesPanel { id: panel; statusPath: Quickshell.env("STATUS_PATH") }
''' + widget_objects + '''
    FileView {
        id: menuFile
        path: Quickshell.env("HOME") + "/.config/omarchy/extensions/omarchy-menu.jsonc"
        watchChanges: true
        blockLoading: true
        printErrors: false
        onFileChanged: reload()
    }
    Timer {
        interval: 180000; running: true
        onTriggered: { console.error("CHECK FAILED: timeout stage=" + stage + " ei=" + ei + " " + panel.status()); Qt.quit() }
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
    readonly property string actionRepo: "actions/" + "long-project-name-".repeat(5)
    property var actionSaved: null
    property var mrSaved: null
    property int actionBase: 0
    property double actionAt: 0
    FileView { id: actionLog; path: Quickshell.env("ACTION_LOG"); blockLoading: true; printErrors: false }
    FileView { id: hostLog; path: Quickshell.env("HOST_LOG"); blockLoading: true; printErrors: false }
    FileView { id: multiStatus; path: Quickshell.env("STATUS_PATH"); blockLoading: true; printErrors: false }
    function hostLines() { hostLog.reload(); var t=hostLog.text().trim(); return t ? t.split("\\n") : [] }
    function actionLines() {
        actionLog.reload()
        var t=actionLog.text().trim()
        return t ? t.split("\\n").map(function(line) { return JSON.parse(line) }) : []
    }
    function actionReply(ok, type, message, delay, extra) {
        var reply={requestId:"@ID@",ok:ok,error:message || "",errorType:type || "",remaining:4000}
        if (extra) Object.assign(reply,extra)
        panel.actionCommand=["sh",Quickshell.env("ACTION_SCRIPT"),JSON.stringify(reply).replace('"@ID@"','@ID@'),String(delay || 0)]
    }
    function actionFixture() {
        var repo=actionRepo
        panel.filterText=""
        panel.polling.repos=[{repo:repo,checked:"x",summaryAt:Date.now(),runs:[
            {id:1,run_number:1,name:"Failed",status:"completed",conclusion:"failed",head_branch:"main",ref:"main",source:"push"},
            {id:2,run_number:2,name:"Running",status:"in_progress",conclusion:"running",head_branch:"main",ref:"main",source:"push"},
            {id:3,run_number:3,name:"MR",status:"completed",conclusion:"failed",head_branch:"main",ref:"main",source:"merge_request_event"},
            {id:4,run_number:4,name:"Good",status:"completed",conclusion:"success",head_branch:"main",ref:"main",source:"push"}]}]
        panel.polling.details[repo+":2"]={jobs:[
            {id:21,name:"Failed job",stage:"test",status:"completed",conclusion:"failed"},
            {id:22,name:"Running job",stage:"test",status:"in_progress",conclusion:"running"},
            {id:23,name:"Manual job",stage:"test",status:"completed",conclusion:"manual"},
            {id:24,name:"Good job",stage:"test",status:"completed",conclusion:"success"}]}
        panel.expanded=({})
        panel.expanded["repo:"+repo]=true
        panel.expanded[repo+":2"]=true
        panel.expanded[repo+":2:stage:test"]=true
        panel.polling.cooldown=0
        panel.polling.lastStarted=0
        panel.polling.writeAt=0
        panel.adopt()
        listFocus()
    }
    function actionPress(row,key) { cursorTo(row); listFocus(); pressKey(key) }
    function actionSent(label) { return waitUntil(function() { return actionLines().length>actionBase && !panel.actionBusy },label) }
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
            // Actions use a separate fake process and a frozen polling fixture.
            actionSaved={polling:panel.polling,expanded:panel.expanded,filter:panel.filterText,
                workerBusy:panel.workerBusy,host:panel.host,command:panel.actionCommand}
            panel.polling=Polling.create()
            panel.polling.discover=false
            panel.polling.catalogueComplete=true
            panel.polling.catalogueAt=Date.now()
            panel.workerBusy=true
            resetZoom()
            cfg("gitlab.example.org")
            actionFixture()
            actionReply(true,"","",0)
            actionBase=actionLines().length
            ;[Qt.Key_A,Qt.Key_C,Qt.Key_X,Qt.Key_N].forEach(function(key) {
                actionPress(actionRepo+":1",key)
                eq(panel.notice,'Actions are off: set "actions": true for this plugin in shell.json',"A off key")
                check(!panel.confirm,"A off leaves no confirmation")
            })
            eq(actionLines().length,actionBase,"A off sent nothing")
            cfg("gitlab.example.org",{actions:true})
            check(panel.status().indexOf('"actionsOn":true')>=0,"A setting enabled")
            check(panel.listHint.indexOf("a/c/x/n act")>=0,"A hint advertises actions")
        },
        function() {
            // Each action key is accepted on its raw status and refused on another.
            var yes=[[actionRepo+":1",Qt.Key_A,"retry-pipeline"],[actionRepo+":2",Qt.Key_C,"cancel-pipeline"],
                [actionRepo+":2:21",Qt.Key_A,"retry-job"],[actionRepo+":2:22",Qt.Key_C,"cancel-job"],
                [actionRepo+":2:23",Qt.Key_X,"play-job"],[actionRepo+":2",Qt.Key_N,"new-pipeline"]]
            yes.forEach(function(c) {
                actionPress(c[0],c[1])
                check(panel.confirm && panel.confirm.action===c[2],"A allowed " + c[2])
                eq(panel.footerHint,panel.confirm.text,"A footer confirms " + c[2])
                pressKey(Qt.Key_Escape)
                check(!panel.confirm && panel.notice==="Nothing was sent","A Esc cancels")
            })
            var no=[[actionRepo+":4",Qt.Key_A,"Only a failed or canceled pipeline can be retried"],
                [actionRepo+":1",Qt.Key_C,"Only a running or queued pipeline can be canceled"],
                [actionRepo+":2:24",Qt.Key_A,"Only a failed or canceled job can be retried"],
                [actionRepo+":2:23",Qt.Key_C,"Only a running or queued job can be canceled"],
                [actionRepo+":2:24",Qt.Key_X,"Only a manual job can be played"],
                [actionRepo+":3",Qt.Key_N,"Merge-request pipelines cannot be started from the panel"]]
            no.forEach(function(c) { actionPress(c[0],c[1]); eq(panel.notice,c[2],"A refused key"); check(!panel.confirm,"A refusal has no confirmation") })
            ;[Qt.Key_A,Qt.Key_C,Qt.Key_X,Qt.Key_N].forEach(function(key) {
                actionPress("repo:"+actionRepo,key)
                eq(panel.notice,"Select a pipeline or job","A repo row refused")
            })
            eq(actionLines().length,actionBase,"A notices sent nothing")
        },
        function() {
            actionPress(actionRepo+":1",Qt.Key_A)
            check(panel.confirm && panel.footerHint===panel.confirm.text,"A footer shows whole confirmation")
            var cursor=panel.cursor
            pressKey(Qt.Key_Slash); check(!panel.searchItem.activeFocus && panel.cursor===cursor,"A slash swallowed")
            pressKey(Qt.Key_Return); check(panel.confirm,"A Enter cannot confirm")
            pressKey(Qt.Key_Y,Qt.ShiftModifier); check(panel.confirm,"A Shift+y cannot confirm")
            // With the search box focused, Esc still cancels the confirmation and y types nothing.
            panel.searchItem.forceActiveFocus()
            pressKey(Qt.Key_Escape)
            check(!panel.confirm && panel.notice==="Nothing was sent" && panel.filterText==="","A Esc in search cancels")
            listFocus()
            actionPress(actionRepo+":1",Qt.Key_A)
            var repeated={key:Qt.Key_Y,modifiers:Qt.NoModifier,isAutoRepeat:true,accepted:false}
            panel.confirmKey(repeated); check(repeated.accepted && panel.confirm,"A auto-repeat y swallowed")
            panel.confirmKey({key:Qt.Key_Y,modifiers:Qt.NoModifier,isAutoRepeat:false,accepted:false})
            check(!panel.confirm && panel.actionBusy,"A plain y sends")
        },
        function() {
            if (!actionSent("A first write")) return false
            eq(actionLines().length,actionBase+1,"A repeated y sent once")
            eq(actionLines()[actionBase].action,"retry-pipeline","A retry request")
            check(panel.notice.indexOf("Retry requested:")===0,"A success text")
            check(panel.polling.tasks["run:"+actionRepo+":1"],"A success touches run lookup")
            actionBase=actionLines().length
            actionPress(actionRepo+":1",Qt.Key_A)
            // Reordering the visible rows must not change the captured target.
            panel.polling.repos[0].runs.reverse()
            panel.adopt()
            pressKey(Qt.Key_Y)
        },
        function() {
            if (!actionSent("A reordered write")) return false
            var sent=actionLines()[actionBase]
            eq(sent.repo,actionRepo,"A target repo pinned")
            eq(sent.run,"1","A target run pinned")
            actionBase=actionLines().length
            actionPress(actionRepo+":2",Qt.Key_C)
            actionAt=Date.now()
            pressKey(Qt.Key_Y)
            check(panel.pendingAction && panel.actionBusy,"A second write waits")
            eq(actionLines().length,actionBase,"A spacing has no early write")
            var before=panel.polling.requests
            panel.workerBusy=false; panel.pump(); panel.workerBusy=true
            eq(panel.polling.requests,before,"A read waits behind write")
        },
        function() {
            if (!actionSent("A spaced write")) return false
            check(Date.now()-actionAt>=750,"A writes spaced by about one second")
            eq(actionLines().length,actionBase+1,"A second write sent")
            actionBase=actionLines().length
            panel.polling.cooldown=Date.now()+60000
            actionPress(actionRepo+":1",Qt.Key_A)
            check(panel.notice.indexOf("GitLab paused until ")===0 && !panel.confirm,"A cooldown refuses")
            eq(actionLines().length,actionBase,"A cooldown sent nothing")
            panel.polling.cooldown=0
        },
        function() {
            panel.polling.lastStarted=Date.now()
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
            check(panel.pendingAction && !panel.confirm,"A close-before-send is waiting")
            panel.close()
            check(!panel.pendingAction,"A close drops pending write")
            actionAt=Date.now()
        },
        function() {
            if (Date.now()-actionAt<1200) return false
            eq(actionLines().length,actionBase,"A close during wait sent nothing")
            panel.open("{}")
            panel.polling.lastStarted=Date.now()
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
            check(panel.pendingAction && !panel.confirm,"A host-before-send is waiting")
            cfg("gitlab.other.org",{actions:true})
            check(!panel.pendingAction && !panel.actionBusy,"A host change drops wait")
            eq(actionLines().length,actionBase,"A host-before-send sent nothing")
            cfg("gitlab.example.org",{actions:true})
            actionFixture()
            actionReply(true,"","",1.2)
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return actionLines().length===actionBase+1 && panel.actionBusy },"A slow write started")) return false
            cfg("gitlab.other.org",{actions:true})
            panel.polling.discover=false; panel.polling.catalogueComplete=true
            panel.workerBusy=true
            actionAt=panel.polling.requests
        },
        function() {
            if (!waitUntil(function() { return !panel.actionBusy },"A old-host result")) return false
            check(panel.notice.indexOf("on gitlab.example.org: Retry requested:")===0,"A old-host result labelled")
            eq(panel.polling.requests,actionAt,"A other-host polling untouched")
            eq(Object.keys(panel.polling.tasks).length,0,"A other-host tasks untouched")
            actionBase=actionLines().length
            cfg("gitlab.example.org",{actions:true})
            actionFixture()
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return actionLines().length===actionBase+1 && panel.actionBusy },"A second slow write started")) return false
            cfg("gitlab.other.org",{actions:true})
            cfg("gitlab.example.org",{actions:true})
            panel.workerBusy=true
        },
        function() {
            if (!waitUntil(function() { return !panel.actionBusy },"A roundtrip host result")) return false
            check(panel.notice.indexOf("on gitlab.example.org: Retry requested:")===0,"A epoch labels A-B-A result")
            eq(Object.keys(panel.polling.tasks).length,0,"A roundtrip leaves new polling untouched")
            actionBase=actionLines().length
            actionFixture()
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return actionLines().length===actionBase+1 && panel.actionBusy },"A close-running started")) return false
            panel.close()
            check(panel.actionBusy,"A close keeps process running")
        },
        function() {
            if (!waitUntil(function() { return !panel.actionBusy && panel.missedAction!=="" },"A closed result")) return false
            panel.open("{}")
            check(panel.notice.indexOf("Retry requested:")===0,"A missed result shown on reopen")
            eq(panel.missedAction,"","A missed result consumed")
            actionAt=Date.now()
        },
        function() {
            if (Date.now()-actionAt<9000) return false
            check(panel.notice.indexOf("Retry requested:")===0,"A missed result lasts nearly 10 s")
        },
        function() {
            if (Date.now()-actionAt<10500) return false
            eq(panel.notice,"","A missed result expires after 10 s")
            actionBase=actionLines().length
            actionFixture()
            actionPress(actionRepo+":1",Qt.Key_A)
            pressKey(Qt.Key_Y)
        },
        function() {
            if (!waitUntil(function() { return actionLines().length===actionBase+1 && panel.actionBusy },"A setting-off write started")) return false
            cfg("gitlab.example.org",{actions:false})
            check(panel.actionBusy,"A setting off keeps process running")
        },
        function() {
            if (!waitUntil(function() { return !panel.actionBusy },"A setting-off result")) return false
            check(panel.notice.indexOf("Retry requested:")===0,"A setting-off result still arrives")
            cfg("gitlab.example.org",{actions:true})
            actionFixture()
            actionReply(false,"scope","Needs a token with the api scope",0)
            actionBase=actionLines().length
            actionPress(actionRepo+":1",Qt.Key_A); pressKey(Qt.Key_Y)
        },
        function() {
            if (!actionSent("A scope result")) return false
            eq(panel.notice,"Needs a token with the api scope","A scope text")
            check(panel.actionFailed,"A scope is urgent")
            actionReply(false,"refused","GitLab refused: denied",0)
            actionBase=actionLines().length
            actionPress(actionRepo+":1",Qt.Key_A); pressKey(Qt.Key_Y)
        },
        function() {
            if (!actionSent("A refused result")) return false
            eq(panel.notice,"GitLab refused: denied","A refused text")
            actionReply(false,"unknown","Outcome unknown; check GitLab before retrying",0)
            actionBase=actionLines().length
            actionPress(actionRepo+":1",Qt.Key_A); pressKey(Qt.Key_Y)
        },
        function() {
            if (!actionSent("A unknown result")) return false
            eq(panel.notice,"Outcome unknown; check GitLab before retrying","A unknown text")
            // Long project names wrap at both compact zoom and a narrow card width.
            panel.zoomPercent=75
            actionPress(actionRepo+":1",Qt.Key_A)
            check(panel.confirm && panel.footerHint===panel.confirm.text,"A long confirmation present")
        },
        function() {
            var h=panel.hintItem
            check(h.text===panel.confirm.text && h.wrapMode===Text.Wrap,"A 75% text wraps")
            check(h.contentWidth<=h.width+1,"A 75% text fits its width")
            panel.cardItem.width=Commons.Style.space(300)
        },
        function() {
            var h=panel.hintItem
            check(h.text===panel.confirm.text && h.lineCount>1,"A narrow text wraps onto several lines")
            check(h.contentWidth<=h.width+1,"A narrow text fits its width")
            var bottom=h.mapToItem(panel.cardItem,0,h.height).y
            check(bottom<=panel.cardItem.height+1,"A narrow footer stays inside the card: " + bottom + " vs " + panel.cardItem.height)
            panel.cardItem.width=Qt.binding(function() { return Math.min(panel.zs(Commons.Style.space(900)), screenW()-Commons.Style.gapsOut*2) })
            pressKey(Qt.Key_Escape)
            panel.zoomPercent=100
            cfg(actionSaved.host)
            panel.polling=actionSaved.polling
            panel.expanded=actionSaved.expanded
            panel.filterText=actionSaved.filter
            panel.workerBusy=actionSaved.workerBusy
            panel.actionCommand=actionSaved.command
            panel.adopt()
            listFocus()
            check(!panel.actionsOn && !panel.confirm && !panel.actionBusy,"A setting and fixture restored")
        },
        function() {
            if (!panel.searchItem.parent.parent.activeFocus) return false
            resetZoom()
            check(panel.polling.requests===zRequests,"the zoom stages made no requests")
            stage=13
        }
    ]
    property int mi: 0
    property double mrWaitAt: 0
    property var mrsteps: [
        // The action stages restore a saved workerBusy that can be stale; let any real helper call end, then clear it.
        function() { if (!mrWaitAt) mrWaitAt=Date.now(); if (Date.now()-mrWaitAt<2000) return false; panel.workerBusy=false },
        function() {
            mrSaved={polling:panel.polling,expanded:panel.expanded,filter:panel.filterText,
                     collapsed:panel.searchCollapsed,key:panel.current && panel.current.key,viewState:panel.viewState}
            var s=Polling.create(), now=Date.now()
            s.opened=true; s.discover=false; s.catalogueComplete=true; s.catalogueAt=now
            s.repos=[{id:1,repo:"one/sub/repo",checked:"x",activityAt:now,summaryAt:now,
                      runs:[{id:7,name:"CI",status:"in_progress",conclusion:"running",run_number:1}]},
                     {id:2,repo:"two/repo",checked:"x",activityAt:now,summaryAt:now,runs:[]}]
            panel.polling=s
            panel.expanded=({})
            panel.filterText="repo"
            panel.adopt()
            listFocus()
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.parent.parent.activeFocus },"MR1 list focus")) return false
            cursorTo("repo:one/sub/repo")
            pressKey(Qt.Key_Right)
            pressKey(Qt.Key_Left)
            check(panel.searchCollapsed["repo:one/sub/repo"],"MR1 project collapsed during search")
            cursorTo("repo:two/repo"); panel.selectionChanged(false)
            panel.confirm={text:"Confirm action"}
            pressKey(Qt.Key_M)
            eq(panel.view,"projects","MR2 m cannot switch during confirmation")
            pressKey(Qt.Key_Escape)
            pressKey(Qt.Key_M)
            eq(panel.view,"mrs","MR1 m switches to merge requests")
            eq(JSON.parse(panel.status()).view,"mrs","MR1 status reports view")
        },
        function() {
            if (!waitUntil(function() { return panel.polling.mrs.list && panel.polling.mrs.status["1!1"] && panel.polling.mrs.status["99!2"] },"MR list and details")) return false
            check(has("mr:1!1") && has("mr:99!2"),"MR1 both rows shown")
            check(textStarts(panel.cardItem,"My merge requests"),"MR3 header")
            eq(JSON.parse(panel.status()).mrs,2,"MR3 status count")
            listFocus(); pressKey(Qt.Key_Slash); typeText("m")
            eq(panel.view,"mrs","MR2 m in search stays in view")
            eq(panel.filterText,"m","MR2 m in search is text")
            pressKey(Qt.Key_Escape)
            listFocus(); pressKey(Qt.Key_Slash); typeText("zzzz")
            check(panel.entries.length===0 && panel.emptyItem.text.indexOf("No merge requests match")===0,"MR3 no-match text")
            pressKey(Qt.Key_Escape)
        },
        function() {
            listFocus(); cursorTo("mr:1!1")
            pressKey(Qt.Key_P)
            eq(panel.notice,"Not on a merge request; press Enter for its pipeline","MR5 p refusal")
            pressKey(Qt.Key_A)
            eq(panel.notice,"Not on a merge request; press Enter for its pipeline","MR5 a refusal")
            tc.keyClick("?"); check(panel.helpOpen,"MR2 help opens")
            pressKey(Qt.Key_M); eq(panel.view,"mrs","MR2 m cannot switch with help open")
            pressKey(Qt.Key_Escape); check(!panel.helpOpen,"MR2 help closes")
            pressKey(Qt.Key_M)
            eq(panel.view,"projects","MR1 m switches back")
            eq(panel.filterText,"repo","MR1 project filter restored")
            eq(panel.current.key,"repo:two/repo","MR1 project cursor restored")
            check(panel.searchCollapsed["repo:one/sub/repo"],"MR1 search collapse restored")
            check(textStarts(panel.cardItem,"GitLab Pipelines"),"MR3 projects header")
        },
        function() {
            listFocus(); pressKey(Qt.Key_M)
            eq(panel.view,"mrs","MR4 return to merge requests")
            cursorTo("mr:1!1"); panel.selectionChanged(false)
            pressKey(Qt.Key_Return)
            eq(panel.view,"projects","MR4 Enter jumps to projects")
            eq(panel.current.key,"one/sub/repo:7","MR4 pipeline selected")
            var at=panel.entries.findIndex(function(row) { return row.key==="one/sub/repo:7" })
            panel.listItem.forceLayout()
            var item=panel.listItem.itemAtIndex(at)
            check(item && item.y>=panel.listItem.contentY-1 && item.y+item.height<=panel.listItem.contentY+panel.listItem.height+1,"MR4 pipeline visible")
        },
        function() {
            listFocus(); pressKey(Qt.Key_M)
            cursorTo("mr:99!2"); panel.selectionChanged(false)
            pressKey(Qt.Key_Return)
            eq(panel.view,"mrs","MR4 outside project stays in merge requests")
            eq(panel.notice,"Project not in your list; o opens the merge request","MR4 outside project refusal")
            panel.close(); panel.open("{}")
            eq(panel.view,"mrs","MR6 close and reopen keeps view")
            panel.close(); panel.open('{"filter":"one/sub/repo"}')
            eq(panel.view,"projects","MR8 an explicit project filter opens the projects view")
            eq(panel.filterText,"one/sub/repo","MR8 the requested filter applies to projects")
            panel.toggleView()
            eq(panel.view,"mrs","MR8 m returns to merge requests")
            sh('touch "$MR_DELAY"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running && !panel.workerBusy },"MR7 delayed helper ready")) return false
            listFocus(); pressKey(Qt.Key_R)
        },
        function() {
            if (!waitUntil(function() { return panel.workerBusy && panel.requestInfo.kind==="mr" },"MR7 detail in flight")) return false
            var before=panel.polling.generation
            cfg("gitlab.other.org",{projects:["three/repo"]})
            check(panel.polling.generation>before,"MR7 host generation changes")
            eq(panel.view,"mrs","MR7 host change keeps view")
            check(!has("mr:1!1") && !has("mr:99!2"),"MR7 old rows disappear")
        },
        function() {
            if (!waitUntil(function() { return !panel.workerBusy && panel.polling.mrs.list!==null },"MR7 new host list")) return false
            eq(panel.polling.mrs.list.length,0,"MR7 other host list loads empty")
            check(!has("mr:1!1") && !has("mr:99!2"),"MR7 old reply ignored")
            eq(panel.view,"mrs","MR7 view remains")
            sh('rm -f "$MR_DELAY"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running },"MR fixture cleanup")) return false
            cfg("gitlab.example.org")
            panel.polling=mrSaved.polling
            panel.expanded=mrSaved.expanded
            panel.viewState=mrSaved.viewState
            panel.switchView("projects",mrSaved.filter,mrSaved.key)
            panel.searchCollapsed=mrSaved.collapsed
            panel.adopt(mrSaved.key)
            eq(panel.view,"projects","MR restore view")
            eq(panel.filterText,mrSaved.filter,"MR restore filter")
            listFocus()
            if (widgetAvailable) stage=14
            else { console.log("SKIP widget: no bar-widget directory"); stage=15 }
        },
        function() {
            if (!panel.searchItem.parent.parent.activeFocus) return false
            stage=15
        }
    ]
    readonly property string firstHost: "gitlab.example.org"
    readonly property string secondHost: "gitlab.other.org"
    property int mhi: 0
    property var mh: ({})
    function multiCfg(names) {
        panel.configure(JSON.stringify({plugins:[{id:"olafkfreund.gitlab-pipelines",hosts:names.map(function(h) {
            return {host:h,actions:true,projects:["one/sub/repo","two/repo"]}
        })}]}))
    }
    function multiPoller(h) { return panel.pollerFor(h).state }
    function multiRun() { return {id:7,name:"CI",status:"in_progress",conclusion:"running",run_number:1,head_branch:"main",ref:"main",source:"push"} }
    property var mhsteps: [
        function() {
            if (!mh.setupAt) mh.setupAt=Date.now()
            if (panel.workerBusy && Date.now()-mh.setupAt<2000) return false
            panel.close()
            panel.workerBusy=true
            sh('touch "$MULTI"; : > "$HOST_LOG"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running },"multihost flags")) return false
            panel.polling=Polling.create()
            multiCfg([firstHost])
            panel.polling.repos=[{id:1,repo:"one/sub/repo",checked:"x",runs:[multiRun()]},{id:2,repo:"two/repo",checked:"x",runs:[]}]
            panel.expanded=({"repo:one/sub/repo":true})
            panel.adopt()
            var old=panel.polling
            multiCfg([firstHost,secondHost])
            check(panel.polling.repos===old.repos && panel.more.length===1,"M 1 to 2 keeps host data")
            eq(Object.keys(panel.expanded).length,0,"M host-count change clears expansion")
            check(has("repo:"+firstHost+"|one/sub/repo") && has("repo:"+secondHost+"|one/sub/repo"),"M duplicate project paths have distinct rows")
            eq(panel.entries.filter(function(r) { return r.key==="repo:"+firstHost+"|one/sub/repo" })[0].hostLabel,firstHost,"M first host label")
            eq(panel.entries.filter(function(r) { return r.key==="repo:"+secondHost+"|one/sub/repo" })[0].hostLabel,secondHost,"M second host label")
            panel.open("{}")
            cursorTo("repo:"+secondHost+"|one/sub/repo"); panel.selectionChanged(true)
            Polling.manual(multiPoller(secondHost),Date.now(),false)
            panel.workerBusy=false; panel.pump()
        },
        function() {
            if (!waitUntil(function() { var r=multiPoller(secondHost).repos.filter(function(x) { return x.repo==="one/sub/repo" })[0]; return r && r.runs && r.runs.length && !panel.workerBusy },"M second host pipeline")) return false
            if (!waitUntil(function() { return hostLines().indexOf(secondHost)>=0 },"M helper read second host")) return false
            cursorTo("repo:"+secondHost+"|one/sub/repo"); panel.expand(false)
            cursorTo(secondHost+"|one/sub/repo:7"); panel.expand(false)
            panel.expanded[secondHost+"|one/sub/repo:7:stage:build"]=true
            panel.rebuild()
            panel.selectionChanged(true); panel.pump()
        },
        function() {
            if (!waitUntil(function() { var d=multiPoller(secondHost).details["one/sub/repo:7"]; return d && d.jobs && d.jobs.length && !panel.workerBusy },"M second host jobs")) return false
            check(has(secondHost+"|one/sub/repo:7:8"),"M second host job row")
            var row=panel.entries.filter(function(r) { return r.key===secondHost+"|one/sub/repo:7:8" })[0]
            check(Model.accessibleName(row).indexOf("on "+secondHost)>=0,"M job accessible name includes host")
            panel.workerBusy=true
            multiPoller(firstHost).details["one/sub/repo:7"]={jobs:[{id:8,name:"compile",stage:"build",status:"completed",conclusion:"success"}]}
            multiPoller(secondHost).details["one/sub/repo:7"]={jobs:[{id:8,name:"compile",stage:"build",status:"completed",conclusion:"failed"}]}
            panel.adopt()
            cursorTo(secondHost+"|one/sub/repo:7:8")
            panel.startAction("a")
            check(panel.confirm && panel.confirm.action==="retry-job" && panel.confirm.host===secondHost,"M job action uses second host raw job")
            actionReply(true,"","",0)
            mh.actionBase=actionLines().length
            panel.confirmAction()
        },
        function() {
            if (!waitUntil(function() { return actionLines().length>mh.actionBase && !panel.actionBusy },"M second host action")) return false
            eq(actionLines()[mh.actionBase].host,secondHost,"M action request names second host")
            check(panel.notice.indexOf("on "+secondHost)>=0,"M action result names second host")
            if (!waitUntil(function() { return panel.pinState[secondHost] && panel.pinState[secondHost].loaded },"M second host pins loaded")) return false
            cursorTo("repo:"+secondHost+"|two/repo"); panel.togglePin()
            check(panel.pinned[secondHost+"|two/repo"] && !panel.pinned[firstHost+"|two/repo"],"M pin belongs only to second host")
            multiPoller(secondHost).repos.filter(function(r) { return r.repo==="one/sub/repo" })[0].id=1
            panel.workerBusy=true
            panel.switchView("mrs")
            panel.pollers().forEach(function(p) { p.state.mrs.list=null })
            panel.adopt()
            eq(panel.emptyItem.text,"Loading merge requests…","M MR list waits for every host")
            panel.pollers().forEach(function(p) { p.state.mrs.list=[] })
            multiPoller(firstHost).error="temporary"
            panel.adopt()
            panel.repos=[]
            eq(panel.emptyItem.text,"No open merge requests","M MR empty label stays visible beside host error")
            multiPoller(firstHost).error=""
            panel.adopt()
            panel.workerBusy=false; panel.pump()
        },
        function() {
            if (!waitUntil(function() { return has("mr:"+secondHost+"|1!1") && has("mr:"+firstHost+"|1!1") && !panel.workerBusy },"M both hosts' MR lists")) return false
            cursorTo("mr:"+secondHost+"|1!1"); panel.selectionChanged(true); panel.pump()
        },
        function() {
            if (!waitUntil(function() { return multiPoller(secondHost).mrs.status["1!1"] && !panel.workerBusy },"M second host MR pipeline")) return false
            panel.jumpMr()
            eq(panel.view,"projects","M MR jump changes view")
            eq(panel.current.key,secondHost+"|one/sub/repo:7","M MR jump selects second host pipeline")
            eq(panel.openHost,"","M MR jump clears host filter")
            sh('touch "$OTHER_AUTH"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running && !panel.workerBusy },"M auth flag ready")) return false
            var s=multiPoller(secondHost)
            s.auth=false; s.error=""
            Polling.manual(s,Date.now(),false)
            panel.pump()
        },
        function() {
            if (!waitUntil(function() { return multiPoller(secondHost).auth && !panel.workerBusy },"M second host auth error")) return false
            check(panel.errorItem.text.indexOf(secondHost+":")>=0,"M strip names stopped host")
            check(!multiPoller(firstHost).auth,"M first host remains usable")
            mh.firstRequests=multiPoller(firstHost).requests
            sh('rm -f "$OTHER_AUTH"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running && !panel.workerBusy },"M auth flag cleared")) return false
            Polling.manual(multiPoller(firstHost),Date.now(),true)
            panel.pump()
        },
        function() {
            if (!waitUntil(function() { return multiPoller(firstHost).requests>mh.firstRequests && !panel.workerBusy },"M first host keeps polling")) return false
            check(multiPoller(secondHost).auth,"M second host stays stopped")
            sh('touch "$OTHER_DELAY"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running && !panel.workerBusy },"M delay flag ready")) return false
            var s=multiPoller(secondHost)
            s.auth=false; s.error=""
            Polling.manual(s,Date.now(),false)
            panel.pump()
        },
        function() {
            if (!waitUntil(function() { return panel.workerBusy && panel.requestInfo.host===secondHost },"M delayed second host read")) return false
            mh.oldLife=panel.pollerFor(secondHost).life
            multiCfg([firstHost])
            sh('rm -f "$OTHER_DELAY"')
            multiCfg([firstHost,secondHost])
            check(panel.pollerFor(secondHost).life!==mh.oldLife,"M readded host has a new life")
        },
        function() {
            if (!waitUntil(function() { return !shp.running && !panel.workerBusy },"M delayed reply finishes")) return false
            check(JSON.stringify(multiPoller(secondHost).repos).indexOf("LATE")<0,"M old reply did not reach readded host")
            panel.workerBusy=true
            multiCfg([firstHost])
            panel.switchView("mrs")
            multiCfg([firstHost,secondHost])
            panel.workerBusy=false; panel.pump()
        },
        function() {
            if (!waitUntil(function() { return multiPoller(secondHost).mrs.list && has("mr:"+secondHost+"|1!1") && !panel.workerBusy },"M added host loads MRs while open")) return false
            mh.secondLife=panel.pollerFor(secondHost).life
            multiCfg([secondHost])
            check(panel.host===secondHost && panel.hostLife===mh.secondLife,"M removing first host moves second host state and life")
            check(has("mr:1!1"),"M remaining host keeps MR rows")
            panel.switchView("projects")
            check(panel.entries.some(function(r) { return r.host===secondHost }),"M remaining host keeps project rows")
        },
        function() {
            if (!waitUntil(function() { return !panel.workerBusy },"M watch setup idle")) return false
            panel.workerBusy=true
            multiCfg([firstHost,secondHost])
            var s=multiPoller(secondHost), r=s.repos.filter(function(x) { return x.repo==="one/sub/repo" })[0]
            check(r,"M second host project exists for watch")
            r.runs=[multiRun()]
            panel.expanded=({})
            panel.expanded["repo:"+secondHost+"|one/sub/repo"]=true
            panel.adopt()
            cursorTo(secondHost+"|one/sub/repo:7"); panel.toggleWatch()
            check(!!s.watches["one/sub/repo:7"] && panel.watching,"M only second host watches")
            mh.watchRequests=s.requests
            mh.hostReads=hostLines().length
            s.watches["one/sub/repo:7"].checkedAt=0
            panel.close(); panel.workerBusy=false
        },
        function() {
            if (!waitUntil(function() { return multiPoller(secondHost).requests>mh.watchRequests && hostLines().length>mh.hostReads },"M second host watch polls while closed")) return false
            eq(hostLines()[hostLines().length-1],secondHost,"M closed watch used second host helper")
            if (!waitUntil(function() { return !panel.workerBusy },"M closed watch reply")) return false
            panel.workerBusy=true; panel.open("{}")
            var s=multiPoller(firstHost)
            s.repos=[{repo:"one/sub/repo",runs:[10,11,12,13].map(function(id) { return {id:id,status:"in_progress",conclusion:"running",run_number:id} })}]
            ;[10,11,12,13].forEach(function(id) { eq(Polling.watch(s,"one/sub/repo",String(id),Date.now()),"watching","M cap fixture watch") })
            panel.adopt()
            cursorTo(secondHost+"|one/sub/repo:7"); panel.toggleWatch()
            check(!multiPoller(secondHost).watches["one/sub/repo:7"],"M unwatch succeeds at five-watch cap")
            s.watches=({}); panel.adopt()
        },
        function() {
            panel.open(JSON.stringify({filter:"one/sub/repo",host:firstHost}))
            eq(panel.openHost,firstHost,"M first open selects first host")
            check(panel.entries.length>0 && panel.entries.every(function(r) { return r.host===firstHost }),"M first open filters rows by host")
            panel.open("{}")
            eq(panel.openHost,firstHost,"M toggle open keeps host filter")
            panel.open(JSON.stringify({filter:"one/sub/repo",host:"absent.test"}))
            eq(panel.openHost,"","M unmatched open clears host filter")
            check(panel.entries.some(function(r) { return r.host===secondHost }),"M unmatched open rebuilds rows")
            panel.open(JSON.stringify({filter:"one/sub/repo",host:secondHost}))
            eq(panel.openHost,secondHost,"M same text selects second host")
            check(panel.entries.length>0 && panel.entries.every(function(r) { return r.host===secondHost }),"M second open rebuilds rows")
            panel.filterText=""
            panel.now=Date.now()
            var a=multiPoller(firstHost), b=multiPoller(secondHost)
            a.auth=false; a.error=""; a.catalogueError=""; a.countsAt=Date.now()
            b.auth=false; b.error=""; b.catalogueError=""; b.countsAt=a.countsAt
            a.repos=[{repo:"one/sub/repo",checked:"x",active:2,runs:[{id:7,status:"completed",conclusion:"failed"}]}]
            b.repos=[{repo:"one/sub/repo",checked:"x",active:3,runs:[{id:7,status:"completed",conclusion:"success"}]}]
            panel.adopt()
        },
        function() {
            var file
            if (!waitUntil(function() { multiStatus.reload(); try { file=JSON.parse(multiStatus.text()) } catch (e) { return false }; return file && file.hosts && file.running===5 },"M status file totals")) return false
            eq(file.hosts.length,2,"M status file has both hosts")
            eq(file.failed,1,"M status file sums failures")
            eq(file.host,firstHost+" +1","M status file labels hosts")
            var status=JSON.parse(panel.status())
            eq(status.hosts.length,2,"M status reports hosts")
            eq(status.requests,status.hosts[0].requests+status.hosts[1].requests,"M status sums requests")
            eq(status.mrs,status.hosts[0].mrs+status.hosts[1].mrs,"M status sums MRs")
            panel.workerBusy=true
            panel.open(JSON.stringify({filter:"one/sub/repo",host:secondHost}))
            panel.viewState.projects.openHost=secondHost
            multiCfg([firstHost,"third.test"])
            eq(panel.openHost,"","M removed host clears active filter")
            eq(panel.viewState.projects.openHost,"","M removed host clears saved filter")
            check(panel.entries.some(function(r) { return r.host===firstHost }),"M removed host filter rebuilds rows")
            panel.workerBusy=false
            sh('rm -f "$MULTI" "$OTHER_AUTH" "$OTHER_DELAY"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running },"M flags cleaned")) return false
            console.log("QML_CHECKS_PASSED")
            Qt.quit()
        }
    ]
    readonly property bool widgetAvailable: Quickshell.env("WIDGET_AVAILABLE")==="1"
    property int wi: 0
    property double widgetWaitAt: 0
    property double widgetCountsAt: 0
    property int widgetRequests: 0
    property double widgetWrittenAt: 0
    property string widgetLastStatus: ""
    function widgetStatus() {
        widgetFile.reload()
        try { return JSON.parse(widgetFile.text()) } catch (e) { return null }
    }
    function widgetButton(widget) {
        var button=widget.children[0]
        check(button && typeof button.triggerPress==="function" && typeof button.tooltipText==="string","widget child is WidgetButton")
        return button
    }
    function widgetPayload(state, countsAt, cooldownUntil) {
        return {version:1,instance:"fixture",host:"gitlab.example.org",state:state,
            running:2,failed:1,countsAt:countsAt,cooldownUntil:cooldownUntil || 0,reason:"",writtenAt:Date.now()}
    }
    property var widgetSteps: [
        function() {
            eq(widgetA.statusView.state,"none","widget starts without a file")
            eq(widgetB.statusView.state,"none","second widget starts without a file")
            eq(widgetButton(widgetA).text,"\\uF296","empty widget shows only the glyph")
            widgetPanelLoader.active=true
        },
        function() {
            var status=widgetStatus()
            if (!waitUntil(function() { return status && status.state==="none" && status.instance && widgetPanelLoader.item },"widget panel startup")) return false
            eq(widgetA.statusView.state,"none","startup status remains dimmed")
            eq(widgetPanelLoader.item.statusPath,Quickshell.env("WIDGET_STATUS_PATH"),"fixture panel uses isolated status path")
            var p=widgetPanelLoader.item
            p.workerBusy=true
            p.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.example.org"}]}')
            p.polling=Polling.create()
            widgetCountsAt=Date.now()
            p.polling.countsAt=widgetCountsAt
            p.polling.repos=[{repo:"widget/one",active:2,checked:"x",runs:[{id:7,status:"completed",conclusion:"failed"}]}]
            p.adopt()
            widgetRequests=p.polling.requests
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.state==="ok" && s.running===2 && widgetA.statusView.state==="ok" && widgetB.statusView.state==="ok" },"widget follows fixture")) return false
            var a=widgetButton(widgetA), b=widgetButton(widgetB)
            eq(a.text,"\\uF296 ●2 ✕1","horizontal label has both counts")
            eq(b.text,"\\uF296\\n●2\\n✕1","vertical label has the same counts")
            check(a.active && !a.dimmed && b.active,"failure uses urgent colour")
            check(a.tooltipText.indexOf("2 running pipelines, 1 failed project")>=0,"tooltip names both units")
            eq(a.Accessible.name,a.tooltipText.replace(/\\n/g,", "),"accessible name follows tooltip")
            a.children[a.children.length-1].entered()
            check(fakeBarA.lastTarget===a,"whole button is tooltip target")
            eq(fakeBarA.lastTooltip,a.tooltipText,"bar receives plain tooltip")
            eq(widgetPanelLoader.item.polling.requests,widgetRequests,"widgets issue no requests")
            widgetPanelLoader.item.polling.repos[0].active=3
            widgetPanelLoader.item.adopt()
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.running===3 && widgetA.statusView.label.indexOf("●3")>=0 },"first atomic update")) return false
            widgetPanelLoader.item.polling.repos[0].active=4
            widgetPanelLoader.item.adopt()
        },
        function() {
            var status=widgetStatus()
            if (!waitUntil(function() { return status && status.running===4 && widgetB.statusView.label.indexOf("●4")>=0 && widgetPanelLoader.item.lastStatus===widgetPanelLoader.item.pendingStatus },"second atomic update")) return false
            widgetWrittenAt=status.writtenAt
            widgetPanelLoader.item.adopt()
            widgetWaitAt=Date.now()
        },
        function() {
            if (Date.now()-widgetWaitAt<600) return false
            eq(widgetStatus().writtenAt,widgetWrittenAt,"unchanged status does not rewrite")
            var p=widgetPanelLoader.item
            p.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"bad host"}]}')
        },
        function() {
            if (!waitUntil(function() { return widgetStatus() && widgetStatus().state==="stopped" && widgetA.statusView.state==="stopped" },"configuration stop")) return false
            var p=widgetPanelLoader.item
            check(widgetButton(widgetA).active && widgetButton(widgetA).text.indexOf("!")>=0,"stopped widget is urgent")
            p.polling.repos[0].active=5
            p.adopt()
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.running===5 },"watch reply while stopped")) return false
            eq(widgetStatus().state,"stopped","watch reply retains configuration stop")
            widgetPanelLoader.item.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.example.org"}]}')
        },
        function() {
            if (!waitUntil(function() { return widgetStatus() && widgetStatus().state==="ok" && widgetA.statusView.state==="ok" },"valid configuration clears stop")) return false
            widgetPanelLoader.item.configure('{"plugins":[{"id":"olafkfreund.gitlab-pipelines","host":"gitlab.other.org"}]}')
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.host==="gitlab.other.org" && s.state==="none" && widgetA.statusView.state==="none" },"host reset publishes none")) return false
            var p=widgetPanelLoader.item, s=Polling.create(), now=Date.now()
            s.opened=false; s.discover=false; s.catalogueComplete=true; s.catalogueAt=now; s.countsAt=now
            s.repos=[{repo:"w/one",checked:"x",active:1,activeFromTotal:true,runs:[wRuns()[0]]}]
            p.polling=s; p.notifyCommand=["sh","-c","exit 0"]
            eq(Polling.watch(s,"w/one","11",now),"watching","closed watch starts")
            p.adopt()
            widgetCountsAt=p.polling.countsAt
            var request=Polling.next(p.polling,now+31000)
            check(request && request.kind==="run","closed watch requests run")
            var run=Object.assign({},wRuns()[0],{status:"completed",conclusion:"success"})
            p.receivePage(JSON.stringify({requestId:request.requestId,data:run,nextPage:0,error:"",errorType:"",remaining:4000}),request)
            eq(p.polling.countsAt,widgetCountsAt,"closed reply keeps project count time")
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.state==="ok" && s.countsAt===widgetCountsAt && s.running===0 && widgetA.statusView.state==="ok" && widgetA.statusView.label.indexOf("●")<0 },"closed watch publishes finish")) return false
            eq(widgetStatus().countsAt,widgetCountsAt,"closed run leaves project count time unchanged")
            widgetLastStatus=widgetPanelLoader.item.lastStatus
            sh('rm -f "$WIDGET_STATUS_PATH" && mkdir "$WIDGET_STATUS_PATH"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running },"make status path unwritable")) return false
            var p=widgetPanelLoader.item
            p.polling.repos[0].active=3
            p.adopt()
            widgetWaitAt=Date.now()
        },
        function() {
            var p=widgetPanelLoader.item
            if (Date.now()-widgetWaitAt<600) return false
            eq(p.lastStatus,widgetLastStatus,"failed save leaves last recorded status unchanged")
            sh('rmdir "$WIDGET_STATUS_PATH"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running },"make status path writable")) return false
            widgetPanelLoader.item.publishStatus()
        },
        function() {
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.running===3 && widgetA.statusView.label.indexOf("●3")>=0 },"retry after unwritable path")) return false
            widgetPanelLoader.active=false
        },
        function() {
            if (!waitUntil(function() { return !widgetPanelLoader.item },"widget panel destruction")) return false
            if (!waitUntil(function() { var s=widgetStatus(); return s && s.state==="none" },"panel destruction writes none")) return false
            widgetWriter.setText(JSON.stringify(widgetPayload("ok",Date.now(),0))+"\\n")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="ok" && widgetB.statusView.state==="ok" },"manual status file")) return false
            sh('rm -f "$WIDGET_STATUS_PATH"')
        },
        function() {
            if (!waitUntil(function() { return !shp.running && widgetA.statusView.state==="none" && widgetB.statusView.state==="none" },"deleted status file")) return false
            widgetWriter.setText(JSON.stringify(widgetPayload("ok",Date.now(),0))+"\\n")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="ok" && widgetB.statusView.state==="ok" },"status restored before empty write")) return false
            widgetWriter.setText("")
        },
        function() {
            if (!waitUntil(function() { widgetFile.reload(); return widgetFile.text()==="" && widgetA.statusView.state==="none" && widgetB.statusView.state==="none" },"empty status file")) return false
            widgetWriter.setText(JSON.stringify(widgetPayload("ok",Date.now(),0))+"\\n")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="ok" && widgetB.statusView.state==="ok" },"recreated status file")) return false
            widgetWriter.setText(JSON.stringify(widgetPayload("rate",Date.now(),Date.now()+2000))+"\\n")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="rate" && widgetB.statusView.state==="rate" },"rate status loads")) return false
            check(widgetButton(widgetA).dimmed && widgetButton(widgetA).tooltipText.indexOf("GitLab paused until ")===0,"rate view is dimmed")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="ok" && widgetB.statusView.state==="ok" },"rate expires to ok")) return false
            widgetWriter.setText(JSON.stringify(widgetPayload("rate",0,Date.now()+2000))+"\\n")
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="rate" && widgetB.statusView.state==="rate" },"rate without counts loads")) return false
        },
        function() {
            if (!waitUntil(function() { return widgetA.statusView.state==="none" && widgetB.statusView.state==="none" },"rate without counts expires to none")) return false
            var button=widgetButton(widgetA)
            button.triggerPress(Qt.RightButton)
            button.triggerPress(Qt.MiddleButton)
            toggleLog.reload()
            eq(toggleLog.text().trim(),"","other clicks do not toggle")
            button.triggerPress(Qt.LeftButton)
        },
        function() {
            if (!waitUntil(function() { toggleLog.reload(); return toggleLog.text().trim()!=="" },"left click toggle process")) return false
            eq(toggleLog.text().trim().split("\\n").length,1,"only one click toggles")
            eq(toggleLog.text().trim(),"shell toggle olafkfreund.gitlab-pipelines {}","toggle argument list")
            stage=13
        }
    ]
    property int ei: 0
    property var keyFixture: ({})
    property var live: ({})
    function rowItem(key) { return panel.listItem.itemAtIndex(panel.entries.findIndex(function(r) { return r.key===key })) }
    property double holdSince: 0
    function zRepos() { return Array.from({length:40},function(_, i) { return {repo:"z/p"+(i<10 ? "0" : "")+i,checked:"x",runs:[]} }) }
    function findByName(item, name) {
        if (item.objectName===name) return item
        for (var i=0;i<item.children.length;i++) { var f=findByName(item.children[i], name); if (f) return f }
        return null
    }
    function textStarts(item, prefix) {
        if (typeof item.text==="string" && item.text.indexOf(prefix)===0) return true
        for (var i=0;i<item.children.length;i++) if (textStarts(item.children[i],prefix)) return true
        return false
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
    function cfg(h, extra) { panel.configure(JSON.stringify({plugins:[Object.assign({id:"olafkfreund.gitlab-pipelines",host:h}, extra || {})]})) }
    function setPin(changes) {
        var next=Object.assign({},panel.pinState)
        next[panel.host]=Object.assign({},next[panel.host],changes)
        panel.pinState=next
    }
    property var startPins: null
    readonly property string stateDir: Quickshell.env("XDG_STATE_HOME") + "/omarchy-gitlab-pipelines"
    // Records the list the real start-up load read for gitlab.com, before the first test step changes host.
    Connections {
        target: panel
        function onPinStateChanged() {
            var pin=panel.pinState[panel.host]
            if (pin && pin.loaded && startPins===null && panel.host==="gitlab.com") startPins=pin.saved.slice()
        }
    }
    FileView { id: stateFile; path: stateDir + "/pinned.json"; blockLoading: true; printErrors: false }
    Process { id: shp }
    function sh(cmd) { shp.command=["sh","-c",cmd]; shp.running=true }
    // True when pinned.json holds exactly want (host -> list) for every host named in it.
    function stateIs(want) {
        stateFile.reload()
        try {
            var hosts=JSON.parse(stateFile.text()).hosts
            return Object.keys(want).every(function(h) { return JSON.stringify(hosts[h])===JSON.stringify(want[h]) })
        } catch (e) { return false }
    }
    function pinFixture() {
        panel.filterText=""
        panel.expanded=({})
        panel.polling.repos=[{repo:"o/alpha",checked:"x",runs:[],active:1},{repo:"o/beta",checked:"x",runs:[]},{repo:"o/gamma",checked:"x",runs:[]},{repo:"o/delta",checked:"x",runs:[]}]
        panel.adopt()
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
    // A fresh file per check: a FileView keeps its last text when a file it loaded is emptied or deleted.
    property int traceN: 0
    readonly property string traceOut: Quickshell.env("XDG_STATE_HOME") + "/trace" + traceN + ".out"
    FileView { id: traceFile; path: traceOut; blockLoading: true; printErrors: false }
    function traceScript() { return ["sh","-c",'for a in "$@"; do echo "$a"; done > "' + traceOut + '"; exit 0',"sh"] }
    function traceExists() { traceFile.reload(); try { return traceFile.text()!=="" } catch (e) { return false } }
    function traceRm() { traceN++; panel.traceCommand=traceScript() }
    function traceFixture() {
        kFixture([kP(1),kP(2)],[kJ(1),kJ(2)])
        panel.traceCommand=traceScript()
    }
    function rowOf(kind) { return panel.entries.findIndex(function(e) { return e.kind===kind }) }
    function tModStart(mod) {
        traceFixture()
        panel.cursor=rowOf("job")
        check(panel.current.kind==="job","T6 cursor on a job")
        traceRm()
        kt=Date.now()+300
    }
    function tModPress(mod) {
        if (Date.now()<kt) return false
        kt=0
        kPress(Qt.Key_T, mod)
        kt=Date.now()+1000
    }
    function tModEnd(label) {
        if (Date.now()<kt) return false
        kt=0
        check(panel.opened,"T6 " + label + " keeps the panel open")
        check(!traceExists(),"T6 " + label + " does not trace")
    }
    // W1-W10: watching a pipeline. A fresh notify file per check, as for the trace file above.
    property int notifyN: 0
    readonly property string notifyOut: Quickshell.env("XDG_STATE_HOME") + "/notify" + notifyN + ".out"
    FileView { id: notifyFile; path: notifyOut; blockLoading: true; printErrors: false }
    function notifyScript() { return ["sh","-c",'for a in "$@"; do echo "$a"; done >> "' + notifyOut + '"; exit 0',"sh"] }
    function notifyHas(text) { notifyFile.reload(); try { return notifyFile.text().indexOf(text)>=0 } catch (e) { return false } }
    function notifyIdle() { return !panel.notifyBusy && panel.notifyQueue.length===0 }
    function notifyRm() { notifyN++; panel.notifyCommand=notifyScript() }
    property double wNow: 0
    // Each closed lookup gets a clock 31 s later, so it is due and the one-second start gap holds.
    function wTick() { wNow=Math.max(Date.now(), wNow+31000); return wNow }
    function wRuns() {
        var u="https://gitlab.example.org/w/one/-/pipelines/"
        var live=[[11,5],[13,6],[14,7],[15,8],[16,9],[17,10]].map(function(p) {
            return {id:p[0],name:"Live",status:"in_progress",conclusion:"running",run_number:p[1],head_branch:"main",html_url:u+p[0]}
        })
        return live.concat([{id:12,name:"Done",status:"completed",conclusion:"success",run_number:4,head_branch:"main",html_url:u+"12"}])
    }
    function wFixture() {
        panel.filterText=""
        panel.polling.repos=[{repo:"w/one",url:"https://gitlab.example.org/w/one",checked:"x",runs:wRuns()}]
        panel.polling.details={"w/one:11":{jobs:[{id:31,name:"compile",stage:"build",status:"in_progress",conclusion:"running"}]}}
        panel.expanded=({"repo:w/one":true,"w/one:11":true,"w/one:11:stage:build":true})
        panel.adopt()
        listFocus()
        panel.cursor=0
    }
    function wWatch(id) { eq(Polling.watch(panel.polling,"w/one",String(id),Date.now()),"watching","watch " + id); panel.adopt() }
    // Asks the closed scheduler for its next lookup and answers it with a finished run.
    function wFeed(conclusion) {
        var request=Polling.next(panel.polling, wTick())
        check(request && request.kind==="run" && request.repo==="w/one","closed lookup is a run request: " + JSON.stringify(request))
        var run=wRuns().filter(function(r) { return String(r.id)===request.run })[0]
        check(run,"lookup is for a watched run: " + request.run)
        panel.receivePage(JSON.stringify({requestId:request.requestId,data:Object.assign({},run,{status:"completed",conclusion:conclusion}),nextPage:0,error:"",errorType:"",remaining:4000}), request)
        return request
    }
    function w10Repos() { return [{repo:"one/sub/repo",checked:"x",runs:[{id:7,name:"CI",status:"in_progress",conclusion:"running",run_attempt:"active",head_branch:"main",run_number:1}]}] }
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
            panel.listItem.positionViewAtIndex(at, ListView.Contain)
            panel.listItem.forceLayout()
            var moreItem=panel.listItem.itemAtIndex(at)
            check(moreItem && moreItem.Accessible.role===Accessible.ListItem,"E10 more accessibility role")
            eq(moreItem.Accessible.name,Model.accessibleName(panel.entries[at]),"E10 more accessibility name")
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
        // P1-P14: pinned projects. The state file lives under XDG_STATE_HOME of this run.
        function() {
            cfg("gitlab.example.org",{pinned:["o/gamma"]})
            pinFixture()
        },
        function() {
            if (!waitUntil(function() { return panel.host==="gitlab.example.org" && panel.pinState[panel.host].loaded },"P1 pins loaded")) return false
            eq(JSON.stringify(startPins),'["zz/saved"]',"P1 start-up load read the file")
            panel.pinsError=""
            check(panel.pinned["o/gamma"] && !panel.pinned["o/alpha"],"P1 config pin applied")
        },
        function() {
            if (!waitUntil(function() { return rowItem("repo:o/gamma") },"P2 rows laid out")) return false
            eq(panel.entries[0].key,"repo:o/gamma","P2 config pin first")
            eq(panel.entries[1].key,"repo:o/alpha","P2 running project second")
            check(arrowOf(rowItem("repo:o/gamma")).indexOf("▸ ★ ")===0,"P2 star in the row: " + arrowOf(rowItem("repo:o/gamma")))
            check(arrowOf(rowItem("repo:o/alpha")).indexOf("★")<0,"P2 no star on an unpinned row")
        },
        function() {
            cursorTo("repo:o/delta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned o/delta","P3 notice")
            eq(panel.entries[1].key,"repo:o/delta","P3 pin moves up")
            eq(panel.current.key,"repo:o/delta","P3 cursor stays on the project")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":["o/delta"]}) },"P3 state file")) return false
            cursorTo("repo:o/delta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Unpinned o/delta","P4 notice")
            check(!panel.pinned["o/delta"],"P4 unpinned")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":[]}) },"P4 state file")) return false
            cursorTo("repo:o/gamma")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned in shell.json","P5 notice")
            check(panel.pinned["o/gamma"],"P5 still pinned")
        },
        function() {
            cfg("gitlab.example.org",{pinned:["o/gamma"].concat(Array.from({length:9},function(_, i) { return "p/x" + i }))})
            cursorTo("repo:o/beta")
            kPress(Qt.Key_P)
            eq(panel.notice,"At most 10 pins","P6 cap notice")
            check(!panel.pinned["o/beta"],"P6 not pinned")
            cfg("gitlab.example.org",{pinned:["o/gamma"]})
        },
        function() {
            cursorTo("repo:o/beta")
            var before=JSON.stringify([panel.pinState[panel.host].saved,panel.pinned])
            kPress(Qt.Key_P, Qt.ControlModifier)
            eq(panel.notice,"","P7 Ctrl+P shows no notice")
            eq(JSON.stringify([panel.pinState[panel.host].saved,panel.pinned]),before,"P7 Ctrl+P changes no pins")
            sh("chmod 500 '" + stateDir + "'")
        },
        function() {
            cursorTo("repo:o/beta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned o/beta","P8 pinned in memory")
        },
        function() {
            if (!waitUntil(function() { return panel.notice.indexOf("Pins not saved:")===0 },"P8 save failure notice")) return false
            sh("chmod 700 '" + stateDir + "'")
        },
        function() {
            // Unpin again so the file and the session agree before P9.
            cursorTo("repo:o/beta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Unpinned o/beta","P8 unpinned again")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":[]}) },"P8 state file")) return false
            cursorTo("repo:o/beta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned o/beta","P9 pin on example")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":["o/beta"]}) },"P9 example file")) return false
            cfg("gitlab.other.org")
        },
        function() {
            if (!waitUntil(function() { return panel.host==="gitlab.other.org" && panel.pinState[panel.host].loaded },"P9 other loaded")) return false
            panel.polling.repos=[{repo:"three/repo",checked:"x",runs:[]}]
            panel.adopt()
            cursorTo("repo:three/repo")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned three/repo","P9 pin on other")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.other.org":["three/repo"],"gitlab.example.org":["o/beta"]}) },"P9 distinct lists")) return false
            sh("touch '" + Quickshell.env("PINS_DELAY") + "'")
        },
        function() {
            // P10: a save for the old host is delayed while the host changes and a pin is queued.
            cursorTo("repo:three/repo")
            kPress(Qt.Key_P)
            eq(panel.notice,"Unpinned three/repo","P10 unpin on other")
            cfg("gitlab.example.org")
        },
        function() {
            if (!waitUntil(function() { return panel.host==="gitlab.example.org" && panel.pinState[panel.host].loaded },"P10 example loaded")) return false
            pinFixture()
            cursorTo("repo:o/delta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Pinned o/delta","P10 pin queued behind the delayed save")
            sh("rm -f '" + Quickshell.env("PINS_DELAY") + "'")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.other.org":[],"gitlab.example.org":["o/beta","o/delta"]}) },"P10 both saves landed")) return false
            sh("touch '" + Quickshell.env("PINS_DELAY") + "'")
        },
        function() {
            // P11: A -> B -> A while a save is pending: the session's list wins over the older file.
            pinFixture()
            cursorTo("repo:o/delta")
            kPress(Qt.Key_P)
            eq(panel.notice,"Unpinned o/delta","P11 unpin")
            cfg("gitlab.other.org")
            cfg("gitlab.example.org")
        },
        function() {
            if (!waitUntil(function() { return panel.host==="gitlab.example.org" && panel.pinState[panel.host].loaded },"P11 reload finished")) return false
            eq(JSON.stringify(panel.pinState[panel.host].saved),'["o/beta"]',"P11 session list, not the file's older one")
            sh("rm -f '" + Quickshell.env("PINS_DELAY") + "'")
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":["o/beta"]}) },"P11 state file")) return false
        },
        function() {
            // P12: the pins and the project list arrive in either order while the catalogue is incomplete.
            panel.polling.catalogueComplete=false
            panel.configured=false
            panel.polling.repos=[]
            setPin({saved:["o/beta"]})
            var before=JSON.stringify(panel.pinned)
            panel.applyPins()
            eq(JSON.stringify(panel.pinned),before,"P12 applyPins before configured does nothing")
            cfg("gitlab.example.org",{projects:["o/alpha"]})
            var names=panel.polling.repos.map(function(r) { return r.repo })
            check(names.indexOf("o/alpha")>=0 && names.indexOf("o/beta")>=0,"P12 config first: " + names)
            panel.configured=false
            panel.polling.repos=[]
            setPin({saved:[]})
            panel.sessionPins=({})
            cfg("gitlab.example.org",{projects:["o/alpha"]})
            panel.pinsLoadHost=panel.host
            panel.pinsLoadLife=panel.hostLife
            panel.finishPinsLoad(0,'{"pins":["o/gamma2"]}')
            names=panel.polling.repos.map(function(r) { return r.repo })
            check(names.indexOf("o/alpha")>=0 && names.indexOf("o/gamma2")>=0,"P12 load last: " + names)
            panel.polling.catalogueComplete=true
            setPin({saved:[]})
        },
        function() {
            // P13: a pin helper that cannot start.
            pinFixture()
            panel.pinsCommand=["/nonexistent-python"]
            setPin({loaded:false})
            panel.loadPins()
        },
        function() {
            if (!waitUntil(function() { return panel.pinState[panel.host].loaded && panel.pinsError.indexOf("Pins not loaded:")===0 },"P13 failed load")) return false
            panel.sessionPins=({})
            pinFixture()
            cursorTo("repo:o/beta")
            var before=panel.pinState[panel.host].saved.slice()
            kPress(Qt.Key_P)
            // After a failed load, p reloads instead of saving over the file.
            eq(panel.notice,"Pins not loaded; trying again","P13 p after failed load")
            eq(JSON.stringify(panel.pinState[panel.host].saved),JSON.stringify(before),"P13 nothing pinned after failed load")
        },
        function() {
            if (!waitUntil(function() { return panel.pinState[panel.host].loaded },"P13 reload done")) return false
            panel.pinsCommand=["python3"]
            setPin({loaded:false})
            panel.loadPins()
        },
        function() {
            if (!waitUntil(function() { return panel.pinState[panel.host].loaded && !panel.pinState[panel.host].loadFailed },"P13 good load")) return false
            panel.pinsCommand=["/nonexistent-python"]
            pinFixture()
            cursorTo("repo:o/beta")
            kPress(Qt.Key_P)
        },
        function() {
            if (!waitUntil(function() { return panel.notice.indexOf("Pins not saved:")===0 },"P13 failed save")) return false
            panel.pinsCommand=["python3"]
            panel.pinsError=""
        },
        function() {
            // P14: texts.
            panel.notice=""
            listFocus()
            tc.keyClick("?")
            check(panel.helpOpen,"? opens help")
        },
        function() {
            if (!waitUntil(function() { return panel.helpText.indexOf("Pin or unpin")>=0 },"P14 help text")) return false
            panel.helpOpen=false
            listFocus()
        },
        function() {
            if (!waitUntil(function() { return panel.footerHint.indexOf("p pin")>=0 },"P14 footer hint")) return false
        },
        function() {
            // T1: t off a job row says so and starts nothing.
            traceFixture()
            traceRm()
            panel.cursor=rowOf("repo")
            kPress(Qt.Key_T)
            eq(panel.notice,"Select a job to open its log","T1 repo row notice")
            panel.cursor=rowOf("run")
            kPress(Qt.Key_T)
            eq(panel.notice,"Select a job to open its log","T1 run row notice")
            check(panel.opened,"T1 panel stays open")
            kt=Date.now()+1000
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            check(!traceExists(),"T1 no trace started")
        },
        function() {
            // T2: a stage row and an empty list.
            traceFixture()
            panel.cursor=rowOf("stage")
            kPress(Qt.Key_T)
            eq(panel.notice,"Select a job to open its log","T2 stage row notice")
            panel.filterText="gltui-no-match-zzz"
            panel.adopt()
            eq(panel.entries.length,0,"T2 empty list")
            kPress(Qt.Key_T)
            eq(panel.notice,"Select a job to open its log","T2 empty list notice")
            check(panel.opened,"T2 panel stays open")
            panel.filterText=""
        },
        function() {
            // T3: t on a job runs the command with host, repo and job id, then closes.
            traceFixture()
            traceRm()
            panel.cursor=rowOf("job")
            kcur=panel.cursor
            kt=Date.now()+300
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            kPress(Qt.Key_T)
        },
        function() {
            if (!waitUntil(function() { return !panel.opened && traceExists() },"T3 panel closes and the file is written")) return false
            eq(traceFile.text().trim(),panel.host + "\\n" + panel.entries[kcur].repo + "\\n" + panel.entries[kcur].job,"T3 arguments")
            panel.open("{}")
        },
        function() {
            // T4: a launcher that fails, then one that is missing.
            traceFixture()
            panel.traceCommand=["sh","-c","exit 1","sh"]
            panel.cursor=rowOf("job")
            kPress(Qt.Key_T)
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Could not open a terminal" },"T4 exit code")) return false
            check(panel.opened,"T4 panel stays open")
            panel.notice=""
            panel.traceCommand=["gltui-no-such-binary"]
            kPress(Qt.Key_T)
        },
        function() {
            if (!waitUntil(function() { return panel.notice==="Could not open a terminal" },"T4 missing binary")) return false
            check(panel.opened,"T4 panel stays open after a missing binary")
        },
        function() {
            // T5: a late result after close and reopen is dropped.
            traceFixture()
            panel.traceCommand=["sh","-c","sleep 1","sh"]
            panel.cursor=rowOf("job")
            kPress(Qt.Key_T)
            pressKey(Qt.Key_Q)
            check(!panel.opened,"T5 q closes")
            panel.open("{}")
            kt=Date.now()+2000
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            check(panel.opened,"T5 panel is open")
            eq(panel.notice,"","T5 no late notice")
        },
        function() { tModStart() },
        function() { return tModPress(Qt.ControlModifier) },
        function() { return tModEnd("Ctrl") },
        function() { tModStart() },
        function() { return tModPress(Qt.AltModifier) },
        function() { return tModEnd("Alt") },
        function() { tModStart() },
        function() { return tModPress(Qt.MetaModifier) },
        function() { return tModEnd("Meta") },
        function() { tModStart() },
        function() { return tModPress(Qt.ShiftModifier) },
        function() { return tModEnd("Shift") },
        function() {
            // T6: t in help does nothing; then plain t is the positive control.
            traceFixture()
            panel.cursor=rowOf("job")
            traceRm()
            panel.helpOpen=true
            kPress(Qt.Key_T)
            kt=Date.now()+1000
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            check(panel.helpOpen && panel.opened,"T6 help stays open")
            check(!traceExists(),"T6 help does not trace")
            panel.helpOpen=false
            kPress(Qt.Key_T)
        },
        function() {
            if (!waitUntil(function() { return !panel.opened && traceExists() },"T6 plain t closes and writes the trace file")) return false
            panel.open("{}")
        },
        function() {
            // T7: t types into the search box.
            traceFixture()
            traceRm()
            pressKey(Qt.Key_Slash)
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.activeFocus },"T7 search focus")) return false
            typeText("t")
            eq(panel.filterText.slice(-1),"t","T7 typed into search")
            check(panel.opened,"T7 panel stays open")
            pressKey(Qt.Key_Escape)
            panel.filterText=""
            panel.adopt()
            check(!traceExists(),"T7 no trace")
        },
        function() {
            // T8: texts.
            panel.notice=""
            listFocus()
            tc.keyClick("?")
            check(panel.helpOpen,"? opens help")
        },
        function() {
            if (!waitUntil(function() { return panel.helpText.indexOf("job's log")>=0 },"T8 help text")) return false
            panel.helpOpen=false
            panel.notice=""
            listFocus()
        },
        function() {
            if (!waitUntil(function() { return panel.footerHint.indexOf("t log")>=0 },"T8 footer hint")) return false
            panel.traceCommand=["python3",panel.localPath("menu.py"),"trace"]
            panel.filterText=""
            panel.adopt()
        },
        function() {
            // W1: w on a pipeline row watches and unwatches it.
            wFixture(); notifyRm()
            cursorTo("w/one:11")
            kPress(Qt.Key_W)
            eq(panel.notice,"Watching #5 in w/one","W1 watch notice")
            check(panel.entries[panel.cursor].kind==="run" && panel.entries[panel.cursor].watched===true,"W1 row is watched")
        },
        function() {
            if (!waitUntil(function() { var r=rowItem("w/one:11"); return r && arrowOf(r).indexOf("◉")>=0 },"W1 row shows the mark")) return false
            kPress(Qt.Key_W)
            eq(panel.notice,"Stopped watching #5","W1 unwatch notice")
            check(panel.entries[panel.cursor].watched===false,"W1 row is not watched")
        },
        function() {
            // W2: stage and job rows watch their pipeline; project and finished rows do not.
            wFixture()
            cursorTo("w/one:11:stage:build"); kPress(Qt.Key_W)
            eq(panel.notice,"Watching #5 in w/one","W2 stage row watches")
            check(panel.polling.watches["w/one:11"],"W2 watch exists")
            cursorTo("w/one:11:31"); kPress(Qt.Key_W)
            eq(panel.notice,"Stopped watching #5","W2 job row stops")
            cursorTo("repo:w/one"); kPress(Qt.Key_W)
            eq(panel.notice,"Select a pipeline to watch","W2 project row")
            cursorTo("w/one:12"); kPress(Qt.Key_W)
            eq(panel.notice,"Pipeline already finished","W2 finished run")
            nokeys(panel.polling.watches,"W2 no watches left")
        },
        function() {
            // W3: the cap.
            wFixture()
            var ids=[11,13,14,15,16]
            ids.forEach(function(id) { eq(Polling.watch(panel.polling,"w/one",String(id),Date.now()),"watching","W3 watch " + id) })
            panel.adopt()
            cursorTo("w/one:17"); kPress(Qt.Key_W)
            eq(panel.notice,"At most 5 watched pipelines","W3 cap")
            panel.polling.watches=({})
            panel.adopt()
        },
        function() {
            // W9: modifiers do nothing; w types into the search box.
            wFixture(); cursorTo("w/one:11")
            var mods=[Qt.ControlModifier,Qt.AltModifier,Qt.MetaModifier,Qt.ShiftModifier]
            mods.forEach(function(m) { kPress(Qt.Key_W,m) })
            nokeys(panel.polling.watches,"W9 modifiers watch nothing")
            eq(panel.notice,"","W9 modifiers give no notice")
            pressKey(Qt.Key_Slash)
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.activeFocus },"W9 search focus")) return false
            typeText("w")
            eq(panel.filterText.slice(-1),"w","W9 typed into search")
            nokeys(panel.polling.watches,"W9 search watches nothing")
            pressKey(Qt.Key_Escape)
            panel.filterText=""
            panel.adopt()
            panel.notice=""
            listFocus()
        },
        function() {
            if (!waitUntil(function() { return panel.footerHint.indexOf("w watch")>=0 },"W9 footer hint")) return false
            listFocus()
            tc.keyClick("?")
            check(panel.helpOpen,"? opens help")
        },
        function() {
            if (!waitUntil(function() { return panel.helpText.indexOf("Watch or stop")>=0 },"W9 help text")) return false
            panel.helpOpen=false
            panel.notice=""
        },
        function() {
            // W4: a watched pipeline finishes while the panel is closed.
            wFixture(); notifyRm()
            wWatch(11)
            panel.close()
            check(panel.watching,"W4 watching while closed")
            var request=wFeed("success")
            eq(request.run,"11","W4 lookup is for the watched run")
        },
        function() {
            if (!waitUntil(function() { return notifyHas("Pipeline passed") && !panel.watching && notifyIdle() },"W4 notification sent and watch ended")) return false
            check(notifyHas("w/one #5 · main"),"W4 notification body")
        },
        function() {
            // W5: a notification that cannot be sent shows when the panel opens.
            wFixture()
            panel.notifyCommand=["sh","-c","exit 1","sh"]
            wWatch(11)
            panel.close()
            wFeed("success")
        },
        function() {
            if (!waitUntil(function() { return panel.missedNotices.length===1 && notifyIdle() },"W5 failed notification recorded")) return false
            panel.open('{"filter":"x"}')
            check(panel.notice.indexOf("Pipeline passed")>=0,"W5 missed notification shown on open: " + panel.notice)
            eq(panel.missedNotices.length,0,"W5 missed list cleared")
            panel.filterText=""
            panel.close()
        },
        function() {
            // W5: a missing command is recorded once per notification, and the queue goes on.
            wFixture()
            panel.notifyCommand=["gltui-no-such-binary"]
            wWatch(11); wWatch(13)
            panel.close()
            wFeed("failed"); wFeed("failed")
        },
        function() {
            if (!waitUntil(function() { return panel.missedNotices.length===2 && notifyIdle() },"W5 two failed starts recorded")) return false
            check(panel.missedNotices.every(function(m) { return m.indexOf("Pipeline failed")===0 }),"W5 both recorded: " + panel.missedNotices.join("|"))
            panel.missedNotices=[]
        },
        function() {
            // W6: a watch that outlives its time ends with a notification, even in a cooldown.
            if (!panel.opened) panel.open("{}")
            wFixture(); notifyRm()
            wWatch(11)
            check(panel.entries.some(function(r) { return r.key==="w/one:11" && r.watched }),"W6 row is watched")
            panel.polling.watches["w/one:11"].until=Date.now()-1
            panel.close()
            panel.polling.cooldown=Date.now()+3600000
            panel.workerBusy=false
            panel.pump()
            panel.workerBusy=true
            check(!panel.watching,"W6 watch ended")
        },
        function() {
            if (!waitUntil(function() { return notifyHas("Stopped watching a pipeline") && notifyIdle() },"W6 expiry notification")) return false
            check(notifyHas("w/one #5: still running after 6 hours"),"W6 body")
            panel.polling.cooldown=0
            panel.open("{}")
            check(panel.entries.some(function(r) { return r.key==="w/one:11" && r.watched===false }),"W6 row is no longer watched")
            panel.close()
            var before=panel.polling.requests
            panel.workerBusy=false
            panel.pump()
            panel.workerBusy=true
            eq(panel.polling.requests,before,"W6 nothing starts while closed")
        },
        function() {
            // W7: a sign-in problem found on close ends the watches with one notification.
            if (!panel.opened) panel.open("{}")
            wFixture(); notifyRm()
            wWatch(11)
            panel.polling.auth=true
            panel.close()
        },
        function() {
            if (!waitUntil(function() { return notifyHas("GitLab sign-in needed") && notifyIdle() },"W7 auth notification")) return false
            check(!panel.watching,"W7 watches ended")
            clearStops()
            panel.open("{}")
        },
        function() {
            // W8: a host change ends the watches with a notification.
            wFixture(); notifyRm()
            wWatch(11)
            cfg("gitlab.other.org")
        },
        function() {
            if (!waitUntil(function() { return notifyHas("Stopped watching 1 pipeline") && notifyIdle() },"W8 host notification")) return false
            check(!panel.watching,"W8 watches ended")
            cfg("gitlab.example.org")
        },
        function() {
            if (!waitUntil(function() { return panel.host==="gitlab.example.org" && panel.pinState[panel.host].loaded && panel.pinsLoadHost===panel.host && panel.pinsLoadLife===panel.hostLife },"W8 host restored")) return false
            sh('touch "$RUN_DONE"; rm -f "$RUN_DELAY"')
            kt=Date.now()+500
        },
        function() {
            // W10: through the real pump and the fake helper, a lookup that finishes while the panel is closed.
            if (Date.now()<kt) return false
            kt=0
            notifyRm()
            panel.close()
            panel.polling=Polling.create()
            panel.polling.repos=w10Repos()
            panel.polling.discover=false
            panel.polling.catalogueComplete=true
            panel.polling.catalogueAt=Date.now()
            panel.expanded=({})
            panel.filterText=""
            panel.adopt()
            eq(Polling.watch(panel.polling,"one/sub/repo","7",Date.now()),"watching","W10 watch")
            panel.polling.watches["one/sub/repo:7"].checkedAt=0
            panel.adopt()
            panel.workerBusy=false
        },
        function() {
            if (!waitUntil(function() { return notifyHas("Pipeline passed") && !panel.watching && !panel.workerBusy && panel.polling.flight===null && notifyIdle() },"W10 finish through the pump")) return false
            sh('touch "$RUN_DELAY"')
            kt=Date.now()+500
        },
        function() {
            // W10: the panel opens while a lookup is in flight; the reply is still accepted.
            if (Date.now()<kt) return false
            kt=0
            notifyRm()
            panel.polling.repos=w10Repos()
            panel.adopt()
            eq(Polling.watch(panel.polling,"one/sub/repo","7",Date.now()),"watching","W10 second watch")
            panel.adopt()
        },
        function() {
            if (!waitUntil(function() { return panel.workerBusy && panel.polling.flight!==null },"W10 delayed lookup in flight")) return false
            panel.open("{}")
        },
        function() {
            if (!waitUntil(function() { return notifyHas("Pipeline passed") && !panel.watching && notifyIdle() },"W10 reply accepted after open")) return false
            panel.close()
        },
        function() {
            if (!waitUntil(function() { return !panel.workerBusy && panel.polling.flight===null },"W10 flight clears")) return false
            zv.wRequests=panel.polling.requests
            kt=Date.now()+2000
        },
        function() {
            if (Date.now()<kt) return false
            kt=0
            eq(panel.polling.requests,zv.wRequests,"W10 nothing starts while closed")
            sh('rm -f "$RUN_DONE" "$RUN_DELAY"')
        },
        function() {
            // Restore the state the later steps expect.
            if (!waitUntil(function() { return notifyIdle() },"restore: notify idle")) return false
            panel.notifyCommand=["notify-send","--app-name=GitLab Pipelines"]
            panel.polling=Polling.create()
            panel.polling.repos=zRepos()
            panel.polling.discover=false
            panel.polling.catalogueComplete=true
            panel.polling.catalogueAt=Date.now()
            panel.polling.watches=({})
            panel.polling.events=[]
            panel.workerBusy=true
            panel.expanded=({})
            panel.filterText=""
            if (!panel.opened) panel.open("{}")
            panel.adopt()
        },
        function() {
            // Restore: no pins, empty state file.
            cfg("gitlab.example.org")
            setPin({saved:[]})
            panel.sessionPins=({})
            panel.savePins("gitlab.example.org",[])
        },
        function() {
            if (!waitUntil(function() { return stateIs({"gitlab.example.org":[]}) },"restore state file")) return false
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
        },
        // E11: drive the selection and expansion keys in a fixture that cannot poll.
        function() {
            keyFixture={repos:panel.polling.repos,expanded:panel.expanded,filter:panel.filterText,
                        cursor:panel.current && panel.current.key}
            panel.polling.repos=[{repo:"key/one",checked:"x",runs:[{id:7,name:"CI",status:"in_progress",conclusion:"running",run_number:1}]},
                                 {repo:"key/two",checked:"x",runs:[]}]
            panel.expanded=({"repo:key/one":true})
            panel.filterText=""
            panel.adopt()
            cursorTo("repo:key/one")
            listFocus()
        },
        function() {
            if (!waitUntil(function() { return panel.searchItem.parent.parent.activeFocus },"E11 list focus")) return false
            pressKey(Qt.Key_Down)
            eq(panel.current.key,"key/one:7","E11 keyboard selection")
            pressKey(Qt.Key_Right)
            check(panel.expanded["key/one:7"],"E11 Right expands run")
            var messageAt=panel.entries.findIndex(function(r) { return r.kind==="message" && r.parent==="key/one:7" })
            check(messageAt>=0 && panel.entries[messageAt].title==="Loading jobs…","E11 loading message")
            panel.listItem.positionViewAtIndex(messageAt,ListView.Contain)
            panel.listItem.forceLayout()
            var messageItem=panel.listItem.itemAtIndex(messageAt)
            check(messageItem && messageItem.Accessible.role===Accessible.ListItem,"E11 message accessibility role")
            eq(messageItem.Accessible.name,Model.accessibleName(panel.entries[messageAt]),"E11 message accessibility name")
            pressKey(Qt.Key_Left)
            check(!panel.expanded["key/one:7"] && has("repo:key/two"),"E11 collapse retains other repository")
            eq(panel.entries.length,3,"E11 collapse leaves three rows")
            var runAt=panel.entries.findIndex(function(r) { return r.key==="key/one:7" })
            panel.listItem.positionViewAtIndex(runAt,ListView.Contain)
            panel.listItem.forceLayout()
            eq(panel.listItem.itemAtIndex(runAt).Accessible.name,"CI, pipeline, running","E11 running name")
            panel.polling.repos[0].runs[0].status="completed"
            panel.polling.repos[0].runs[0].conclusion="failed"
            panel.adopt()
            runAt=panel.entries.findIndex(function(r) { return r.key==="key/one:7" })
            panel.listItem.positionViewAtIndex(runAt,ListView.Contain)
            panel.listItem.forceLayout()
            eq(panel.listItem.itemAtIndex(runAt).Accessible.name,"CI, pipeline, failed","E11 failed name after adopt")
            panel.polling.repos=keyFixture.repos
            panel.expanded=keyFixture.expanded
            panel.filterText=keyFixture.filter
            panel.adopt()
            if (keyFixture.cursor) { cursorTo(keyFixture.cursor); panel.selectionChanged(false) }
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
            if(stage===1 && panel.polling.requests>=6 && panel.details["one/sub/repo:7"] && panel.details["one/sub/repo:7"].jobs && panel.details["one/sub/repo:7"].bridges && panel.polling.catalogueComplete) {
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
                eq(lintItem.Accessible.selected,true,"a11y cursor row selected")
                ;["repo","run","stage","job","trigger"].forEach(function(kind) {
                    var index=panel.entries.findIndex(function(row) { return row.kind===kind })
                    check(index>=0,"a11y " + kind + " row exists")
                    panel.listItem.positionViewAtIndex(index,ListView.Contain)
                    panel.listItem.forceLayout()
                    var item=panel.listItem.itemAtIndex(index)
                    check(item && item.Accessible.role===Accessible.ListItem,"a11y " + kind + " role")
                    eq(item.Accessible.name,Model.accessibleName(panel.entries[index]),"a11y " + kind + " name")
                    for (var i=0;i<panel.entries.length;i++) {
                        var visible=panel.listItem.itemAtIndex(i)
                        if (visible) eq(visible.Accessible.selected,i===panel.cursor,"a11y selected row " + i)
                    }
                })
                eq(panel.listItem.Accessible.role,Accessible.List,"a11y list role")
                eq(panel.listItem.Accessible.name,"GitLab pipelines","a11y list name")
                eq(panel.searchItem.Accessible.role,Accessible.EditableText,"a11y search role")
                eq(panel.searchItem.Accessible.name,"Search projects","a11y search name")
                eq(panel.hintItem.Accessible.role,Accessible.StaticText,"a11y footer role")
                eq(panel.hintItem.Accessible.name,panel.hintItem.text,"a11y footer name")
                panel.notify("x")
                eq(panel.hintItem.Accessible.name,"x","a11y footer notice")
                var trigIndex=panel.entries.findIndex(function(row) { return row.kind==="trigger" })
                check(trigIndex>=0,"trigger row exists")
                panel.cursor=trigIndex
                panel.selectionChanged(true)
                kPress(Qt.Key_T)
                eq(panel.notice,"Job logs are not available for a trigger row","trigger row has no log")
                kPress(Qt.Key_W)
                eq(panel.notice,"Watch the parent pipeline row instead","trigger row cannot be watched")
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
            } else if(stage===13) {
                var mrstep=mrsteps[mi]
                if (mrstep() !== false) mi++
            } else if(stage===14) {
                var widgetStep=widgetSteps[wi]
                if (widgetStep() !== false) wi++
            } else if(stage===15) {
                var multiStep=mhsteps[mhi]
                if (multiStep() !== false) mhi++
            }
        }
    }
}
''')
        try:
            result=subprocess.run(['quickshell','-p',str(root),'--no-color'],capture_output=True,text=True,timeout=200,
                                  env={**os.environ, 'HOME':str(home), 'XDG_STATE_HOME':str(home / '.local/state'), 'PINS_DELAY':str(root / 'pins-delay'), 'RUN_DONE':str(root / 'run-done'), 'RUN_DELAY':str(root / 'run-delay'), 'MR_DELAY':str(root / 'mr-delay'), 'MULTI':str(root / 'multi'), 'OTHER_DELAY':str(root / 'other-delay'), 'OTHER_AUTH':str(root / 'other-auth'), 'HOST_LOG':str(root / 'host.log'), 'ACTION_SCRIPT':str(root / 'action.sh'), 'ACTION_LOG':str(root / 'actions.log'), 'MENU_SCENARIO':scenario, 'EXPECTED_BACKGROUND':colors['background'].lower(), 'STATUS_PATH':str(root / 'status.json'), 'WIDGET_STATUS_PATH':str(root / 'widget-status.json'), 'TOGGLE_LOG':str(root / 'omarchy-shell.log'), 'WIDGET_AVAILABLE':'1' if widget_available else '0', 'PATH':f"{root / 'bin'}:{os.environ.get('PATH', '')}"})
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
