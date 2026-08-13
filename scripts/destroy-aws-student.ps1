[CmdletBinding()]
param(
  [string]$Region = $(if ($env:TF_VAR_region) { $env:TF_VAR_region } else { 'eu-central-1' }),
  [string]$Prefix = $(if ($env:TF_VAR_prefix) { $env:TF_VAR_prefix } else { 'ti' }),
  [string]$Environment = $(if ($env:TF_VAR_environment) { $env:TF_VAR_environment } else { 'student' })
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root 'infrastructure/aws'
$Boot = Join-Path $App 'bootstrap'

foreach ($tool in 'aws','terraform') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required." }
}
$Account = aws sts get-caller-identity --query Account --output text
Write-Warning "This permanently deletes the application, private RDS databases, Keycloak users, buckets, and ECR images in account $Account."
$confirmation = Read-Host "Type destroy to confirm"
if ($confirmation -cne 'destroy') { throw 'Not confirmed. Nothing was deleted.' }

terraform "-chdir=$App" init -input=false
terraform "-chdir=$App" destroy -input=false -auto-approve -var="region=$Region" -var="prefix=$Prefix" -var="environment=$Environment"
if ((Test-Path (Join-Path $Boot '.terraform')) -or (Test-Path (Join-Path $Boot 'terraform.tfstate'))) {
  terraform "-chdir=$Boot" init -input=false
  terraform "-chdir=$Boot" destroy -input=false -auto-approve -var="region=$Region" -var="prefix=$Prefix" -var="environment=$Environment"
}
Write-Host 'Application and ECR bootstrap states were destroyed in dependency order.'
