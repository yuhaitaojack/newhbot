param(
    [string]$CredentialFile = "C:\Users\Admin\Desktop\hyper.txt"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $CredentialFile)) { throw "credential file not found" }
$text = [System.IO.File]::ReadAllText($CredentialFile)
# The handoff file may contain a trailing annotation after the hex value.
# Select by protocol-sized candidates and take only the required prefix.
$candidates = [regex]::Matches($text, '0x[0-9A-Fa-f]+', [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)
if ($candidates.Count -lt 2 -or $candidates[0].Value.Length -lt 42 -or $candidates[$candidates.Count - 1].Value.Length -lt 66) {
    $lengths = ($candidates | ForEach-Object { $_.Value.Length }) -join ','
    throw "credential file does not contain expected address/key formats (count=$($candidates.Count), lengths=$lengths)"
}
$addressValue = $candidates[0].Value.Substring(0, 42)
$keyValue = $candidates[$candidates.Count - 1].Value.Substring(0, 66)

# Values are inherited by the child process only; they are never printed.
$env:HYPERLIQUID_PERPETUAL_ADDRESS = $addressValue
$env:HYPERLIQUID_PERPETUAL_SECRET_KEY = $keyValue
$env:EXECUTION_MODE = "hyperliquid"
$env:EXECUTION_ENABLED = "false"
$env:HUMMINGBOT_LIVE_CONNECTOR = "true"

$probe = @'
import asyncio, json
from app.factory import build_runtime

async def main():
    runtime = build_runtime()
    await runtime.connect()
    position = await runtime.get_position("BTC-USD")
    positions = await runtime.get_positions()
    orders = await runtime.get_open_orders()
    balance = await runtime.get_balance()
    status = runtime.health_payload()
    print(json.dumps({
        "readonly": not status["execution_enabled"],
        "authenticated": bool(getattr(getattr(runtime.inner, "connector", None), "authenticated", False)),
        "worker_state": status["worker_state"],
        "position_side": position.side.value,
        "position_count": len(positions),
        "open_order_count": len(orders),
        "equity_readable": balance.equity > 0,
    }, separators=(",", ":")))

asyncio.run(main())
'@

$probeEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probe))
$probeCommand = "import base64;exec(base64.b64decode('$probeEncoded'))"

docker compose run --rm --no-deps `
    -e HYPERLIQUID_PERPETUAL_ADDRESS `
    -e HYPERLIQUID_PERPETUAL_SECRET_KEY `
    -e EXECUTION_MODE `
    -e EXECUTION_ENABLED `
    -e HUMMINGBOT_LIVE_CONNECTOR `
    execution-worker /opt/conda/envs/hummingbot/bin/python -c $probeCommand
