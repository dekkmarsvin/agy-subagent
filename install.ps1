[CmdletBinding()]
param([string]$SkillsRoot)
$ErrorActionPreference = 'Stop'
if (-not $SkillsRoot) {
    $codexBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $SkillsRoot = Join-Path $codexBase 'skills'
}
$destination = Join-Path $SkillsRoot 'agy-subagent'
$files = @('SKILL.md', 'agents/openai.yaml', 'scripts/invoke_agy.py', 'scripts/agy_control.py', 'scripts/test_invoke_agy.py', 'scripts/test_agy_control.py')
foreach ($relative in $files) {
    $sourceFile = Join-Path $PSScriptRoot $relative
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { throw "Missing package file: $relative" }
}
foreach ($relative in $files) {
    $target = Join-Path $destination $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $relative) -Destination $target -Force
}
Write-Output "Installed agy-subagent to $destination (local model selection preserved)."
