{
  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } ({ lib, ... }:
      let
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
        overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
        pyprojectOverrides = final: prev: {
          fitparse = prev.fitparse.overrideAttrs (old: {
            nativeBuildInputs = old.nativeBuildInputs ++ [ final.setuptools ];
          });
        };
      in {
        systems = lib.systems.flakeExposed;

        perSystem = { config, pkgs, ... }:
          let
            python = pkgs.python313;
            pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
              inherit python;
            }).overrideScope (lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              overlay
              pyprojectOverrides
            ]);
          in {
            packages = {
              garmin-grafana = (pythonSet.mkVirtualEnv "garmin-grafana-env"
                workspace.deps.default).overrideAttrs {
                  meta.mainProgram = "garmin-fetch";
                };
              default = config.packages.garmin-grafana;
	      docker = pkgs.dockerTools.buildImage {
		name = "garmin-grafana";
		config = {
		  Cmd = [ (lib.getExe config.packages.garmin-grafana) ];
		};
	      };
            };

            devShells = {
              impure = pkgs.mkShell {
                packages = [ python pkgs.uv ];
                env = {
                  UV_PYTHON_DOWNLOADS = "never";
                  UV_PYTHON = python.interpreter;
                } // lib.optionalAttrs pkgs.stdenv.isLinux {
                  LD_LIBRARY_PATH =
                    lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux1;
                };
                shellHook = ''
                  unset PYTHONPATH
                '';
              };
              default = config.devShells.impure;
            };
          };
      });
}
