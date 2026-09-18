"""Launch menu actions against the running desktop, including after a Nix rebuild."""
import json
import os
import re
import stat
from pathlib import Path
import subprocess
import sys
import tempfile


# Keep source offsets while letting the standard JSON decoder validate values.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/|[^\s]')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate menu key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_menu(source):
    tokens = []
    clean = list(source)
    for match in JSONC_TOKEN.finditer(source):
        if match[0].startswith(('//', '/*')):
            clean[match.start():match.end()] = ' ' * len(match[0])
        else:
            tokens.append(match)
    for index, (previous, following) in enumerate(zip(tokens, tokens[1:])):
        if (previous[0] == ',' and following[0] in (']', '}')
                and index > 0 and tokens[index - 1][0] not in ('{', '[', ',', ':')):
            clean[previous.start()] = ' '
    data = json.loads(''.join(clean), object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)
    if not isinstance(data, dict) or any(not isinstance(value, dict) for value in data.values()):
        raise ValueError('Menu must be an object of entry objects')
    return data, tokens


def registered_menu(source, defaults):
    data, tokens = parse_menu(source)
    missing = {key: value for key, value in defaults.items() if key not in data}
    if missing:
        # Put separators immediately after the last value, before any line comment.
        position = tokens[-2].end()
        separator = ',' if data and tokens[-2][0] != ',' else ''
        addition = json.dumps(missing, ensure_ascii=False, indent=2)[1:-1]
        source = source[:position] + separator + addition + '\n' + source[position:]
    parse_menu(source)
    return source


def register_menu():
    path = Path.home() / '.config/omarchy/extensions/omarchy-menu.jsonc'
    guidance = 'Declare menu.example.json in the host configuration for managed menu files.'
    if path.is_symlink() or path.resolve().is_relative_to('/nix/store'):
        raise ValueError(f'Menu is managed: {path}. {guidance}')
    original = path.read_bytes() if path.exists() else None
    before = path.stat() if original is not None else None
    if before and not before.st_mode & 0o222:
        raise ValueError(f'Menu is not writable: {path}. {guidance}')
    defaults = json.loads(Path(__file__).with_name('menu.example.json').read_text())
    updated = registered_menu(original.decode('utf-8') if original is not None else '{}\n', defaults).encode('utf-8')
    if updated == original:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.gitlab-pipelines-menu-', delete=False) as output:
            temporary = Path(output.name)
            output.write(updated)
            if before:
                os.fchmod(output.fileno(), stat.S_IMODE(before.st_mode))
        current = path.stat() if path.exists() else None
        if path.is_symlink() or current != before or (current and path.read_bytes() != original):
            raise ValueError('Menu changed during registration; retry after editing finishes')
        os.replace(temporary, path)
    except PermissionError as error:
        raise PermissionError(f'{error}. {guidance}') from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def session_tree(instances):
    trees = {
        Path(instance["config_path"]).parent.parent
        for instance in instances
        if Path(instance["config_path"]).name == "shell.qml"
        and (Path(instance["config_path"]).parent / "plugins/menu/Menu.qml").is_file()
    }
    if len(trees) != 1:
        raise RuntimeError("Expected one running Omarchy shell on this display")
    return str(trees.pop())


def main():
    try:
        if sys.argv[1:] == ["register"]:
            register_menu()
            return 0
        if sys.argv[1:] not in ([], ["keys"], ["toggle"]):
            raise ValueError("Usage: menu.py [keys|toggle|register]")
        instances = json.loads(subprocess.check_output(
            ["quickshell", "list", "--all", "--json"], text=True, timeout=5))
        os.environ["OMARCHY_PATH"] = session_tree(instances)
        command = (["bash", str(Path(__file__).with_name("keybindings.sh"))]
                   if sys.argv[1:] == ["keys"] else
                   ["omarchy-shell", "shell", "toggle" if sys.argv[1:] == ["toggle"] else "summon", "olafkfreund.gitlab-pipelines", "{}"])
        os.execvp(command[0], command)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"GitLab Pipelines: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
