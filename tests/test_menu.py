import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("menu", Path(__file__).resolve().parents[1] / "menu.py")
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class MenuTest(unittest.TestCase):
    def test_remote(self):
        valid = {
            'git@host:group/sub/project.git': ('host', 'group/sub/project'),
            'ssh://git@host:2222/group/sub/project.git': ('host', 'group/sub/project'),
            'https://host:8443/group/sub/project.git/': ('host', 'group/sub/project'),
            'git@host:g/p': ('host', 'g/p'),
            'https://u@Host/g/s/p/': ('host', 'g/s/p'),
            '  https://host/g/p  ': ('host', 'g/p'),
        }
        for url, expected in valid.items():
            with self.subTest(url=url):
                self.assertEqual(menu.remote(url), expected)
        invalid = ('/local/path', 'file:///x/y', 'https://host/', 'https://host/p',
                   'git@host:/abs/path', 'https://host/g/../p', 'https://host/g%72oup/p',
                   'https://[broken/g/p', 'git@[::1]:g/p.git', 'https://host/g/p q',
                   'ftp://host/g/p')
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(menu.remote(url))

    def call_main(self, args, git_result=None):
        stderr = io.StringIO()
        events = []
        def git_call(*_args, **_kwargs):
            events.append('git')
            if isinstance(git_result, Exception):
                raise git_result
            return git_result
        def quickshell_call(*_args, **_kwargs):
            events.append('quickshell')
            return '[]'
        with patch.object(sys, 'argv', ['menu.py', *args]), \
                patch.object(menu.subprocess, 'check_output', side_effect=quickshell_call) as quickshell, \
                patch.object(menu.subprocess, 'run', side_effect=git_call) as git, \
                patch.object(menu, 'session_tree', return_value='/shell'), \
                patch.object(menu.os, 'execvp') as execvp, \
                patch.object(sys, 'stderr', stderr):
            result = menu.main()
        return result, stderr.getvalue(), git, quickshell, execvp, events

    def test_open_filter(self):
        filter_text = 'a"b\\c\n$(x)'
        result, stderr, git, quickshell, execvp, _ = self.call_main(['open', filter_text])
        self.assertIsNone(result)
        self.assertEqual(stderr, '')
        git.assert_not_called()
        quickshell.assert_called_once()
        self.assertEqual(execvp.call_args.args[1][4], json.dumps({'filter': filter_text}))

    def test_open_remote(self):
        response = Mock(returncode=0, stdout='https://Host/g/s/p.git\n')
        result, stderr, git, quickshell, execvp, events = self.call_main(['open'], response)
        self.assertIsNone(result)
        self.assertEqual(stderr, '')
        git.assert_called_once_with(['git', 'remote', 'get-url', 'origin'],
                                    capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(events, ['git', 'quickshell'])
        self.assertEqual(execvp.call_args.args[1],
                         ['omarchy-shell', 'shell', 'summon', 'olafkfreund.gitlab-pipelines',
                          json.dumps({'filter': 'g/s/p', 'host': 'host'})])

    def test_open_without_remote(self):
        cases = [
            (Mock(returncode=2, stdout=''), 'no Git origin remote here'),
            (Mock(returncode=0, stdout='file:///x/y'), 'unsupported Git origin remote'),
            (Mock(returncode=0, stdout='https://oauth2:glpat-SECRET@host/p'), 'unsupported Git origin remote'),
            (OSError('missing git'), 'no Git origin remote here'),
            (subprocess.TimeoutExpired(['git'], 5), 'no Git origin remote here'),
        ]
        for response, message in cases:
            with self.subTest(response=response):
                result, stderr, _, _, execvp, _ = self.call_main(['open'], response)
                self.assertIsNone(result)
                self.assertEqual(stderr, f'GitLab Pipelines: {message}\n')
                self.assertEqual(execvp.call_args.args[1][4], '{}')

    def test_open_usage(self):
        result, stderr, git, quickshell, execvp, _ = self.call_main(['open', 'a', 'b'])
        self.assertEqual(result, 1)
        self.assertEqual(stderr, 'GitLab Pipelines: Usage: menu.py [keys|toggle|register|open [FILTER]|trace HOST PROJECT JOB]\n')
        git.assert_not_called()
        quickshell.assert_not_called()
        execvp.assert_not_called()

    def test_trace_launch_and_exit(self):
        args = ['trace', 'gitlab.example.org:8443', 'g/s/p', '42']
        expected = [menu.LAUNCHER, '--app-id=org.omarchy.gitlab-trace', 'sh', '-c',
                    menu.TRACE, 'sh', '42', 'https://gitlab.example.org:8443/g/s/p']
        for outcome, code, error in (
            (subprocess.TimeoutExpired(expected, 2), 0, ''),
            (0, 0, ''),
            (3, 1, 'GitLab Pipelines: terminal launcher failed (exit 3)\n'),
        ):
            with self.subTest(outcome=outcome), patch.object(menu.subprocess, 'Popen') as popen:
                popen.return_value.wait.side_effect = outcome if isinstance(outcome, Exception) else None
                if not isinstance(outcome, Exception):
                    popen.return_value.wait.return_value = outcome
                result, stderr, git, quickshell, execvp, _ = self.call_main(args)
                self.assertEqual((result, stderr), (code, error))
                popen.assert_called_once_with(expected, start_new_session=True,
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
                popen.return_value.wait.assert_called_once_with(timeout=2)
                git.assert_not_called()
                quickshell.assert_not_called()
                execvp.assert_not_called()

    def test_trace_rejects_invalid_arguments(self):
        valid = ['gitlab.example.org', 'g/p', '42']
        invalid = [
            ['-x', *valid[1:]], ['a b', *valid[1:]],
            [valid[0], 'p', valid[2]], [valid[0], 'g/../p', valid[2]],
            [valid[0], 'g/p;x', valid[2]],
            *([valid[0], valid[1], job] for job in
              ('0', '-1', '1a', '12345678901234567890', '$(x)')),
            ['a', 'b'], ['a', 'b', 'c', 'd'],
        ]
        for args in invalid:
            with self.subTest(args=args), patch.object(menu.subprocess, 'Popen') as popen:
                result, stderr, git, quickshell, execvp, _ = self.call_main(['trace', *args])
                self.assertEqual(result, 1)
                self.assertTrue(stderr.startswith('GitLab Pipelines: '), stderr)
                popen.assert_not_called()
                git.assert_not_called()
                quickshell.assert_not_called()
                execvp.assert_not_called()

    def test_trace_missing_launcher(self):
        with patch.object(menu.subprocess, 'Popen', side_effect=FileNotFoundError('missing')) as popen:
            result, stderr, _, quickshell, execvp, _ = self.call_main(['trace', 'host', 'g/p', '42'])
        self.assertEqual(result, 1)
        self.assertEqual(stderr, 'GitLab Pipelines: missing\n')
        popen.assert_called_once()
        quickshell.assert_not_called()
        execvp.assert_not_called()

    def test_trace_real_launcher_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / 'launcher'
            for body, expected in (('sleep 5', (0, '')),
                                   ('exit 0', (0, '')),
                                   ('exit 3', (1, 'GitLab Pipelines: terminal launcher failed (exit 3)\n'))):
                with self.subTest(body=body):
                    launcher.write_text('#!/bin/sh\n' + body + '\n')
                    launcher.chmod(0o700)
                    with patch.object(menu, 'LAUNCHER', str(launcher)):
                        start = time.monotonic()
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', ResourceWarning)
                            result, stderr, _, quickshell, execvp, _ = self.call_main(['trace', 'host', 'g/p', '42'])
                        elapsed = time.monotonic() - start
                    self.assertEqual((result, stderr), expected)
                    self.assertLess(elapsed, 4)
                    quickshell.assert_not_called()
                    execvp.assert_not_called()

    def test_trace_shell_quotes_arguments_and_prompts_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fakebin = root / 'bin'
            fakebin.mkdir()
            glab = fakebin / 'glab'
            for exit_code in (0, 1):
                with self.subTest(exit_code=exit_code):
                    glab.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit ' + str(exit_code) + '\n')
                    glab.chmod(0o700)
                    result = subprocess.run(
                        ['sh', '-c', menu.TRACE, 'sh', '$(touch X)', 'u;v'], cwd=root,
                        env={**os.environ, 'PATH': f'{fakebin}:{os.environ["PATH"]}'},
                        stdin=subprocess.DEVNULL, capture_output=True, text=True)
                    self.assertEqual(result.stdout.splitlines(),
                                     ['ci', 'trace', '$(touch X)', '-R', 'u;v', '', 'Press Enter to close. '])
                    self.assertFalse((root / 'X').exists())

    def test_running_tree_and_ambiguous_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            trees = [Path(directory) / name for name in ("running", "other")]
            for tree in trees:
                marker = tree / "shell/plugins/menu/Menu.qml"
                marker.parent.mkdir(parents=True)
                marker.touch()
            instances = [{"config_path": str(tree / "shell/shell.qml")} for tree in trees]
            self.assertEqual(menu.session_tree(instances[:1]), str(trees[0]))
            self.assertEqual(menu.session_tree(instances[:1] * 2), str(trees[0]))
            with self.assertRaises(RuntimeError):
                menu.session_tree(instances)
            with self.assertRaises(RuntimeError):
                menu.session_tree([])
            with self.assertRaises(RuntimeError):
                menu.session_tree([{"config_path": str(Path(directory) / "unrelated/shell.qml")}])
            for malformed in ([{}], [{"config_path": None}], ["x"]):
                with self.subTest(malformed=malformed), self.assertRaises(RuntimeError):
                    menu.session_tree(malformed)


class RegistrationTest(unittest.TestCase):
    defaults = json.loads(Path(menu.__file__).with_name('menu.example.json').read_text())

    def test_fresh_and_idempotent(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home):
            menu.register_menu()
            path = Path(home) / '.config/omarchy/extensions/omarchy-menu.jsonc'
            self.assertEqual(menu.parse_menu(path.read_text())[0], self.defaults)
            before = path.stat()
            menu.register_menu()
            self.assertEqual(path.stat(), before)

    def test_comments_strings_and_custom_entries(self):
        source = r"""{
  // heading with "fake": {} and punctuation ,}
  "apps.gitlab-pipelines": {
    /* keep this comment */ "action": "custom launcher",
    "label": "Custom", "description": "https://host/quote\"/*not comment*/,}",
  },
  "other": {"label": "unchanged", "array": [1, 2,],},
} // footer
"""
        output = menu.registered_menu(source, self.defaults)
        # Existing customisations win; only the missing entry is appended.
        self.assertTrue(output.startswith(source[:source.rindex('}')]))
        self.assertIn('/* keep this comment */', output)
        self.assertIn('// footer', output)
        data = menu.parse_menu(output)[0]
        self.assertEqual(data['apps.gitlab-pipelines']['action'], 'custom launcher')
        self.assertEqual(data['learn.gitlab-pipelines-keybindings'], self.defaults['learn.gitlab-pipelines-keybindings'])
        self.assertEqual(menu.registered_menu(output, self.defaults), output)

    def test_addition_after_line_comment(self):
        source = '{"other": {} // last entry\n}'
        output = menu.registered_menu(source, self.defaults)
        self.assertIn('// last entry\n}', output)
        self.assertEqual(set(menu.parse_menu(output)[0]), {'other', *self.defaults})

    def test_invalid_documents(self):
        for source in ('{', '[]', '{,}', '{"x": {,}}', '{"x": {"a": [1,,]}}',
                       '{"x": {}, "x": {}}', '{"x": {"a":1,"a":2}}',
                       '{"x": null}', '{"x": {"a": NaN}}', '{/* unterminated}',
                       '{"x": {"a": "unterminated}}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                menu.registered_menu(source, self.defaults)

    def test_file_failures_permissions_and_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home):
            path = Path(home) / '.config/omarchy/extensions/omarchy-menu.jsonc'
            path.parent.mkdir(parents=True)
            original = b'{"other": {}}\n'
            path.write_bytes(original)
            path.chmod(0o640)
            with patch.object(menu.os, 'replace', side_effect=PermissionError('test denied')):
                with self.assertRaises(PermissionError):
                    menu.register_menu()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('.gitlab-pipelines-menu-*')), [])
            real_render = menu.registered_menu
            def concurrent(source, defaults):
                path.write_text('{"edited": {}}')
                return real_render(source, defaults)
            with patch.object(menu, 'registered_menu', side_effect=concurrent):
                with self.assertRaisesRegex(ValueError, 'changed during'):
                    menu.register_menu()
            self.assertEqual(path.read_text(), '{"edited": {}}')
            path.write_bytes(original)
            menu.register_menu()
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                menu.register_menu()
            self.assertEqual(path.read_text(), '{broken')
            path.write_bytes(original)
            path.chmod(0o440)
            with self.assertRaisesRegex(ValueError, 'not writable'):
                menu.register_menu()
            path.unlink()
            target = Path(home) / 'managed'
            target.write_bytes(original)
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'managed'):
                menu.register_menu()
            self.assertTrue(path.is_symlink())
            self.assertEqual(target.read_bytes(), original)

    def test_managed_marker_leaves_menu_untouched(self):
        source = '// mine\n{"my.row": {"label": "Mine"}}\n'
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home), \
                tempfile.TemporaryDirectory() as plugin:
            path = Path(home) / '.config/omarchy/extensions/omarchy-menu.jsonc'
            path.parent.mkdir(parents=True)
            path.write_text(source)
            before = path.stat()
            Path(plugin, 'menu.example.json').write_text(
                Path(menu.__file__).with_name('menu.example.json').read_text())
            Path(plugin, 'menu.managed').touch()
            with patch.object(menu, '__file__', str(Path(plugin, 'menu.py'))):
                menu.register_menu()
                self.assertEqual(path.read_text(), source)
                self.assertEqual(path.stat(), before)
                path.unlink()
                menu.register_menu()
                self.assertFalse(path.exists())
                Path(plugin, 'menu.managed').unlink()
                Path(plugin, 'menu.managed').symlink_to(Path(plugin, 'missing'))  # dangling marker still counts
                menu.register_menu()
                self.assertFalse(path.exists())
