@echo off
REM Deploy ECS Services - Windows Version
REM Usage: deploy.bat [environment] [image-tag]
REM Example: deploy.bat production latest

set PROJECT_NAME=emergency-response
set AWS_REGION=%AWS_REGION%
if "%AWS_REGION%"=="" set AWS_REGION=us-east-1
set ENVIRONMENT=%1
if "%ENVIRONMENT%"=="" set ENVIRONMENT=production
set IMAGE_TAG=%2
if "%IMAGE_TAG%"=="" set IMAGE_TAG=latest

set CLUSTER_NAME=%PROJECT_NAME%-%ENVIRONMENT%
set API_SERVICE_NAME=%PROJECT_NAME%-api
set WORKER_SERVICE_NAME=%PROJECT_NAME%-worker
set API_TASK_FAMILY=%PROJECT_NAME%-api
set WORKER_TASK_FAMILY=%PROJECT_NAME%-worker

for /f "tokens=*" %%a in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%a
set ECR_IMAGE_URI=%ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:%IMAGE_TAG%

echo [INFO] Starting deployment for %PROJECT_NAME% (%ENVIRONMENT%)
echo [INFO] Image: %ECR_IMAGE_URI%
echo [INFO] Cluster: %CLUSTER_NAME%

REM Check cluster exists
aws ecs describe-clusters --clusters %CLUSTER_NAME% --region %AWS_REGION% --query "clusters[0].status" --output text | findstr "ACTIVE" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Cluster %CLUSTER_NAME% does not exist or is not active
    echo [INFO] Run terraform apply first to create infrastructure
    exit /b 1
)

REM Deploy API service
echo [STEP] Deploying %API_SERVICE_NAME%...

REM Update task definition template
powershell -Command "
    $content = Get-Content '..\ecs-task-definition.json.template' -Raw
    $content = $content -replace '\$\{ACCOUNT_ID\}', '%ACCOUNT_ID%'
    $content = $content -replace '\$\{AWS_REGION\}', '%AWS_REGION%'
    $content = $content -replace '\$\{IMAGE_TAG\}', '%IMAGE_TAG%'
    $content = $content -replace '\$\{ECR_IMAGE_URI\}', '%ECR_IMAGE_URI%'
    $content = $content -replace '\$\{ENVIRONMENT\}', '%ENVIRONMENT%'
    $content = $content -replace '\$\{REDIS_HOST\}', '%REDIS_HOST%'
    $content = $content -replace '\$\{CORS_ORIGINS\}', '%CORS_ORIGINS%'
    $content = $content -replace '\$\{SQS_QUEUE_URL\}', '%SQS_QUEUE_URL%'
    $content = $content -replace '\$\{CAMPUS_EMERGENCY_PHONE\}', '%CAMPUS_EMERGENCY_PHONE%'
    $content = $content -replace '\$\{BACKUP_PHONE\}', '%BACKUP_PHONE%'
    $content = $content -replace '\$\{EFS_FILE_SYSTEM_ID\}', '%EFS_FILE_SYSTEM_ID%'
    $content = $content -replace '\$\{EFS_ACCESS_POINT_ID\}', '%EFS_ACCESS_POINT_ID%'
    Set-Content -Path '..\ecs-task-definition-generated.json' -Value $content
"

for /f "tokens=*" %%a in ('aws ecs register-task-definition --cli-input-json file://..\ecs-task-definition-generated.json --region %AWS_REGION% --query "taskDefinition.taskDefinitionArn" --output text') do set API_TASK_DEF_ARN=%%a
echo [INFO] Registered API task definition: %API_TASK_DEF_ARN%

aws ecs update-service --cluster %CLUSTER_NAME% --service %API_SERVICE_NAME% --task-definition %API_TASK_DEF_ARN% --desired-count 2 --force-new-deployment --region %AWS_REGION% --output json >nul

REM Deploy Worker service
echo [STEP] Deploying %WORKER_SERVICE_NAME%...

powershell -Command "
    $content = Get-Content '..\ecs-worker-task-definition.json.template' -Raw
    $content = $content -replace '\$\{ACCOUNT_ID\}', '%ACCOUNT_ID%'
    $content = $content -replace '\$\{AWS_REGION\}', '%AWS_REGION%'
    $content = $content -replace '\$\{IMAGE_TAG\}', '%IMAGE_TAG%'
    $content = $content -replace '\$\{ECR_IMAGE_URI\}', '%ECR_IMAGE_URI%'
    $content = $content -replace '\$\{ENVIRONMENT\}', '%ENVIRONMENT%'
    $content = $content -replace '\$\{SQS_QUEUE_URL\}', '%SQS_QUEUE_URL%'
    $content = $content -replace '\$\{CAMPUS_EMERGENCY_PHONE\}', '%CAMPUS_EMERGENCY_PHONE%'
    $content = $content -replace '\$\{BACKUP_PHONE\}', '%BACKUP_PHONE%'
    Set-Content -Path '..\ecs-worker-task-definition-generated.json' -Value $content
"

for /f "tokens=*" %%a in ('aws ecs register-task-definition --cli-input-json file://..\ecs-worker-task-definition-generated.json --region %AWS_REGION% --query "taskDefinition.taskDefinitionArn" --output text') do set WORKER_TASK_DEF_ARN=%%a
echo [INFO] Registered Worker task definition: %WORKER_TASK_DEF_ARN%

aws ecs update-service --cluster %CLUSTER_NAME% --service %WORKER_SERVICE_NAME% --task-definition %WORKER_TASK_DEF_ARN% --desired-count 1 --force-new-deployment --region %AWS_REGION% --output json >nul

REM Wait for deployments
echo [INFO] Waiting for deployments to stabilize...

aws ecs wait services-stable --cluster %CLUSTER_NAME% --services %API_SERVICE_NAME% --region %AWS_REGION%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] API service deployment failed or timed out
    exit /b 1
)

aws ecs wait services-stable --cluster %CLUSTER_NAME% --services %WORKER_SERVICE_NAME% --region %AWS_REGION%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Worker service deployment failed or timed out
    exit /b 1
)

echo [INFO] All deployments completed successfully!