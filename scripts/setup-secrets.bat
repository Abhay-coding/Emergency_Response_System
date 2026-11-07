@echo off
REM Setup Secrets in AWS Secrets Manager - Windows Version
REM Usage: setup-secrets.bat [environment]
REM Example: setup-secrets.bat production

set PROJECT_NAME=emergency-response
set AWS_REGION=%AWS_REGION%
if "%AWS_REGION%"=="" set AWS_REGION=us-east-1
set ENVIRONMENT=%1
if "%ENVIRONMENT%"=="" set ENVIRONMENT=production

for /f "tokens=*" %%a in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%a

set JWT_SECRET_NAME=emergency-response/jwt-secret
set DATABASE_URL_NAME=emergency-response/database-url
set REDIS_URL_NAME=emergency-response/redis-url

echo [INFO] Setting up secrets for %PROJECT_NAME% (%ENVIRONMENT%)

REM JWT Secret
echo [STEP] Configuring JWT Secret...
aws secretsmanager describe-secret --secret-id %JWT_SECRET_NAME% --region %AWS_REGION% >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] JWT secret already exists. Regenerate? (y/N)
    set /p REGENERATE_JWT=
    if /i "%REGENERATE_JWT%"=="y" (
        for /f "tokens=*" %%a in ('openssl rand -hex 32') do set JWT_SECRET=%%a
        aws secretsmanager put-secret-value --secret-id %JWT_SECRET_NAME% --secret-string "%JWT_SECRET%" --region %AWS_REGION% >nul
        echo [INFO] JWT secret regenerated
    ) else (
        echo [INFO] Keeping existing JWT secret
    )
) else (
    for /f "tokens=*" %%a in ('openssl rand -hex 32') do set JWT_SECRET=%%a
    aws secretsmanager create-secret --name %JWT_SECRET_NAME% --description "JWT signing secret for emergency-response application" --secret-string "%JWT_SECRET%" --region %AWS_REGION% >nul
    echo [INFO] JWT secret created
)

REM Database URL
echo [STEP] Configuring Database URL...
if exist "..\terraform\terraform.tfstate" (
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw rds_endpoint 2^>nul') do set RDS_ENDPOINT=%%a
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw db_password 2^>nul') do set DB_PASSWORD=%%a
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw db_name 2^>nul') do set DB_NAME=%%a
    if "%DB_NAME%"=="" set DB_NAME=emergency
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw db_username 2^>nul') do set DB_USERNAME=%%a
    if "%DB_USERNAME%"=="" set DB_USERNAME=admin

    if defined RDS_ENDPOINT if defined DB_PASSWORD (
        set DATABASE_URL=postgresql+psycopg://%DB_USERNAME%:%DB_PASSWORD%@%RDS_ENDPOINT%/%DB_NAME%
        echo [INFO] Database URL auto-detected from Terraform
    )
)

if not defined DATABASE_URL (
    echo [WARN] Could not get database URL from Terraform. Please enter manually:
    set /p RDS_ENDPOINT="RDS Endpoint (e.g., db.xxxxx.us-east-1.rds.amazonaws.com): "
    set /p DB_NAME="Database name [emergency]: "
    if "%DB_NAME%"=="" set DB_NAME=emergency
    set /p DB_USERNAME="Database username [admin]: "
    if "%DB_USERNAME%"=="" set DB_USERNAME=admin
    echo Enter database password:
    powershell -Command "$pw = Read-Host -AsSecureString; [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))" > tmp_pwd.txt
    set /p DB_PASSWORD=<tmp_pwd.txt
    del tmp_pwd.txt
    echo.
    set DATABASE_URL=postgresql+psycopg://%DB_USERNAME%:%DB_PASSWORD%@%RDS_ENDPOINT%/%DB_NAME%
)

aws secretsmanager describe-secret --secret-id %DATABASE_URL_NAME% --region %AWS_REGION% >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    aws secretsmanager put-secret-value --secret-id %DATABASE_URL_NAME% --secret-string "%DATABASE_URL%" --region %AWS_REGION% >nul
) else (
    aws secretsmanager create-secret --name %DATABASE_URL_NAME% --description "PostgreSQL database connection URL" --secret-string "%DATABASE_URL%" --region %AWS_REGION% >nul
)
echo [INFO] Database URL configured

REM Redis URL
echo [STEP] Configuring Redis URL...
if exist "..\terraform\terraform.tfstate" (
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw redis_primary_endpoint 2^>nul') do set REDIS_ENDPOINT=%%a
    for /f "tokens=*" %%a in ('cd ..\terraform && terraform output -raw redis_auth_token 2^>nul') do set REDIS_AUTH=%%a

    if defined REDIS_ENDPOINT (
        if defined REDIS_AUTH (
            set REDIS_URL=redis://:%REDIS_AUTH%@%REDIS_ENDPOINT%:6379/0
        ) else (
            set REDIS_URL=redis://%REDIS_ENDPOINT%:6379/0
        )
        echo [INFO] Redis URL auto-detected from Terraform
    )
)

if not defined REDIS_URL (
    echo [WARN] Could not get Redis URL from Terraform. Please enter manually:
    set /p REDIS_ENDPOINT="ElastiCache Endpoint (e.g., redis.xxxxx.use1.cache.amazonaws.com): "
    echo Enter Redis Auth Token (leave empty if not using auth):
    powershell -Command "$pw = Read-Host -AsSecureString; [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))" > tmp_pwd.txt
    set /p REDIS_AUTH=<tmp_pwd.txt
    del tmp_pwd.txt
    echo.

    if defined REDIS_AUTH (
        set REDIS_URL=redis://:%REDIS_AUTH%@%REDIS_ENDPOINT%:6379/0
    ) else (
        set REDIS_URL=redis://%REDIS_ENDPOINT%:6379/0
    )
)

aws secretsmanager describe-secret --secret-id %REDIS_URL_NAME% --region %AWS_REGION% >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    aws secretsmanager put-secret-value --secret-id %REDIS_URL_NAME% --secret-string "%REDIS_URL%" --region %AWS_REGION% >nul
) else (
    aws secretsmanager create-secret --name %REDIS_URL_NAME% --description "Redis connection URL" --secret-string "%REDIS_URL%" --region %AWS_REGION% >nul
)
echo [INFO] Redis URL configured

echo [INFO] All secrets configured successfully!
echo.
echo [INFO] Secret ARNs:
echo [INFO]   JWT Secret: arn:aws:secretsmanager:%AWS_REGION%:%ACCOUNT_ID%:secret:%JWT_SECRET_NAME%
echo [INFO]   Database URL: arn:aws:secretsmanager:%AWS_REGION%:%ACCOUNT_ID%:secret:%DATABASE_URL_NAME%
echo [INFO]   Redis URL: arn:aws:secretsmanager:%AWS_REGION%:%ACCOUNT_ID%:secret:%REDIS_URL_NAME%
echo.
echo [WARN] IMPORTANT: Update your ECS task definitions with these secret ARNs if they differ