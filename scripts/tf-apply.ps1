<#
.SYNOPSIS
Run terraform apply with the deployment's secrets rehydrated from SSM.

.DESCRIPTION
Two Terraform variables carry live credentials and both default to "":

    ai_api_key     -> TRANSFEROPS_AI_API_KEY on the API, assistant and refresh
                      functions, and /<prefix>-<env>/ai-api-key
    smtp_password  -> Keycloak's SES relay password, and
                      /<prefix>-<env>/smtp-password

An empty value is indistinguishable from "the operator does not want this
feature", so a plain `terraform apply` in a shell that has not exported them
destroys the SSM parameter and drops the setting from every consumer. Nothing
fails: the AI panels start reporting no key, and Keycloak stops sending mail.
The cause is invisible because the apply succeeded.

This wrapper reads whatever is already in SSM and exports it before calling
Terraform, so re-applying preserves what is deployed. An explicitly exported
TF_VAR_ always wins, which is how a rotation is performed:

    $env:TF_VAR_ai_api_key = "<new-model-provider-key>"; .\scripts\tf-apply.ps1

Any extra arguments are passed through to terraform, so `-target=...` and
friends still work.
#>
[CmdletBinding()]
param(
  [string]$Region = $(if ($env:TF_VAR_region) { $env:TF_VAR_region } else { 'eu-central-1' }),
  [string]$Prefix = $(if ($env:TF_VAR_prefix) { $env:TF_VAR_prefix } else { 'ti' }),
  [string]$Environment = $(if ($env:TF_VAR_environment) { $env:TF_VAR_environment } else { 'student' }),
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$TerraformArgs
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root 'infrastructure/aws'

foreach ($tool in 'aws', 'terraform') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required and is not on PATH." }
}

$ParameterPath = "/$Prefix-$Environment"

# Read one SecureString, returning '' when it does not exist. A missing
# parameter is a legitimate "never configured", not a failure.
function Get-Secret([string]$Name) {
  $value = aws ssm get-parameter --region $Region --name "$ParameterPath/$Name" --with-decryption --query 'Parameter.Value' --output text 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $value) { return '' }
  return $value.Trim()
}

function Restore-Var([string]$VarName, [string]$ParameterName, [string]$Description) {
  $envName = "TF_VAR_$VarName"
  if ([Environment]::GetEnvironmentVariable($envName)) {
    Write-Host "  $VarName : using the value already exported (rotation)"
    return
  }
  $value = Get-Secret $ParameterName
  if ($value) {
    [Environment]::SetEnvironmentVariable($envName, $value)
    Write-Host "  $VarName : restored from $ParameterPath/$ParameterName"
  }
  else {
    Write-Warning "  $VarName : not in SSM and not exported -- $Description stays disabled"
  }
}

Write-Host "`n==> Rehydrating secrets from SSM"
Restore-Var 'ai_api_key'    'ai-api-key'    'the AI layer'
Restore-Var 'smtp_password' 'smtp-password' 'Keycloak outbound mail'

Write-Host "`n==> terraform apply"
$arguments = @(
  "-chdir=$App", 'apply', '-input=false',
  "-var=region=$Region", "-var=prefix=$Prefix", "-var=environment=$Environment"
) + $TerraformArgs
& terraform @arguments
if ($LASTEXITCODE -ne 0) { throw "terraform apply failed with exit code $LASTEXITCODE." }
