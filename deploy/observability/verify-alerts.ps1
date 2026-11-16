# Validate observability alert rules / configs without a full stack.
# Usage (from deploy/):
#   powershell -File .\observability\verify-alerts.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Obs = Join-Path $Root "observability"
$PromImage = if ($env:PROM_IMAGE) { $env:PROM_IMAGE } else { "prom/prometheus:v3.2.1" }
$AmImage = if ($env:AM_IMAGE) { $env:AM_IMAGE } else { "prom/alertmanager:v0.28.1" }
$ComposeFile = if ($env:COMPOSE_FILE) { $env:COMPOSE_FILE } else { Join-Path $Root "docker-compose.prod.yml" }
$WebhookUrl = if ($env:ALERTMANAGER_WEBHOOK_URL) { $env:ALERTMANAGER_WEBHOOK_URL } else { "http://127.0.0.1:9/" }

Write-Host "== D2 verify-alerts =="
Write-Host "root=$Root"
Write-Host "prom_image=$PromImage"
Write-Host "am_image=$AmImage"

Write-Host ""
Write-Host "-- 1) compose file declares observability profile services"
$composeText = Get-Content $ComposeFile -Raw
foreach ($svc in @("prometheus:", "alertmanager:", "grafana:", "otel-collector:", "jaeger:", "node-exporter:")) {
  if ($composeText -notmatch [regex]::Escape($svc)) {
    throw "service key '$svc' missing from $ComposeFile"
  }
}
if ($composeText -notmatch 'profiles:\s*\[["'']observability["'']\]') {
  throw "observability profile marker missing from $ComposeFile"
}
# Prefer full interpolate when env file exists; otherwise YAML presence is enough for D2 gate.
$envFile = Join-Path $Root ".env.prod"
if (-not (Test-Path $envFile)) { $envFile = Join-Path $Root ".env.prod.example" }
if (Test-Path $envFile) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $cfg = docker compose --env-file $envFile -f $ComposeFile --profile observability config 2>&1 | Out-String
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  if ($code -eq 0) {
    if ($cfg -notmatch "(?m)^  prometheus:") { throw "prometheus missing after compose config" }
    Write-Host "OK compose config interpolated ($envFile)"
  } else {
    $first = ($cfg -split "`r?`n" | Select-Object -First 1)
    Write-Host "WARN compose config skipped (env incomplete): $first"
    Write-Host "OK compose YAML declares observability services"
  }
} else {
  Write-Host "OK compose YAML declares observability services"
}

function Invoke-DockerChecked([string[]]$DockerArgs) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & docker @DockerArgs
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  if ($code -ne 0) { throw "docker $($DockerArgs -join ' ') failed with exit $code" }
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $Content, $utf8)
}

Write-Host ""
Write-Host "-- 2) promtool check rules"
$alertsHost = Join-Path $Obs "alerts.yml"
Invoke-DockerChecked @(
  "run", "--rm",
  "-v", "${alertsHost}:/etc/prometheus/alerts.yml:ro",
  "--entrypoint", "promtool",
  $PromImage, "check", "rules", "/etc/prometheus/alerts.yml"
)
$alertCount = (Select-String -Path $alertsHost -Pattern '^\s*- alert:' | Measure-Object).Count
if ($alertCount -lt 1) { throw "expected alert rules in alerts.yml" }
Write-Host "OK rules loaded (alert count=$alertCount)"

Write-Host ""
Write-Host "-- 3) promtool check config"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ekb-alert-verify-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  Copy-Item (Join-Path $Obs "alerts.yml") (Join-Path $tmp "alerts.yml")
  $prom = Get-Content (Join-Path $Obs "prometheus.yml") -Raw
  $prom = $prom.Replace("/etc/prometheus/alerts.yml", "/work/alerts.yml")
  $prom = $prom.Replace("/etc/prometheus/metrics-token", "/work/metrics-token")
  Write-Utf8NoBom (Join-Path $tmp "prometheus.yml") $prom
  Write-Utf8NoBom (Join-Path $tmp "metrics-token") "drill-token`n"
  Invoke-DockerChecked @(
    "run", "--rm",
    "-v", "${tmp}:/work:ro",
    "--entrypoint", "promtool",
    $PromImage, "check", "config", "/work/prometheus.yml"
  )
  Write-Host "OK prometheus config"

  Write-Host ""
  Write-Host "-- 4) amtool check-config (rendered webhook)"
  $tmpl = Get-Content (Join-Path $Obs "alertmanager.yml.tmpl") -Raw
  $rendered = $tmpl.Replace("__WEBHOOK_URL__", $WebhookUrl)
  $amPath = Join-Path $tmp "alertmanager.yml"
  Write-Utf8NoBom $amPath $rendered
  Invoke-DockerChecked @(
    "run", "--rm",
    "-v", "${amPath}:/tmp/alertmanager.yml:ro",
    "--entrypoint", "amtool",
    $AmImage, "check-config", "/tmp/alertmanager.yml"
  )
  Write-Host "OK alertmanager config (webhook=$WebhookUrl)"
}
finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "SUCCESS verify-alerts"
Write-Host "ALERT_COUNT=$alertCount"
