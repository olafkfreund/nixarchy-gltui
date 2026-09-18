import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("menu", Path(__file__).resolve().parents[1] / "menu.py")
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class MenuTest(unittest.TestCase):
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


class RegistrationTest(unittest.TestCase):
    defaults = json.loads(Path(menu.__file__).with_name('menu.example.json').read_text())
    action = 'python3 ~/.config/omarchy/plugins/olafkfreund.github-actions/menu.py'

    def test_fresh_and_idempotent(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home):
            menu.register_menu()
            path = Path(home) / '.config/omarchy/extensions/omarchy-menu.jsonc'
            self.assertEqual(menu.parse_menu(path.read_text())[0], self.defaults)
            before = path.stat()
            menu.register_menu()
            self.assertEqual(path.stat(), before)

    def test_migrations_and_precedence(self):
        for keys in [('github-actions',), ('system.github-actions',),
                     ('github-actions', 'system.github-actions'),
                     ('github-actions', 'system.github-actions', 'apps.github-actions')]:
            with self.subTest(keys=keys):
                entries = {key: {'action': self.action, 'label': key, 'custom': [1, True]} for key in keys}
                source = json.dumps(entries)
                output = menu.registered_menu(source, self.defaults)
                data = menu.parse_menu(output)[0]
                self.assertEqual(data['apps.github-actions'], entries[keys[-1]])
                self.assertNotIn('github-actions', data)
                self.assertNotIn('system.github-actions', data)
                self.assertEqual(menu.registered_menu(output, self.defaults), output)

    def test_comments_strings_and_custom_entries(self):
        source = r'''{
  // heading with "fake": {} and punctuation ,}
  "github-actions": {"action": "unrelated", "label": "Keep me"},
  "system.github-actions": {
    /* keep this comment */ "action": "python3 ~/.config/omarchy/plugins/olafkfreund.github-actions/menu.py",
    "label": "Custom", "description": "https://host/quote\"/*not comment*/,}",
  },
  "learn.github-actions-keybindings": {"action": "custom keys"}, // keep keys
  "other": {"label": "unchanged", "array": [1, 2,],},
} // footer
'''
        output = menu.registered_menu(source, self.defaults)
        self.assertEqual(output, source.replace('"system.github-actions":', '"apps.github-actions":'))
        with_apps = output.replace('"other":', '"system.github-actions":')
        self.assertEqual(menu.registered_menu(with_apps, self.defaults), with_apps)
        # Deleting a duplicate retains its comments and unrelated text.
        duplicate = output.replace('"github-actions": {"action": "unrelated", "label": "Keep me"}',
                                   '"github-actions": {/* retain me */ "action": ' + json.dumps(self.action) + '}')
        deduped = menu.registered_menu(duplicate, self.defaults)
        self.assertIn('/* retain me */', deduped)
        self.assertIn('"other": {"label": "unchanged", "array": [1, 2,],},', deduped)
        self.assertNotIn('github-actions', menu.parse_menu(deduped)[0])

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
            self.assertEqual(list(path.parent.glob('.github-actions-menu-*')), [])
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
