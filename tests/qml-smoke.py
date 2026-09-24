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
assert request.get('host')=='gitlab.example.org', request
run={'id':7,'name':'CI','status':'in_progress','conclusion':'running','run_attempt':'active','head_branch':'main','run_number':1}
if kind=='catalogue': data=[{'repo':'one/sub/repo','url':'https://gitlab.example.org/one/sub/repo'},{'repo':'two/repo'}]
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
import Quickshell
import Quickshell.Io
import qs.Commons
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
        interval: 18000; running: true
        onTriggered: { console.error("CHECK FAILED: timeout stage=" + stage + " " + panel.status()); Qt.quit() }
    }
    property int stage: 0
    property string selected: ""
    property double closedAt: 0
    property int closedRequests: 0
    function check(value, label) { if (!value) throw new Error("CHECK FAILED: " + label) }
    Timer {
        interval: 1000; running: true
        onTriggered: {
            check(Color.background.toString()===Quickshell.env("EXPECTED_BACKGROUND"),"active Omarchy theme")
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
            } else if(stage===3 && !panel.workerBusy) {
                console.log("QML_CHECKS_PASSED")
                Qt.quit()
            }
        }
    }
}
''')
        try:
            result=subprocess.run(['quickshell','-p',str(root),'--no-color'],capture_output=True,text=True,timeout=25,
                                  env={**os.environ, 'HOME':str(home), 'MENU_SCENARIO':scenario, 'EXPECTED_BACKGROUND':colors['background'].lower()})
        except subprocess.TimeoutExpired as error:
            print(error.stdout, error.stderr)
            raise
        output=result.stdout+result.stderr
        print(output)
        if result.returncode or 'QML_CHECKS_PASSED' not in output or any(term in output for term in ('ERROR:', 'ReferenceError','TypeError','CHECK FAILED')):
            raise SystemExit('QML smoke check failed')
        if scenario == 'managed':
            assert 'GitLab Pipelines menu registration failed:' in output and 'Menu is managed:' in output
            assert menu_path.is_symlink() and menu_path.read_text() == '{}\n'
        else:
            assert 'menu registration failed' not in output
            assert '"apps.gitlab-pipelines"' in menu_path.read_text()
