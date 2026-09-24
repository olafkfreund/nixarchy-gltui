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
