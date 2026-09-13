{ lib, stdenvNoCC, python3, makeWrapper
, xfconf, xorg, glib, dbus, coreutils, fontconfig
, dejavu_fonts, noto-fonts
}:

let
  py = python3.withPackages (ps: [ ps.pillow ]);
in
stdenvNoCC.mkDerivation {
  pname = "pomological";
  version = "0.1.0";
  src = ../.;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/pomological $out/bin
    cp -r scripts $out/share/pomological/
    cp -r data/botany.json $out/share/pomological/botany.json

    makeWrapper ${py}/bin/python3 $out/bin/pom \
      --add-flags "$out/share/pomological/scripts/pom" \
      --set POMOLOGICAL_BOTANY "$out/share/pomological/botany.json" \
      --prefix PATH : ${lib.makeBinPath [
        xfconf xorg.xrandr glib dbus coreutils fontconfig
      ]} \
      --prefix XDG_DATA_DIRS : "${dejavu_fonts}/share:${noto-fonts}/share"

    runHook postInstall
  '';

  meta = with lib; {
    description = "Compose and set wallpapers from the USDA Pomological Watercolor Collection";
    longDescription = ''
      7,584 watercolours of fruit painted for the USDA between 1886 and 1942,
      composed for the screen you actually have -- including ultrawides, where
      a single portrait plate would waste most of the width -- and set on the
      desktop, lock and login screens.
    '';
    license = licenses.mit;          # the paintings themselves are public domain
    platforms = platforms.linux;
    mainProgram = "pom";
  };
}
