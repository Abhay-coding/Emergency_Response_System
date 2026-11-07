#!/bin/bash
# Run Database Migrations on AWS ECS
#
# Usage: ./scripts/migrate.sh [environment] [command]
# Commands: upgrade, downgrade, current, history, revision
# Example: ./scripts/migrate.sh production upgrade
# Example: ./scripts/migrate.sh staging "downgrade -1"
# Example: ./scripts/migrate.sh production "revision --autogenerate -m 'add new column'"

set -euo pipefail

PROJECT_NAME="emergency-response"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${1:-production}"
MIGRATION_COMMAND="${2:-upgrade head}"

CLUSTER_NAME="${PROJECT_NAME}-${ENVIRONMENT}"
TASK_FAMILY="${PROJECT_NAME}-migration"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Get AWS Account ID and ECR image
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:latest"

# Get network configuration from Terraform outputs or environment
get_network_config() {
    log_info "Getting network configuration..."

    # Try to get from Terraform outputs
    if [[ -f "../terraform/terraform.tfstate" ]]; then
        PRIVATE_SUBNETS=$(cd ../terraform && terraform output -json private_subnet_ids | jq -r '.[]' | paste -sd "," -)
        SECURITY_GROUPS=$(cd ../terraform && terraform output -json ecs_tasks_security_group_id | jq -r '.')
    else
        # Fallback to environment variables
        PRIVATE_SUBNETS="${PRIVATE_SUBNETS:-subnet-xxxxxxxx,subnet-yyyyyyyy}"
        SECURITY_GROUPS="${ECS_SECURITY_GROUPS:-sg-xxxxxxxx}"
    fi

    log_info "Using subnets: $PRIVATE_SUBNETS"
    log_info "Using security groups: $SECURITY_GROUPS"
}

# Run migration as ECS task
run_migration_task() {
    local command="$1"

    log_step "Running migration: $command"

    # Create task override
    cat > /tmp/migration-override.json <<EOF
{
  "containerOverrides": [
    {
      "name": "emergency-response-api",
      "command": ["python", "-m", "alembic"] $(echo "$command" | sed 's/ /", "/g')
    }
  ]
}
EOF

    # Run the task
    TASK_ARN=$(aws ecs run-task \
        --cluster "$CLUSTER_NAME" \
        --task-definition "${PROJECT_NAME}-api" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNETS],securityGroups=[$SECURITY_GROUPS],assignPublicIp=DISABLED}" \
        --overrides file:///tmp/migration-override.json \
        --region "$AWS_REGION" \
        --query 'tasks[0].taskArn' \
        --output text)

    if [[ -z "$TASK_ARN" || "$TASK_ARN" == "None" ]]; then
        log_error "Failed to start migration task"
        return 1
    fi

    log_info "Migration task started: $TASK_ARN"

    # Wait for task to complete
    wait_for_task "$TASK_ARN"
}

# Wait for task completion and get logs
wait_for_task() {
    local task_arn=$1
    local timeout=600
    local interval=10
    local elapsed=0

    log_info "Waiting for migration task to complete..."

    while [[ $elapsed -lt $timeout ]]; do
        TASK_STATUS=$(aws ecs describe-tasks \
            --cluster "$CLUSTER_NAME" \
            --tasks "$task_arn" \
            --region "$AWS_REGION" \
            --query 'tasks[0].lastStatus' \
            --output text)

        case "$TASK_STATUS" in
            "STOPPED")
                EXIT_CODE=$(aws ecs describe-tasks \
                    --cluster "$CLUSTER_NAME" \
                    --tasks "$task_arn" \
                    --region "$AWS_REGION" \
                    --query 'tasks[0].containers[0].exitCode' \
                    --output text)

                if [[ "$EXIT_CODE" == "0" ]]; then
                    log_info "Migration completed successfully!"
                    # Get logs
                    get_task_logs "$task_arn"
                    return 0
                else
                    log_error "Migration failed with exit code: $EXIT_CODE"
                    get_task_logs "$task_arn"
                    return 1
                fi
                ;;
            "RUNNING")
                log_info "  Task is running... (${elapsed}s elapsed)"
                ;;
            "PENDING")
                log_info "  Task is pending... (${elapsed}s elapsed)"
                ;;
            *)
                log_warn "  Task status: $TASK_STATUS"
                ;;
        esac

        sleep $interval
        elapsed=$((elapsed + interval))
    done

    log_error "Migration task timeout after ${timeout}s"
    return 1
}

# Get task logs from CloudWatch
get_task_logs() {
    local task_arn=$1
    local task_id=$(echo "$task_arn" | awk -F/ '{print $NF}')
    local log_group="/ecs/emergency-response-api-${ENVIRONMENT}"
    local log_stream="ecs/emergency-response-api/${task_id}"

    log_info "Fetching migration logs..."

    aws logs get-log-events \
        --log-group-name "$log_group" \
        --log-stream-name "$log_stream" \
        --region "$AWS_REGION" \
        --query 'events[*].message' \
        --output text 2>/dev/null || log_warn "Could not fetch logs"
}

# Main execution
main() {
    log_info "Starting database migration for ${PROJECT_NAME} (${ENVIRONMENT})"
    log_info "Command: alembic $MIGRATION_COMMAND"

    get_network_config
    run_migration_task "$MIGRATION_COMMAND"
}

main "$@"