{
  description = "USDA Pomological Watercolor Collection as a desktop, lock and login wallpaper";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in
    {
      packages = forAll (pkgs: rec {
        pomological = pkgs.callPackage ./nix/package.nix { };
        default = pomological;
      });

      apps = forAll (pkgs: rec {
        pomological = {
          type = "app";
          program = "${self.packages.${pkgs.system}.pomological}/bin/pom";
        };
        default = pomological;
      });

      # `nix develop` for hacking on the scripts without installing anything.
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.pillow ]))
            pkgs.sqlite
          ];
        };
      });

      # The greeter half. Needs root, so it is a system module rather than
      # something the rotation can do for itself.
      nixosModules.default = import ./nix/nixos-module.nix;

      # The user half: the rotation service, for people who run home-manager.
      homeModules.default = import ./nix/home-module.nix self;
      homeManagerModules.default = self.homeModules.default;   # older name

      formatter = forAll (pkgs: pkgs.nixpkgs-fmt);
    };
}
