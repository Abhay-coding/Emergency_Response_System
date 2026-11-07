@echo off
REM Run Database Migrations on AWS ECS - Windows Version
REM Usage: migrate.bat [environment] [command]
REM Example: migrate.bat production upgrade
REM Example: migrate.bat staging "downgrade -1"

set PROJECT_NAME=emergency-response
set AWS_REGION=%AWS_REGION%
if "%AWS_REGION%"=="" set AWS_REGION=us-east-1
set ENVIRONMENT=%1
if "%ENVIRONMENT%"=="" set ENVIRONMENT=production
set MIGRATION_COMMAND=%2
if "%MIGRATION_COMMAND%"=="" set MIGRATION_COMMAND=upgrade head

set CLUSTER_NAME=%PROJECT_NAME%-%ENVIRONMENT%

for /f "tokens=*" %%a in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%a
set ECR_IMAGE_URI=%ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:latest

echo [INFO] Starting database migration for %PROJECT_NAME% (%ENVIRONMENT%)
echo [INFO] Command: alembic %MIGRATION_COMMAND%

REM Get network configuration from environment variables or prompt
if "%PRIVATE_SUBNETS%"=="" (
    set /p PRIVATE_SUBNETS="Enter private subnet IDs (comma-separated): "
)
if "%ECS_SECURITY_GROUPS%"=="" (
    set /p ECS_SECURITY_GROUPS="Enter ECS security group ID: "
)

echo [INFO] Using subnets: %PRIVATE_SUBNETS%
echo [INFO] Using security groups: %ECS_SECURITY_GROUPS%

REM Create migration override
echo {"containerOverrides":[{"name":"emergency-response-api","command":["python","-m","alembic"]}]} > migration-override.json

REM We need to add the command parts - use PowerShell for proper JSON
powershell -Command "
    $cmd = '%MIGRATION_COMMAND%'
    $parts = $cmd -split ' '
    $json = Get-Content 'migration-override.json' | ConvertFrom-Json
    $json.containerOverrides[0].command += $parts
    $json | ConvertTo-Json -Depth 10 | Set-Content 'migration-override.json'
"

echo [STEP] Running migration task...

for /f "tokens=*" %%a in ('aws ecs run-task --cluster %CLUSTER_NAME% --task-definition %PROJECT_NAME%-api --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[%PRIVATE_SUBNETS%],securityGroups=[%ECS_SECURITY_GROUPS%],assignPublicIp=DISABLED}" --overrides file://migration-override.json --region %AWS_REGION% --query "tasks[0].taskArn" --output text') do set TASK_ARN=%%a

if "%TASK_ARN%"=="" (
    echo [ERROR] Failed to start migration task
    exit /b 1
)

echo [INFO] Migration task started: %TASK_ARN%
echo [INFO] Waiting for migration task to complete...

:WAIT_LOOP
timeout /t 10 /nobreak >nul
for /f "tokens=*" %%a in ('aws ecs describe-tasks --cluster %CLUSTER_NAME% --tasks %TASK_ARN% --region %AWS_REGION% --query "tasks[0].lastStatus" --output text') do set TASK_STATUS=%%a

if "%TASK_STATUS%"=="STOPPED" (
    for /f "tokens=*" %%a in ('aws ecs describe-tasks --cluster %CLUSTER_NAME% --tasks %TASK_ARN% --region %AWS_REGION% --query "tasks[0].containers[0].exitCode" --output text') do set EXIT_CODE=%%a
    if "%EXIT_CODE%"=="0" (
        echo [INFO] Migration completed successfully!
        REM Get logs
        for /f "tokens=*" %%a in ('aws ecs describe-tasks --cluster %CLUSTER_NAME% --tasks %TASK_ARN% --region %AWS_REGION% --query "tasks[0].taskArn" --output text') do set TASK_ID=%%a
        for /f "tokens=*" %%b in ('echo %TASK_ID%') do set TASK_ID_SHORT=%%b
        set TASK_ID_SHORT=%TASK_ID_SHORT:*-=%
        aws logs get-log-events --log-group-name "/ecs/emergency-response-api-%ENVIRONMENT%" --log-stream-name "ecs/emergency-response-api/%TASK_ID_SHORT%" --region %AWS_REGION% --query "events[*].message" --output text 2>nul
        exit /b 0
    ) else (
        echo [ERROR] Migration failed with exit code: %EXIT_CODE%
        exit /b 1
    )
) else if "%TASK_STATUS%"=="RUNNING" (
    echo [INFO] Task is running...
    goto WAIT_LOOP
) else if "%TASK_STATUS%"=="PENDING" (
    echo [INFO] Task is pending...
    goto WAIT_LOOP
) else (
    echo [WARN] Task status: %TASK_STATUS%
    goto WAIT_LOOP
)