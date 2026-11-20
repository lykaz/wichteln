{
  description = "wichteln";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};

    pythonEnv = pkgs.python3.withPackages (ps: with ps; [
      flask
      gunicorn
    ]);

    appCode = pkgs.stdenv.mkDerivation {
      name = "flask-app-src";
      src = ./app/.;
      installPhase = ''
        mkdir -p $out/app
        cp -r * $out/app/
      '';
    };

  in {
    devShells.${system}.default = pkgs.mkShell {
      packages = with pkgs; [
        pythonEnv
        basedpyright
      ];
    };

    packages.${system}.dockerImage = pkgs.dockerTools.buildLayeredImage {
      name = "website";
      tag = "latest";

      contents = [ pythonEnv appCode ];

      config = {
        Cmd = [ "${pythonEnv}/bin/python" "-m" "gunicorn" "--bind" "0.0.0.0:5000" "app:app" ];
        WorkingDir = "/app";
        Env = [
          "FLASK_APP=app.py"
          "FLASK_ENV=production"
        ];
        ExposedPorts = {
          "5000/tcp" = {};
        };
      };
    };
  };
}
