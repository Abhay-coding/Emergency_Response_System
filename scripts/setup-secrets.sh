#!/bin/bash
# Setup Secrets in AWS Secrets Manager
#
# Usage: ./scripts/setup-secrets.sh [environment]
# Example: ./scripts/setup-secrets.sh production
# Example: ./scripts/setup-secrets.sh staging

set -euo pipefail

PROJECT_NAME="emergency-response"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${1:-production}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Secret names
JWT_SECRET_NAME="emergency-response/jwt-secret"
DATABASE_URL_NAME="emergency-response/database-url"
REDIS_URL_NAME="emergency-response/redis-url"

# Check if secret exists
secret_exists() {
    aws secretsmanager describe-secret --secret-id "$1" --region "$AWS_REGION" &>/dev/null
}

# Create or update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_value=$2
    local description=$3

    if secret_exists "$secret_name"; then
        log_info "Updating secret: $secret_name"
        aws secretsmanager put-secret-value \
            --secret-id "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" \
            --output json > /dev/null
    else
        log_info "Creating secret: $secret_name"
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --description "$description" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" \
            --output json > /dev/null
    fi
}

# Generate secure random string
generate_secret() {
    openssl rand -hex 32
}

# Get database URL from Terraform output or prompt
get_database_url() {
    if [[ -f "../terraform/terraform.tfstate" ]]; then
        RDS_ENDPOINT=$(cd ../terraform && terraform output -raw rds_endpoint 2>/dev/null || echo "")
        DB_PASSWORD=$(cd ../terraform && terraform output -raw db_password 2>/dev/null || echo "")
        DB_NAME=$(cd ../terraform && terraform output -raw db_name 2>/dev/null || echo "emergency")
        DB_USERNAME=$(cd ../terraform && terraform output -raw db_username 2>/dev/null || echo "admin")

        if [[ -n "$RDS_ENDPOINT" && -n "$DB_PASSWORD" ]]; then
            echo "postgresql+psycopg://${DB_USERNAME}:${DB_PASSWORD}@${RDS_ENDPOINT}/${DB_NAME}"
            return
        fi
    fi

    # Prompt for manual entry
    log_warn "Could not get database URL from Terraform. Please enter manually:"
    read -p "RDS Endpoint (e.g., db.xxxxx.us-east-1.rds.amazonaws.com): " RDS_ENDPOINT
    read -p "Database name [emergency]: " DB_NAME
    DB_NAME=${DB_NAME:-emergency}
    read -p "Database username [admin]: " DB_USERNAME
    DB_USERNAME=${DB_USERNAME:-admin}
    read -s -p "Database password: " DB_PASSWORD
    echo

    echo "postgresql+psycopg://${DB_USERNAME}:${DB_PASSWORD}@${RDS_ENDPOINT}/${DB_NAME}"
}

# Get Redis URL from Terraform output or prompt
get_redis_url() {
    if [[ -f "../terraform/terraform.tfstate" ]]; then
        REDIS_ENDPOINT=$(cd ../terraform && terraform output -raw redis_primary_endpoint 2>/dev/null || echo "")
        REDIS_AUTH=$(cd ../terraform && terraform output -raw redis_auth_token 2>/dev/null || echo "")

        if [[ -n "$REDIS_ENDPOINT" ]]; then
            if [[ -n "$REDIS_AUTH" ]]; then
                echo "redis://:${REDIS_AUTH}@${REDIS_ENDPOINT}:6379/0"
            else
                echo "redis://${REDIS_ENDPOINT}:6379/0"
            fi
            return
        fi
    fi

    log_warn "Could not get Redis URL from Terraform. Please enter manually:"
    read -p "ElastiCache Endpoint (e.g., redis.xxxxx.use1.cache.amazonaws.com): " REDIS_ENDPOINT
    read -s -p "Redis Auth Token (leave empty if not using auth): " REDIS_AUTH
    echo

    if [[ -n "$REDIS_AUTH" ]]; then
        echo "redis://:${REDIS_AUTH}@${REDIS_ENDPOINT}:6379/0"
    else
        echo "redis://${REDIS_ENDPOINT}:6379/0"
    fi
}

# Main execution
main() {
    log_info "Setting up secrets for ${PROJECT_NAME} (${ENVIRONMENT})"

    # JWT Secret
    log_step "Configuring JWT Secret..."
    if secret_exists "$JWT_SECRET_NAME"; then
        log_info "JWT secret already exists. Regenerate? (y/N)"
        read -r REGENERATE_JWT
        if [[ "$REGENERATE_JWT" =~ ^[Yy]$ ]]; then
            JWT_SECRET=$(generate_secret)
            create_or_update_secret "$JWT_SECRET_NAME" "$JWT_SECRET" "JWT signing secret for emergency-response application"
            log_info "JWT secret regenerated"
        else
            log_info "Keeping existing JWT secret"
        fi
    else
        JWT_SECRET=$(generate_secret)
        create_or_update_secret "$JWT_SECRET_NAME" "$JWT_SECRET" "JWT signing secret for emergency-response application"
        log_info "JWT secret created"
    fi

    # Database URL
    log_step "Configuring Database URL..."
    DATABASE_URL=$(get_database_url)
    create_or_update_secret "$DATABASE_URL_NAME" "$DATABASE_URL" "PostgreSQL database connection URL"
    log_info "Database URL configured"

    # Redis URL
    log_step "Configuring Redis URL..."
    REDIS_URL=$(get_redis_url)
    create_or_update_secret "$REDIS_URL_NAME" "$REDIS_URL" "Redis connection URL"
    log_info "Redis URL configured"

    log_info "All secrets configured successfully!"
    log_info ""
    log_info "Secret ARNs:"
    log_info "  JWT Secret: arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:${JWT_SECRET_NAME}"
    log_info "  Database URL: arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:${DATABASE_URL_NAME}"
    log_info "  Redis URL: arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:${REDIS_URL_NAME}"
    log_info ""
    log_warn "IMPORTANT: Update your ECS task definitions with these secret ARNs if they differ"
}

main "$@"