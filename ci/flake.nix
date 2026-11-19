{
  description = "gltui CI: boots a nixarchy session and runs the QML smoke test";

  inputs = {
    nixarchy.url = "github:olafkfreund/nixarchy/600730956cbb3da5e3ed1311e2d5a0404c07772e";
    gltui = {
      url = "path:..";
      flake = false;
    };
  };

  outputs =
    { nixarchy, gltui, ... }:
    let
      pkgs = nixarchy.inputs.nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      checks.x86_64-linux.qml-smoke = import ./qml-smoke.nix {
        inherit nixarchy gltui pkgs;
        home-manager = nixarchy.inputs.home-manager;
      };
    };
}
