#!/bin/bash
# Build and Push Docker Image to ECR
#
# Usage: ./scripts/build-and-push.sh [environment] [tag]
# Example: ./scripts/build-and-push.sh production latest
# Example: ./scripts/build-and-push.sh staging git-abc123

set -euo pipefail

# Configuration
PROJECT_NAME="emergency-response"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${1:-production}"
IMAGE_TAG="${2:-latest}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured"
        exit 1
    fi

    log_info "Prerequisites check passed"
}

# Get AWS Account ID
get_account_id() {
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    log_info "AWS Account ID: $ACCOUNT_ID"
}

# Login to ECR
ecr_login() {
    log_info "Logging into ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
}

# Build Docker image
build_image() {
    log_info "Building Docker image..."

    # Build with BuildKit for better caching
    DOCKER_BUILDKIT=1 docker build \
        --target production \
        -t "${PROJECT_NAME}-api:${IMAGE_TAG}" \
        -t "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:${IMAGE_TAG}" \
        -f Dockerfile \
        .

    log_info "Docker image built successfully"
}

# Push to ECR
push_image() {
    log_info "Pushing image to ECR..."
    docker push "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:${IMAGE_TAG}"
    log_info "Image pushed successfully"
}

# Tag as latest if not already
tag_latest() {
    if [[ "$IMAGE_TAG" != "latest" ]]; then
        log_info "Tagging as latest..."
        docker tag \
            "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:${IMAGE_TAG}" \
            "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:latest"
        docker push "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:latest"
    fi
}

# Main execution
main() {
    log_info "Starting build and push for ${PROJECT_NAME} (${ENVIRONMENT})"
    log_info "Image tag: ${IMAGE_TAG}"

    check_prerequisites
    get_account_id
    ecr_login
    build_image
    push_image
    tag_latest

    log_info "Build and push completed successfully!"
    log_info "Image URI: ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-api:${IMAGE_TAG}"
}

main "$@"