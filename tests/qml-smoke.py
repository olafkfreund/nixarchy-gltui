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
        for name in ('PipelinesPanel.qml', 'PipelinesModel.js', 'Polling.js', 'menu.py', 'menu.example.json'):
            (root / name).symlink_to(source / name)
        (root / 'gitlab.py').write_text('''import json, sys, time
request=json.loads(sys.argv[2]); kind=request['kind']
time.sleep(0.1)
host=request.get('host'); assert host in ('gitlab.example.org','gitlab.other.org'), request
run={'id':7,'name':'CI','status':'in_progress','conclusion':'running','run_attempt':'active','head_branch':'main','run_number':1}
if host=='gitlab.other.org': data={} if kind=='run' else [{'repo':'three/repo'}] if kind=='catalogue' else []
elif kind=='catalogue': data=[{'repo':'one/sub/repo','url':'https://gitlab.example.org/one/sub/repo'},{'repo':'two/repo'}]
elif kind=='jobs': data=[{'id':8,'name':'compile','stage':'build','status':'in_progress','conclusion':'running'},{'id':9,'name':'unit','stage':'test','status':'queued','conclusion':'created'}]
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
        interval: 45000; running: true
        onTriggered: { console.error("CHECK FAILED: timeout stage=" + stage + " " + panel.status()); Qt.quit() }
    }
    property int stage: 0
    property string selected: ""
    property double closedAt: 0
    property int closedRequests: 0
    function check(value, label) { if (!value) throw new Error("CHECK FAILED: " + label) }
    // when: false keeps TestCase from running tests and quitting; it is only used for keyClick.
    TestCase { id: tc; when: false }
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
    Timer {
        interval: 1000; running: true
        onTriggered: {
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
            panel.filterText="repo"
            check(panel.cursor===0 && panel.entries.length===2,"search resets collapsed results")
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
                check(panel.details["one/sub/repo:7"].jobs.length===2,"jobs arrive")
                check(panel.entries.filter(function(row) { return row.kind==="stage" }).length===2,"jobs grouped into stages")
                check(panel.polling.catalogueComplete,"catalogue completed")
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
                panel.polling.repos=Array.from({length:40},function(_, i) { return {repo:"z/p"+(i<10 ? "0" : "")+i,checked:"x",runs:[]} })
                panel.polling.discover=false
                panel.polling.catalogueComplete=true
                panel.polling.catalogueAt=Date.now()
                // Set before open(): open() pumps at once and the cooldown is what keeps Polling.next from returning a request.
                panel.polling.cooldown=Date.now()+3600000
                panel.expanded=({})
                panel.filterText=""
                panel.open("{}")
                panel.adopt()
                stage=10
            } else if(stage===10) {
                var step=zsteps[zi]
                if (step() !== false) zi++
            }
        }
    }
}
''')
        try:
            result=subprocess.run(['quickshell','-p',str(root),'--no-color'],capture_output=True,text=True,timeout=60,
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
