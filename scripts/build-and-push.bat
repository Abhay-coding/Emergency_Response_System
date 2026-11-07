@echo off
REM Build and Push Docker Image to ECR - Windows Version
REM Usage: build-and-push.bat [environment] [tag]
REM Example: build-and-push.bat production latest

set PROJECT_NAME=emergency-response
set AWS_REGION=%AWS_REGION%
if "%AWS_REGION%"=="" set AWS_REGION=us-east-1
set ENVIRONMENT=%1
if "%ENVIRONMENT%"=="" set ENVIRONMENT=production
set IMAGE_TAG=%2
if "%IMAGE_TAG%"=="" set IMAGE_TAG=latest

echo [INFO] Starting build and push for %PROJECT_NAME% (%ENVIRONMENT%)
echo [INFO] Image tag: %IMAGE_TAG%

REM Check prerequisites
where docker >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker is not installed or not in PATH
    exit /b 1
)

where aws >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] AWS CLI is not installed or not in PATH
    exit /b 1
)

REM Get AWS Account ID
for /f "tokens=*" %%a in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%a
echo [INFO] AWS Account ID: %ACCOUNT_ID%

REM Login to ECR
echo [INFO] Logging into ECR...
aws ecr get-login-password --region %AWS_REGION% | docker login --username AWS --password-stdin %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] ECR login failed
    exit /b 1
)

REM Build Docker image
echo [INFO] Building Docker image...
docker build --target production -t %PROJECT_NAME%-api:%IMAGE_TAG% -t %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:%IMAGE_TAG% -f Dockerfile .
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker build failed
    exit /b 1
)

REM Push to ECR
echo [INFO] Pushing image to ECR...
docker push %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:%IMAGE_TAG%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker push failed
    exit /b 1
)

REM Tag as latest if not already
if not "%IMAGE_TAG%"=="latest" (
    echo [INFO] Tagging as latest...
    docker tag %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:%IMAGE_TAG% %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:latest
    docker push %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:latest
)

echo [INFO] Build and push completed successfully!
echo [INFO] Image URI: %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%PROJECT_NAME%-api:%IMAGE_TAG%