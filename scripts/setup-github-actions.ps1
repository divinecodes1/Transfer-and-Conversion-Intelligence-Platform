# ============================================================================
# Transfer & Conversion Intelligence Platform :: wire GitHub Actions to AWS.
#
#   .\scripts\setup-github-actions.ps1
#
# The Windows equivalent of setup-github-actions.sh. Reads the deployed stack
# from `terraform output` and pushes every secret and variable the workflows
# need, so nothing is copied by hand.
#
# THE ROLE ALREADY EXISTS. Terraform creates the IAM OIDC provider and the
# deployment role (infrastructure/aws/github_oidc.tf), because on AWS both live
# inside the account and need no administrator beyond the one deploying. That is
# the difference from the Azure attempt, which ended here: federated login there
# needed an Entra app registration and the university tenant set
# allowedToCreateApps=false.
#
# No access key is created. GitHub mints a short-lived OIDC token scoped to this
# repository and the production-demo environment.
# ============================================================================
[CmdletBinding()]
param(
  # Re-granted after a warehouse reload, which otherwise leaves the account
  # correctly enforcing an empty scope.
  [string]$Operator = $env:TRANSFEROPS_OPERATOR
)

$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
  $PSNativeCommandUseErrorActionPreference = $true
}

$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root 'infrastructure/aws'

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "    $m" -ForegroundColor Gray }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }

# ---- 1. Prerequisites -------------------------------------------------------
Step 'Checking prerequisites'
foreach ($tool in 'aws', 'gh', 'terraform') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "$tool is required and is not on PATH."
  }
}
aws sts get-caller-identity | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Not authenticated to AWS.' }
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Not logged in to GitHub. Run: gh auth login' }

$GhRepo = (gh repo view --json nameWithOwner -q .nameWithOwner).Trim()
Info "Repository $GhRepo"

# ---- 2. Read the deployment -------------------------------------------------
Step 'Reading terraform outputs'
if (-not (Test-Path (Join-Path $App '.terraform'))) {
  throw 'Terraform is not initialised in infrastructure/aws. Deploy first with scripts/deploy-aws-student.ps1.'
}

# `terraform output` exits non-zero for an output that does not exist, which is
# a legitimate "not set" here rather than a failure.
function Get-Output([string]$Name) {
  $value = terraform "-chdir=$App" output -raw $Name 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return $value.Trim()
}

$RoleArn = Get-Output 'github_actions_role_arn'
$Region = Get-Output 'region'
$ApiUrl = Get-Output 'api_url'
$AssistantUrl = Get-Output 'assistant_url'
$ConsoleUrl = Get-Output 'console_url'
$KeycloakUrl = Get-Output 'keycloak_url'
$ConsoleBucket = Get-Output 'console_bucket'
$DistributionId = Get-Output 'cloudfront_distribution_id'
$ApiFunction = Get-Output 'api_function_name'
$RefreshFunction = Get-Output 'refresh_function_name'
$AssistantFunction = Get-Output 'assistant_function_name'
$KeycloakInstance = Get-Output 'keycloak_instance_id'
$RolloutDocument = Get-Output 'keycloak_rollout_document'
$SeedDocument = Get-Output 'warehouse_seed_document'

# Repository NAMES, not URLs: amazon-ecr-login supplies the registry host.
$ApiRepository = (Get-Output 'ecr_api_repository').Split('/')[-1]
$KeycloakRepository = (Get-Output 'ecr_keycloak_repository').Split('/')[-1]

if (-not $RoleArn) {
  Warn 'No github_actions_role_arn output.'
  Warn 'Set github_repository in infrastructure/aws/terraform.tfvars and re-apply:'
  Warn "  github_repository = `"$GhRepo`""
  throw 'Cannot wire CI without the role.'
}

Info "Role   $RoleArn"
Info "Region $Region"

# ---- 3. Secrets -------------------------------------------------------------
Step 'GitHub secrets'
function Set-Secret([string]$Name, [string]$Value) {
  if (-not $Value) { Warn "skip    $Name (no value)"; return }
  # --body rather than a pipe: PowerShell appends a newline to piped strings,
  # and a secret with a trailing newline fails in ways that are hard to see.
  gh secret set $Name --repo $GhRepo --body $Value | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to set secret $Name." }
  Info "set     $Name"
}

# The role ARN is not a credential -- it names a role, and only a token from
# this repository can assume it. It is a secret purely to keep the account id
# out of public logs.
Set-Secret 'AWS_ROLE_ARN'                   $RoleArn
Set-Secret 'AWS_ECR_API_REPOSITORY'         $ApiRepository
Set-Secret 'AWS_ECR_KEYCLOAK_REPOSITORY'    $KeycloakRepository
Set-Secret 'AWS_API_FUNCTION'               $ApiFunction
Set-Secret 'AWS_REFRESH_FUNCTION'           $RefreshFunction
Set-Secret 'AWS_ASSISTANT_FUNCTION'         $AssistantFunction
Set-Secret 'AWS_KEYCLOAK_INSTANCE'          $KeycloakInstance
Set-Secret 'AWS_KEYCLOAK_ROLLOUT_DOCUMENT'  $RolloutDocument
# RDS is private, so CI loads the warehouse by running this fixed document on
# the in-VPC host. Without it a schema change never reaches the deployment.
Set-Secret 'AWS_WAREHOUSE_SEED_DOCUMENT'    $SeedDocument
Set-Secret 'AWS_CONSOLE_BUCKET'             $ConsoleBucket
Set-Secret 'AWS_CLOUDFRONT_DISTRIBUTION_ID' $DistributionId

# ---- 4. Variables -----------------------------------------------------------
Step 'GitHub variables (public; VITE_* compile into the browser bundle)'
function Set-Var([string]$Name, [string]$Value) {
  if (-not $Value) { Warn "skip    $Name (no value)"; return }
  gh variable set $Name --repo $GhRepo --body $Value | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to set variable $Name." }
  Info "set     $Name = $Value"
}

Set-Var 'AWS_REGION'        $Region
Set-Var 'AWS_API_URL'       $ApiUrl
Set-Var 'AWS_ASSISTANT_URL' $AssistantUrl
Set-Var 'AWS_CONSOLE_URL'   $ConsoleUrl
Set-Var 'AWS_KEYCLOAK_URL'  $KeycloakUrl

# Compiled into the bundle and therefore PUBLIC. Only values safe to publish
# appear here; tests/web_checks.py asserts the built console holds no key.
Set-Var 'VITE_TRANSFEROPS_API'    $ApiUrl
Set-Var 'VITE_TRANSFEROPS_AGENT'  $AssistantUrl
Set-Var 'VITE_KEYCLOAK_URL'       $KeycloakUrl
Set-Var 'VITE_KEYCLOAK_REALM'     'transferops'
Set-Var 'VITE_KEYCLOAK_CLIENT_ID' 'transferops-api'
Set-Var 'VITE_TRANSFEROPS_AUTH'   'oidc'

# The switch the deploy jobs read. A repository VARIABLE, not a secret: a
# job-level `if:` cannot see the secrets context, so a secret could never gate a
# job even though it looks like it should.
Set-Var 'AWS_DEPLOY_ENABLED' 'true'

if ($Operator) {
  Set-Var 'TRANSFEROPS_OPERATOR' $Operator
} else {
  Warn 'skip    TRANSFEROPS_OPERATOR (set it to keep your account entitled across a warehouse reload)'
}

# ---- 5. Summary -------------------------------------------------------------
Step 'Done'
Write-Host @"

  CI assumes        $RoleArn
  Authentication    federated OIDC -- NO access key exists
  Scoped to         repo:${GhRepo}:environment:production-demo
                    repo:${GhRepo}:ref:refs/heads/main

  Create the environment the deploy jobs declare, if it does not exist:
    GitHub -> Settings -> Environments -> New environment -> production-demo

  Verify:
    gh secret list --repo $GhRepo
    gh variable list --repo $GhRepo

  Deploy everything, in order, and verify all three tiers:
    gh workflow run deploy.yml

  Force a warehouse reload with it:
    gh workflow run deploy.yml -f seed_warehouse=true

"@
