[CmdletBinding()]
param(
  [string]$Operator = $env:TRANSFEROPS_OPERATOR,
  [string]$Region = $(if ($env:TF_VAR_region) { $env:TF_VAR_region } else { 'eu-central-1' }),
  [string]$Prefix = $(if ($env:TF_VAR_prefix) { $env:TF_VAR_prefix } else { 'ti' }),
  [string]$Environment = $(if ($env:TF_VAR_environment) { $env:TF_VAR_environment } else { 'student' })
)
$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
  $PSNativeCommandUseErrorActionPreference = $true
}
$Root = Split-Path -Parent $PSScriptRoot
$Boot = Join-Path $Root 'infrastructure/aws/bootstrap'
$App = Join-Path $Root 'infrastructure/aws'

foreach ($tool in 'aws','terraform','docker','node','npm.cmd') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required and is not on PATH." }
}
function Assert-Native([string]$Operation) {
  if ($LASTEXITCODE -ne 0) { throw "$Operation failed with exit code $LASTEXITCODE." }
}
aws sts get-caller-identity | Out-Null
Assert-Native 'AWS authentication'
docker info | Out-Null
Assert-Native 'Docker availability check'

Write-Host "`n==> Detecting the current AWS account plan"
try {
  $planJson = aws freetier get-account-plan-state --region us-east-1 --output json
  Assert-Native 'AWS Free Plan detection'
  $plan = $planJson | ConvertFrom-Json
  Write-Host "  Type: $($plan.accountPlanType)  Status: $($plan.accountPlanStatus)  Credits: $($plan.accountPlanRemainingCredits.amount) $($plan.accountPlanRemainingCredits.unit)  Expires: $($plan.accountPlanExpirationDate)"
  if (($plan.accountPlanType -ne 'FREE' -or $plan.accountPlanStatus -ne 'ACTIVE') -and $env:TRANSFEROPS_ALLOW_PAID -ne 'true') {
    throw 'Free Plan is not active. Set TRANSFEROPS_ALLOW_PAID=true only if paid deployment is intentional.'
  }
} catch {
  if ($_.Exception.Message -like 'Free Plan is not active*') { throw }
  Write-Warning 'The account-plan API was unavailable; verify Billing > Free Tier before deployment.'
}

Write-Host "`n==> Stage 1/2: ECR bootstrap"
terraform "-chdir=$Boot" init -input=false
Assert-Native 'Terraform bootstrap init'
terraform "-chdir=$Boot" apply -input=false -auto-approve -var="region=$Region" -var="prefix=$Prefix" -var="environment=$Environment"
Assert-Native 'Terraform bootstrap apply'
$Region = (terraform "-chdir=$Boot" output -raw region).Trim()
$ApiRepo = terraform "-chdir=$Boot" output -raw api_repository_url
$KcRepo = terraform "-chdir=$Boot" output -raw keycloak_repository_url

Write-Host "`n==> Building and pushing images"
# The pipe is handed to cmd rather than run in PowerShell: Windows PowerShell
# 5.1 re-encodes data crossing a native-to-native pipe, which corrupts the
# authorization token and ECR answers 400 Bad Request. cmd passes the bytes
# through unchanged. Harmless on PowerShell 7, where the pipe would also work.
$Registry = $ApiRepo.Split('/')[0]
cmd /c "aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $Registry"
Assert-Native 'ECR login'
docker build -t transfer-intelligence:base $Root
Assert-Native 'Base image build'
docker build -f (Join-Path $Root 'infrastructure/docker/lambda/Dockerfile') --build-arg BASE_IMAGE=transfer-intelligence:base -t "${ApiRepo}:latest" $Root
Assert-Native 'Lambda image build'
docker build -f (Join-Path $Root 'infrastructure/docker/keycloak/Dockerfile') -t "${KcRepo}:latest" $Root
Assert-Native 'Keycloak image build'
docker push "${ApiRepo}:latest"
Assert-Native 'Lambda image push'
docker push "${KcRepo}:latest"
Assert-Native 'Keycloak image push'

# The IAM OIDC provider and the CI deployment role are only created when
# github_repository is set -- and when it is not, nothing fails. The apply
# succeeds, the stack works, and CI simply has no role to assume, which is not
# discovered until setup-github-actions.ps1 cannot find one. Resolve it here.
Write-Host "`n==> Resolving the repository allowed to deploy from CI"
$TfvarsPath = Join-Path $App 'terraform.tfvars'
$TfvarsRepository = ''
if (Test-Path $TfvarsPath) {
  $match = Select-String -Path $TfvarsPath -Pattern '^\s*github_repository\s*=\s*"(.+)"\s*$' | Select-Object -First 1
  if ($match) { $TfvarsRepository = $match.Matches[0].Groups[1].Value }
}
if ($env:TF_VAR_github_repository) {
  Write-Host "  $($env:TF_VAR_github_repository) (from TF_VAR_github_repository)"
} elseif ($TfvarsRepository) {
  Write-Host "  $TfvarsRepository (from terraform.tfvars)"
} elseif (Get-Command gh -ErrorAction SilentlyContinue) {
  $detected = gh repo view --json nameWithOwner -q .nameWithOwner 2>$null
  if ($LASTEXITCODE -eq 0 -and $detected) {
    $env:TF_VAR_github_repository = $detected.Trim()
    Write-Host "  $($env:TF_VAR_github_repository) (detected with gh)"
  } else {
    Write-Warning 'github_repository is not set and gh is not authenticated. GitHub Actions will have no role to assume.'
  }
} else {
  Write-Warning "github_repository is not set. The stack will deploy, but GitHub Actions will have no role to assume. Add github_repository = `"owner/name`" to $TfvarsPath and re-run."
}

Write-Host "`n==> Stage 2/2: application resources"
terraform "-chdir=$App" init -input=false
Assert-Native 'Terraform application init'
terraform "-chdir=$App" apply -input=false -auto-approve -var="region=$Region" -var="prefix=$Prefix" -var="environment=$Environment"
Assert-Native 'Terraform application apply'
$ApiUrl = terraform "-chdir=$App" output -raw api_url
$AgentUrl = terraform "-chdir=$App" output -raw assistant_url
$KcUrl = terraform "-chdir=$App" output -raw keycloak_url
$Instance = terraform "-chdir=$App" output -raw keycloak_instance_id
$RolloutDoc = terraform "-chdir=$App" output -raw keycloak_rollout_document
$SeedDoc = terraform "-chdir=$App" output -raw warehouse_seed_document

Write-Host "`n==> Waiting for SSM"
for ($i=0; $i -lt 60; $i++) {
  $status = aws ssm describe-instance-information --region $Region --filters "Key=InstanceIds,Values=$Instance" --query 'InstanceInformationList[0].PingStatus' --output text 2>$null
  if ($status -eq 'Online') { break }
  if ($i -eq 59) { throw "SSM did not report $Instance online." }
  Start-Sleep -Seconds 10
}
function Invoke-SsmDocument([string]$Document,[string]$Parameters) {
  $id = aws ssm send-command --region $Region --instance-ids $Instance --document-name $Document --parameters $Parameters --query 'Command.CommandId' --output text
  Assert-Native "SSM send-command ($Document)"
  aws ssm wait command-executed --region $Region --command-id $id --instance-id $Instance
  Assert-Native "SSM command wait ($Document)"
  aws ssm get-command-invocation --region $Region --command-id $id --instance-id $Instance --query '{Status:Status,Output:StandardOutputContent}' --output table
}
Invoke-SsmDocument $RolloutDoc "ImageUri=${KcRepo}:latest,PublicUrl=$KcUrl"
$seedParameters = "ImageUri=${ApiRepo}:latest"
if ($Operator) { $seedParameters += ",Operator=$Operator" }
Invoke-SsmDocument $SeedDoc $seedParameters

Write-Host "`n==> Building and publishing the console"
$Bucket = terraform "-chdir=$App" output -raw console_bucket
$Distribution = terraform "-chdir=$App" output -raw cloudfront_distribution_id
$ConsoleUrl = terraform "-chdir=$App" output -raw console_url
Push-Location (Join-Path $Root 'web')
try {
  $env:VITE_TRANSFEROPS_API = $ApiUrl
  $env:VITE_TRANSFEROPS_AGENT = $AgentUrl
  $env:VITE_KEYCLOAK_URL = $KcUrl
  $env:VITE_KEYCLOAK_REALM = 'transferops'
  $env:VITE_KEYCLOAK_CLIENT_ID = 'transferops-api'
  $env:VITE_TRANSFEROPS_AUTH = 'enforce'
  npm.cmd ci
  Assert-Native 'npm install'
  npm.cmd run build
  Assert-Native 'console build'
} finally { Pop-Location }
aws s3 sync (Join-Path $Root 'web/dist') "s3://$Bucket" --delete --exclude index.html --cache-control 'public,max-age=31536000,immutable'
Assert-Native 'console asset upload'
aws s3 cp (Join-Path $Root 'web/dist/index.html') "s3://$Bucket/index.html" --cache-control 'no-cache,must-revalidate'
Assert-Native 'console index upload'
aws cloudfront create-invalidation --distribution-id $Distribution --paths '/*' | Out-Null
Assert-Native 'CloudFront invalidation'

Write-Host "`nDeployment complete"
Write-Host "Console:   $ConsoleUrl`nAPI:       $ApiUrl`nAssistant: $AgentUrl`nKeycloak:  $KcUrl"
terraform "-chdir=$App" output -raw cost_posture
Assert-Native 'Terraform output'

# This script exists to create the stack once. Every deployment after this one
# should come from CI, which needs the outputs above published to the
# repository -- that is the next command, and it is not optional if you want
# `git push` to deploy.
Write-Host "`n`nHand the deployment over to GitHub Actions:"
Write-Host "  .\scripts\setup-github-actions.ps1"
Write-Host "  gh workflow run deploy.yml`n"
