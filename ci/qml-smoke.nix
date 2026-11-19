# Boots a real nixarchy session and runs tests/qml-smoke.py inside it.
# Node config is a focused copy of nixarchy's tests/session.nix.
{
  nixarchy,
  home-manager,
  gltui,
  pkgs,
}:
pkgs.testers.runNixOSTest {
  name = "gltui-qml-smoke";

  nodes.machine = {
    imports = [
      nixarchy.nixosModules.nixarchy
      home-manager.nixosModules.home-manager
    ];

    programs.nixarchy.enable = true;

    home-manager = {
      useGlobalPkgs = true;
      useUserPackages = true;
      sharedModules = [ nixarchy.homeManagerModules.nixarchy ];
      users.omarchy = {
        programs.nixarchy.enable = true;
        home.stateVersion = "25.05";
      };
    };

    users.users.omarchy = {
      isNormalUser = true;
      uid = 1000;
      password = "omarchy";
      extraGroups = [
        "wheel"
        "video"
        "input"
      ];
    };

    # plymouth-quit-wait never finishes without a display.
    boot.plymouth.enable = pkgs.lib.mkForce false;
    # No GPU in the VM; Hyprland refuses a software renderer unless told.
    environment.sessionVariables.WLR_RENDERER_ALLOW_SOFTWARE = "1";

    services.displayManager = {
      autoLogin = {
        enable = true;
        user = "omarchy";
      };
      defaultSession = "omarchy";
    };

    environment.systemPackages = [
      pkgs.python3
      pkgs.wl-clipboard
    ];

    virtualisation = {
      memorySize = 4096;
      cores = 2;
    };
  };

  # enableOCR is off: the greeter fallback only types the password blind.
  testScript = ''
    def on_desktop(cmd):
        return ("su omarchy -c 'XDG_RUNTIME_DIR=/run/user/1000"
                " HYPRLAND_INSTANCE_SIGNATURE=$(ls -t /run/user/1000/hypr | head -1) "
                + cmd + "'")

    machine.wait_for_unit("display-manager.service")

    # Login: autologin if it works, else the greeter with the typed password.
    logged_in = False
    for _ in range(90):
        if machine.execute("loginctl list-sessions --no-legend | grep -q omarchy")[0] == 0:
            logged_in = True
            break
        machine.sleep(1)
    if logged_in:
        print("login path: autologin")
    else:
        print("login path: greeter fallback (no omarchy session after 90 s)")
        machine.wait_until_succeeds("loginctl list-sessions | grep -q greeter")
        machine.send_chars("omarchy\n")
    machine.wait_until_succeeds("systemctl is-active user@1000.service", timeout=300)
    machine.wait_until_succeeds(on_desktop("hyprctl monitors"), timeout=300)

    # Readiness, each with its own failure message.
    tree = machine.succeed("su - omarchy -c 'echo $OMARCHY_PATH'").strip()
    for sub in ("Commons", "Ui"):
        rc, _ = machine.execute("test -d " + tree + "/shell/" + sub)
        assert rc == 0, "readiness: " + tree + "/shell/" + sub + " is missing"
    # The harness reads colors.toml; it only symlinks shell.toml and fontconfig,
    # which a fresh user may not have yet, so those are reported, not required.
    machine.wait_until_succeeds(
        "su - omarchy -c 'test -e ~/.local/state/omarchy/current/theme/colors.toml'", timeout=120)
    for path in ("~/.config/omarchy/shell.toml", "~/.config/fontconfig"):
        rc, _ = machine.execute("su - omarchy -c 'test -e " + path + "'")
        print("readiness: " + path + (" present" if rc == 0 else " absent (harness links it dangling)"))
    print("readiness: shell tree and theme colors present")

    # hypridle would lock the idle VM mid-test.
    machine.execute("pkill -x hypridle")
    rc, _ = machine.execute("pgrep -x hypridle")
    assert rc != 0, "hypridle is still running; the session would lock mid-test"

    machine.succeed("cp -rT ${gltui} /tmp/gltui && chmod -R u+w /tmp/gltui && chown -R omarchy /tmp/gltui")
    # Heredocs, not inline: on_desktop already wraps its command in single quotes.
    machine.succeed(
        "cat > /tmp/run-smoke.sh <<'EOF'\n"
        "cd /tmp/gltui && python3 /tmp/gltui/tests/qml-smoke.py /tmp/gltui > /tmp/smoke.out 2>&1; echo $? > /tmp/smoke.rc\n"
        "EOF\n"
        "cat > /tmp/dispatch.sh <<'EOF'\n"
        "hyprctl dispatch 'hl.dsp.exec_cmd(\"sh /tmp/run-smoke.sh\")'\n"
        "EOF")
    machine.succeed(on_desktop("sh /tmp/dispatch.sh"))

    machine.wait_for_file("/tmp/smoke.rc", timeout=600)
    out = machine.succeed("cat /tmp/smoke.out")
    print(out)
    rc = machine.succeed("cat /tmp/smoke.rc").strip()
    assert rc == "0", "qml-smoke.py exited " + rc
    assert out.count("QML_CHECKS_PASSED") == 2, (
        "expected QML_CHECKS_PASSED twice, saw " + str(out.count("QML_CHECKS_PASSED")))
  '';
}
