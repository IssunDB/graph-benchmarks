{
  description = "Graph Benchmarks: IssunDB benchmarks against other graph databases";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system:
          let
            pkgs = import nixpkgs { inherit system; };
          in
          f pkgs
        );
    in
    {
      devShells = forAllSystems (pkgs:
        {
          default = pkgs.mkShell {
            name = "graph-benchmarks-dev";

            packages = with pkgs; [
              python313
              uv
              gnumake
              graphviz
              docker-compose
            ];

            shellHook = ''
              echo "Graph Benchmarks development environment"
              echo "Python: $(python3 --version 2>/dev/null || echo 'not found')"
              echo "uv: $(uv --version 2>/dev/null || echo 'not found')"
            '';
          };
        });

      formatter = forAllSystems (pkgs: pkgs.nixpkgs-fmt);
    };
}
