$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$output = Join-Path $PSScriptRoot "FILES.sha256"
$files = @(
    "AGENTS.md",
    "README.md",
    "README.zh-CN.md",
    "HANDOFF-CODEX-GPT6.md",
    "PLAN-AA-vision-first.zh-CN.md",
    "PLAN-WPK-video-first.zh-CN.md",
    "handoff/2026-09-12/START-HERE.zh-CN.md",
    "handoff/2026-09-12/CURRENT-STATE.json",
    "handoff/2026-09-12/NEXT-TASK.zh-CN.md",
    "handoff/2026-09-12/MIGRATION-PROMPT.zh-CN.md",
    "handoff/2026-09-12/PRIVATE-ARTIFACTS.json",
    "handoff/2026-09-12/LATEST-TEST-RESULT.txt",
    "handoff/2026-09-12/PRE-CHECKPOINT-AUDIT.md",
    "handoff/2026-09-12/VERIFY.ps1",
    "handoff/2026-09-12/GENERATE-FILES.ps1",
    "configs/game/aa-shadow-rules-v2.json",
    "configs/strategy/aa-asset-binding-v2.schema.json",
    "configs/strategy/aa-range-asset-v2.schema.json",
    "configs/reproduction/aa8_candidate_v2/aa8_recording_split_plan_20260909.json",
    "src/poker_engine/strategy/aa8_shadow.py",
    "src/poker_engine/strategy/aa_rules_v2.py",
    "src/poker_engine/strategy/aa_rule_router_v2.py",
    "src/poker_engine/strategy/aa_asset_binding_v2.py",
    "src/poker_engine/strategy/aa_equity_shadow_v2.py",
    "src/poker_engine/strategy/aa_range_assets_v2.py",
    "src/poker_engine/strategy/shadow_log.py",
    "tools/aa8_candidate_v2.py",
    "tools/aa8_state_adapter_v2.py",
    "tools/aa8_live_wagers_v2.py",
    "tools/aa8_dealer_v2.py",
    "tools/aa8_strategy_state_v2.py",
    "tools/run_aa8_shadow_monitor.py",
    "docs/AA8-STRATEGY-BRIDGE-TASK1.zh-CN.md",
    "docs/AA8-SHADOW-LOG-BACKEND-TASK2.zh-CN.md",
    "docs/AA8-DEALER-LEDGER-ACTIONLINE-TASK3.zh-CN.md",
    "docs/AA8-RULES-AND-PROVIDER-GATE-TASK4.zh-CN.md",
    "docs/AA8-ASSET-AND-EQUITY-SHADOW-TASK5.zh-CN.md",
    "docs/AA8-RANGE-ASSET-TRACKER-TASK6.zh-CN.md"
)
$lines = foreach ($relative in $files) {
    $path = Join-Path $repo ($relative -replace "/", "\")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required handoff file is missing: $relative"
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    "$hash  $relative"
}
[System.IO.File]::WriteAllLines(
    $output,
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "Generated $($lines.Count) repository hashes at $output"
