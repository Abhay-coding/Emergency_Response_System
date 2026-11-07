#!/bin/bash
# Deploy ECS Services
#
# Usage: ./scripts/deploy.sh [environment] [image-tag]
# Example: ./scripts/deploy.sh production latest
# Example: ./scripts/deploy.sh staging git-abc123

set -euo pipefail

PROJECT_NAME="emergency-response"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${1:-production}"
IMAGE_TAG="${2:-latest}"

CLUSTER_NAME="${PROJECT_NAME}-${ENVIRONMENT}"
API_SERVICE_NAME="${PROJECT_NAME}-api"
WORKER_SERVICE_NAME="${PROJECT_NAME}-worker"
API_TASK_FAMILY="${PROJECT_NAME}-api"
WORKER_TASK_FAMILY="${PROJECT_NAME}-worker"

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
ECR_IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:${IMAGE_TAG}"

# Check if service exists
service_exists() {
    local service_name=$1
    aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$service_name" --region "$AWS_REGION" --query 'services[0].status' --output text 2>/dev/null | grep -q "ACTIVE"
}

# Register task definition
register_task_definition() {
    local task_family=$1
    local template_file=$2
    local output_file="/tmp/${task_family}-${ENVIRONMENT}-${IMAGE_TAG}.json"

    log_info "Registering task definition: $task_family"

    # Read template and substitute variables
    sed \
        -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
        -e "s|\${AWS_REGION}|${AWS_REGION}|g" \
        -e "s|\${IMAGE_TAG}|${IMAGE_TAG}|g" \
        -e "s|\${ECR_IMAGE_URI}|${ECR_IMAGE_URI}|g" \
        -e "s|\${CLUSTER_NAME}|${CLUSTER_NAME}|g" \
        "$template_file" > "$output_file"

    # Register with ECS
    aws ecs register-task-definition \
        --cli-input-json "file://$output_file" \
        --region "$AWS_REGION" \
        --query 'taskDefinition.taskDefinitionArn' \
        --output text
}

# Create or update service
deploy_service() {
    local service_name=$1
    local task_family=$2
    local template_file=$3
    local desired_count=$4

    log_step "Deploying $service_name..."

    # Register new task definition
    TASK_DEF_ARN=$(register_task_definition "$task_family" "$template_file")
    log_info "Registered task definition: $TASK_DEF_ARN"

    if service_exists "$service_name"; then
        log_info "Updating existing service: $service_name"
        aws ecs update-service \
            --cluster "$CLUSTER_NAME" \
            --service "$service_name" \
            --task-definition "$TASK_DEF_ARN" \
            --desired-count "$desired_count" \
            --force-new-deployment \
            --region "$AWS_REGION" \
            --output json > /dev/null
    else
        log_info "Creating new service: $service_name"
        # For create, we need the full service definition
        local service_template="${template_file/task-definition/service}"
        local service_output="/tmp/${service_name}-${ENVIRONMENT}.json"

        sed \
            -e "s|\${TASK_DEFINITION_ARN}|${TASK_DEF_ARN}|g" \
            -e "s|\${DESIRED_COUNT}|${desired_count}|g" \
            -e "s|\${CLUSTER_NAME}|${CLUSTER_NAME}|g" \
            "$service_template" > "$service_output"

        aws ecs create-service \
            --cli-input-json "file://$service_output" \
            --region "$AWS_REGION" \
            --output json > /dev/null
    fi

    log_info "Service deployment initiated: $service_name"
}

# Wait for deployment to complete
wait_for_deployment() {
    local service_name=$1
    local timeout=600  # 10 minutes
    local interval=15
    local elapsed=0

    log_info "Waiting for deployment to stabilize: $service_name"

    while [[ $elapsed -lt $timeout ]]; do
        DEPLOYMENT_STATUS=$(aws ecs describe-services \
            --cluster "$CLUSTER_NAME" \
            --services "$service_name" \
            --region "$AWS_REGION" \
            --query 'services[0].deployments[0].rolloutState' \
            --output text)

        RUNNING_COUNT=$(aws ecs describe-services \
            --cluster "$CLUSTER_NAME" \
            --services "$service_name" \
            --region "$AWS_REGION" \
            --query 'services[0].runningCount' \
            --output text)

        DESIRED_COUNT=$(aws ecs describe-services \
            --cluster "$CLUSTER_NAME" \
            --services "$service_name" \
            --region "$AWS_REGION" \
            --query 'services[0].desiredCount' \
            --output text)

        log_info "  Status: $DEPLOYMENT_STATUS | Running: $RUNNING_COUNT / Desired: $DESIRED_COUNT"

        if [[ "$DEPLOYMENT_STATUS" == "COMPLETED" && "$RUNNING_COUNT" -eq "$DESIRED_COUNT" ]]; then
            log_info "Deployment completed successfully: $service_name"
            return 0
        elif [[ "$DEPLOYMENT_STATUS" == "FAILED" ]]; then
            log_error "Deployment failed: $service_name"
            return 1
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
    done

    log_error "Deployment timeout: $service_name"
    return 1
}

# Main execution
main() {
    log_info "Starting deployment for ${PROJECT_NAME} (${ENVIRONMENT})"
    log_info "Image: ${ECR_IMAGE_URI}"
    log_info "Cluster: ${CLUSTER_NAME}"

    # Check cluster exists
    if ! aws ecs describe-clusters --clusters "$CLUSTER_NAME" --region "$AWS_REGION" --query 'clusters[0].status' --output text | grep -q "ACTIVE"; then
        log_error "Cluster $CLUSTER_NAME does not exist or is not active"
        log_info "Run terraform apply first to create infrastructure"
        exit 1
    fi

    # Deploy API service
    deploy_service "$API_SERVICE_NAME" "$API_TASK_FAMILY" \
        "../ecs-task-definition.json" 2

    # Deploy Worker service
    deploy_service "$WORKER_SERVICE_NAME" "$WORKER_TASK_FAMILY" \
        "../ecs-worker-task-definition.json" 1

    # Wait for both deployments
    wait_for_deployment "$API_SERVICE_NAME" &
    API_PID=$!

    wait_for_deployment "$WORKER_SERVICE_NAME" &
    WORKER_PID=$!

    wait $API_PID
    API_RESULT=$?

    wait $WORKER_PID
    WORKER_RESULT=$?

    if [[ $API_RESULT -eq 0 && $WORKER_RESULT -eq 0 ]]; then
        log_info "All deployments completed successfully!"
    else
        log_error "One or more deployments failed"
        exit 1
    fi
}

main "$@"