# The login screen half.
#
# SDDM's greeter runs as its own user, before any session exists, and cannot
# read /home -- which is mode 0700 on most systems. So the rotation cannot set
# the greeter's wallpaper directly the way it sets the desktop's. Instead it
# drops a copy somewhere world-readable, and a theme points at that path.
#
# If the image is missing -- a fresh boot before the rotation has ever run --
# the base theme falls back to its own solid colour, so an absent or corrupt
# file can never keep anyone out.
{ config, pkgs, lib, ... }:

let
  cfg = config.services.pomological.login;

  themed = pkgs.runCommand "sddm-theme-pomological" { } ''
    mkdir -p $out/share/sddm/themes
    cp -r ${cfg.baseTheme}/share/sddm/themes/${cfg.baseThemeName} \
          $out/share/sddm/themes/pomological
    chmod -R u+w $out/share/sddm/themes/pomological
    conf=$out/share/sddm/themes/pomological/theme.conf
    # Rewrite the whole line rather than matching the base theme's current
    # default wallpaper path, which moves with every upstream bump. Fail the
    # build if the key is gone, so a silently unthemed greeter is impossible.
    grep -q '^background=' $conf || { echo "theme.conf has no background= key"; exit 1; }
    sed -i "s|^background=.*|background=${cfg.imageDir}/login.jpg|" $conf
    grep -q '^background=${cfg.imageDir}/login.jpg$' $conf \
      || { echo "background= rewrite did not take"; exit 1; }
  '';
in
{
  options.services.pomological.login = {
    enable = lib.mkEnableOption "a pomological watercolour on the SDDM login screen";

    user = lib.mkOption {
      type = lib.types.str;
      description = "User who owns the image directory, i.e. who runs the rotation.";
      example = "alice";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "users";
      description = "Group for the image directory.";
    };

    imageDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/pomological";
      description = ''
        World-readable directory the greeter reads `login.jpg` from. Must not
        be under /home, which the greeter cannot traverse.
      '';
    };

    baseTheme = lib.mkOption {
      type = lib.types.package;
      default = pkgs.kdePackages.plasma-desktop;
      description = "Package providing the SDDM theme to copy and re-point.";
    };

    baseThemeName = lib.mkOption {
      type = lib.types.str;
      default = "breeze";
      description = ''
        Theme directory inside `baseTheme` to copy. Copying an existing theme
        rather than writing one keeps the user list, session picker and clock.
      '';
    };

    preserveCursor = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Plasma only sets the greeter's cursor theme while SDDM's theme is still
        named "breeze", so renaming it quietly drops the cursor back to the X
        default. This puts it back.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      # 0755 so the greeter can traverse in; owned by the rotation's user so it
      # can write without root.
      "d ${cfg.imageDir} 0755 ${cfg.user} ${cfg.group} - -"
    ];

    environment.systemPackages = [ themed ];
    services.displayManager.sddm.theme = "pomological";

    services.displayManager.sddm.settings = lib.mkIf cfg.preserveCursor {
      Theme = {
        CursorTheme = "breeze_cursors";
        CursorSize = 24;
      };
    };
  };
}
