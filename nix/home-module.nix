# The user half: compose a new plate whenever the screen goes dark, and put it
# on the desktop and lock screen. The login screen needs root and lives in
# nix/nixos-module.nix instead.
self:
{ config, pkgs, lib, ... }:

let
  cfg = config.services.pomological;
  pom = "${cfg.package}/bin/pom";
in
{
  options.services.pomological = {
    enable = lib.mkEnableOption "the pomological watercolour rotation";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.system}.default;
      description = "The pomological package to run.";
    };

    treatment = lib.mkOption {
      type = lib.types.enum [ "rotate" "mat" "ledger" "board" "diptych" "cabinet" "bleed" ];
      default = "rotate";
      description = ''
        Which composition to use. "rotate" steps through all six, one per
        change, rather than picking at random -- so a week of changes shows all
        of them instead of three of them twice.
      '';
    };

    interval = lib.mkOption {
      type = lib.types.str;
      default = "1h";
      description = ''
        Minimum time between changes. This is a floor, not a schedule: the
        change happens the next time the screen goes dark after this much time
        has passed, never while you are looking at it.
      '';
    };

    mode = lib.mkOption {
      type = lib.types.enum [ "watch" "timer" ];
      default = "watch";
      description = ''
        "watch" changes the wallpaper when the screen locks, so unlocking
        reveals a picture that was already there. "timer" changes it on a
        schedule regardless of what you are doing, which is worse, and is here
        for desktops that do not announce locking on D-Bus.
      '';
    };

    dataDir = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Override where the scans and prepared plates live (POMOLOGICAL_DATA).";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    systemd.user.services.pomological = {
      Unit = {
        Description = "Change the pomological wallpaper when the screen goes dark";
        PartOf = [ "graphical-session.target" ];
        After = [ "graphical-session.target" ];
      };
      Service = {
        Environment = lib.optional (cfg.dataDir != null) "POMOLOGICAL_DATA=${cfg.dataDir}";
        ExecStart =
          if cfg.mode == "watch"
          then "${pom} watch --min-interval ${cfg.interval} --treatment ${cfg.treatment}"
          else "${pom} set --treatment ${cfg.treatment}";
        Restart = lib.mkIf (cfg.mode == "watch") "always";
        RestartSec = lib.mkIf (cfg.mode == "watch") "10s";
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };

    systemd.user.timers.pomological = lib.mkIf (cfg.mode == "timer") {
      Unit.Description = "Change the pomological wallpaper every ${cfg.interval}";
      Timer = {
        OnActiveSec = "5min";
        OnUnitActiveSec = cfg.interval;
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
