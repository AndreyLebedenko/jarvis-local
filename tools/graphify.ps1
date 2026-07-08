param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "help",
        "init",
        "update",
        "semantic",
        "docs",
        "refresh",
        "label",
        "cluster",
        "query",
        "path",
        "explain",
        "hook-install",
        "hook-status",
        "hook-uninstall"
    )]
    [string] $Command = "help",

    [string] $Backend = "ollama",

    [string] $Model = "gemma4:12b-it-qat",

    [int] $MaxConcurrency = 1,

    [switch] $Deep,

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

function Invoke-SemanticExtract {
    if (-not $env:OLLAMA_API_KEY) {
        $env:OLLAMA_API_KEY = "ollama"
    }
    if ($Backend -eq "ollama") {
        $env:OLLAMA_MODEL = $Model
    }
    $graphifyArgs = @(
        "extract",
        ".",
        "--backend",
        $Backend,
        "--model",
        $Model,
        "--max-concurrency",
        $MaxConcurrency.ToString()
    )
    if ($Deep) {
        $graphifyArgs += @("--mode", "deep")
    }
    Invoke-Graphify -GraphifyArgs $graphifyArgs
}

function Invoke-LabelCommunities {
    if (-not $env:OLLAMA_API_KEY) {
        $env:OLLAMA_API_KEY = "ollama"
    }
    if ($Backend -eq "ollama") {
        $env:OLLAMA_MODEL = $Model
    }
    Invoke-Graphify -GraphifyArgs @("label", $repoRoot.Path, "--backend=$Backend")
}

switch ($Command) {
    "help" {
        @"
Jarvis graphify wrapper

Usage:
  tools/graphify.ps1 init                  Build the initial code graph
  tools/graphify.ps1 update                Fast code-only graph update
  tools/graphify.ps1 semantic              Full code+docs semantic extraction
  tools/graphify.ps1 refresh               Semantic extraction, then labels
  tools/graphify.ps1 docs                  Alias for refresh
  tools/graphify.ps1 label                 Refresh community labels only
    -Backend ollama                        LLM backend for semantic extraction
    -Model gemma4:12b-it-qat               Generative model for JSON extraction
    -MaxConcurrency 1                      Local LLM request concurrency
    -Deep                                  Use graphify's deep extraction mode
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
    "semantic" {
        Invoke-SemanticExtract
    }
    "docs" {
        Invoke-SemanticExtract
        Invoke-LabelCommunities
    }
    "refresh" {
        Invoke-SemanticExtract
        Invoke-LabelCommunities
    }
    "label" {
        Require-Graph
        Invoke-LabelCommunities
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
