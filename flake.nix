{
  description = "GitLab Pipelines panel for the Omarchy shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      version = (builtins.fromJSON (builtins.readFile ./manifest.json)).version;
      runtimeFiles = [
        "LICENSE"
        "manifest.json"
        "PipelinesPanel.qml"
        "PipelinesModel.js"
        "Polling.js"
        "gitlab.py"
        "menu.py"
        "menu.example.json"
        "keybindings.sh"
      ];
    in
    {
      packages = forAllSystems (pkgs: {
        default = pkgs.runCommand "nixarchy-gltui-${version}" {
          inherit version;
          # Found on PATH at run time, not substituted, so Git installs keep working (#15).
          passthru.runtimeDeps = [
            pkgs.glab
            pkgs.python3
            pkgs.xdg-utils
          ];
          meta = {
            description = "GitLab Pipelines panel for the Omarchy shell";
            homepage = "https://github.com/olafkfreund/nixarchy-gltui";
            license = nixpkgs.lib.licenses.mit;
            platforms = nixpkgs.lib.platforms.linux;
          };
        } ''
          mkdir -p "$out"
          ${nixpkgs.lib.concatMapStringsSep "\n" (file: ''
            cp ${./. + "/${file}"} "$out/${file}"
          '') runtimeFiles}
        '';
      });

      checks = forAllSystems (pkgs: {
        plugin =
          pkgs.runCommand "nixarchy-gltui-checks-${version}"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.nodejs
              ];
            }
            ''
              plugin=${self.packages.${pkgs.stdenv.hostPlatform.system}.default}
              python3 - "$plugin" <<'PY'
              import json, sys
              from pathlib import Path
              root = Path(sys.argv[1])
              assert sorted(p.name for p in root.iterdir()) == sorted(${builtins.toJSON runtimeFiles})
              assert (root / 'LICENSE').is_file(), 'the package must ship its licence'
              assert not any(p.is_symlink() for p in root.rglob('*'))
              manifest = json.loads((root / 'manifest.json').read_text())
              assert manifest['version'] == '${version}'
              assert manifest['id'] == 'olafkfreund.gitlab-pipelines'
              assert all((root / entry).is_file() for entry in manifest['entryPoints'].values())
              PY
              cp "$plugin"/* .
              cp -R ${./tests} tests
              export HOME="$TMPDIR/home"
              mkdir -p "$HOME"
              python3 -m unittest discover -s tests -v
              node tests/model.cjs
              node tests/polling.cjs
              python3 menu.py register
              bash keybindings.sh --print > /dev/null
              if python3 tests/qml-smoke.py "$TMPDIR/missing" 2> invalid-directory; then
                exit 1
              fi
              grep -F 'plugin_dir must contain the complete GitLab Pipelines plugin' invalid-directory
              touch "$out"
            '';
      });
    };
}
