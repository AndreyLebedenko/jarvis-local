param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "help",
        "init",
        "update",
        "cluster",
        "query",
        "path",
        "explain",
        "hook-install",
        "hook-status",
        "hook-uninstall"
    )]
    [string] $Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Rest
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Require-Graphify {
    if (-not (Get-Command graphify -ErrorAction SilentlyContinue)) {
        throw "graphify is not installed. Install it with: python -m pip install graphifyy"
    }
}

function Invoke-Graphify {
    param([string[]] $GraphifyArgs)

    Require-Graphify
    & graphify @GraphifyArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Require-Graph {
    if (-not (Test-Path "graphify-out/graph.json")) {
        throw "graphify-out/graph.json is missing. Run: tools/graphify.ps1 init"
    }
}

switch ($Command) {
    "help" {
        @"
Jarvis graphify wrapper

Usage:
  tools/graphify.ps1 init                  Build the initial code graph
  tools/graphify.ps1 update                Fast code-only graph update
  tools/graphify.ps1 cluster               Rebuild clusters/report from graph.json
  tools/graphify.ps1 query "question"      Query the existing graph
  tools/graphify.ps1 path "A" "B"          Show shortest path between nodes
  tools/graphify.ps1 explain "Node"        Explain a node and neighbors
  tools/graphify.ps1 hook-install          Install graphify git hooks
  tools/graphify.ps1 hook-status           Show hook status
  tools/graphify.ps1 hook-uninstall        Remove graphify git hooks
"@
    }
    "init" {
        Invoke-Graphify -GraphifyArgs @("update", ".", "--no-cluster")
    }
    "update" {
        Invoke-Graphify -GraphifyArgs @("update", ".")
    }
    "cluster" {
        Require-Graph
        Invoke-Graphify -GraphifyArgs @("cluster-only", ".")
    }
    "query" {
        Require-Graph
        if ($Rest.Count -lt 1) {
            throw "query requires a question"
        }
        Invoke-Graphify -GraphifyArgs @("query", ($Rest -join " "))
    }
    "path" {
        Require-Graph
        if ($Rest.Count -lt 2) {
            throw "path requires two node labels"
        }
        Invoke-Graphify -GraphifyArgs @("path", $Rest[0], $Rest[1])
    }
    "explain" {
        Require-Graph
        if ($Rest.Count -lt 1) {
            throw "explain requires a node label"
        }
        Invoke-Graphify -GraphifyArgs @("explain", ($Rest -join " "))
    }
    "hook-install" {
        Invoke-Graphify -GraphifyArgs @("hook", "install")
    }
    "hook-status" {
        Invoke-Graphify -GraphifyArgs @("hook", "status")
    }
    "hook-uninstall" {
        Invoke-Graphify -GraphifyArgs @("hook", "uninstall")
    }
}
