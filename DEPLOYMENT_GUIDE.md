# AWS Deployment Guide for Campus Medical Assistance

This guide walks you through deploying the Campus Medical Assistance application to AWS using ECS Fargate.

## 📋 Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured (`aws configure`)
- Terraform >= 1.5.0 installed
- Docker installed and running
- GitHub repository (for CI/CD)

## 🏗️ Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Users     │────▶│     ALB      │────▶│ ECS Fargate │
│  (HTTPS)    │     │  (Port 443)  │     │   API       │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                    ┌──────────────┐             │
                    │   RDS        │◀────────────┤
                    │  PostgreSQL  │             │
                    └──────────────┘             │
                                                 │
                    ┌──────────────┐             │
                    │ ElastiCache  │◀────────────┤
                    │    Redis     │             │
                    └──────────────┘             │
                                                 │
                    ┌──────────────┐             │
                    │     EFS      │◀────────────┤
                    │  (uploads)   │             │
                    └──────────────┘             │
                                                 ▼
                    ┌──────────────┐     ┌─────────────┐
                    │     SQS      │────▶│ ECS Fargate │
                    │ (notifications)   │   Worker    │
                    └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │     SNS      │
                    │   (SMS)      │
                    └──────────────┘
```

## 🚀 Quick Start (Automated)

### 1. Clone and Configure

```bash
git clone <your-repo>
cd emergency-response

# Copy and edit Terraform variables
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars with your values
```

### 2. Deploy Infrastructure

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 3. Set Up Secrets

```bash
cd ../scripts
./setup-secrets.sh production
```

### 4. Build and Deploy

```bash
./build-and-push.sh production latest
./migrate.sh production upgrade
./deploy.sh production latest
```

## 📦 Manual Step-by-Step Deployment

### Phase 1: Infrastructure with Terraform

#### 1.1 Configure Terraform Variables

Edit `terraform/terraform.tfvars`:

```hcl
# Required: Your AWS region
aws_region = "us-east-1"

# Required: ACM Certificate ARN for HTTPS
# Request in AWS Certificate Manager for your domain
acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Optional: Custom domain
domain_name = "api.yourdomain.com"
hosted_zone_id = "Z123456789EXAMPLE"

# Required: Phone numbers for notifications (E.164 format)
campus_emergency_phone = "+15551234567"
backup_phone = "+15559876543"
```

#### 1.2 Initialize and Apply

```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

#### 1.3 Save Important Outputs

After apply, save these outputs (you'll need them):

```bash
terraform output -json > ../terraform-outputs.json
```

Key outputs:
- `vpc_id`, `private_subnet_ids`, `public_subnet_ids`
- `rds_endpoint`, `redis_primary_endpoint`
- `efs_file_system_id`, `efs_access_point_id`
- `ecr_repository_url`, `ecs_cluster_name`
- `target_group_arn`, `sqs_queue_url`, `sns_topic_arn`
- `ecs_task_execution_role_arn`, `ecs_task_role_arn`
- `alb_security_group_id`, `ecs_tasks_security_group_id`

### Phase 2: Configure Secrets

Run the secrets setup script:

```bash
cd scripts
./setup-secrets.sh production
```

This will:
1. Generate a secure JWT secret
2. Prompt for database URL (or auto-detect from Terraform)
3. Prompt for Redis URL (or auto-detect from Terraform)
4. Store all in AWS Secrets Manager

### Phase 3: Build Docker Image

```bash
./build-and-push.sh production latest
```

This will:
1. Login to ECR
2. Build the production Docker image
3. Push to ECR with `latest` tag

### Phase 4: Run Database Migrations

```bash
./migrate.sh production upgrade
```

This runs `alembic upgrade head` as an ECS task.

### Phase 5: Deploy Services

```bash
./deploy.sh production latest
```

This will:
1. Register new task definitions with the latest image
2. Update/create ECS services
3. Wait for deployments to stabilize

## 🔧 CI/CD with GitHub Actions

### Required GitHub Secrets

Add these secrets to your GitHub repository:

| Secret | Description |
|--------|-------------|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for GitHub Actions to assume |
| `SLACK_WEBHOOK_URL` | (Optional) Slack webhook for notifications |

### IAM Role for GitHub Actions

Create an IAM role with trust policy for GitHub OIDC:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/YOUR_REPO:*"
        }
      }
    }
  ]
}
```

Attach policies for:
- ECR (Push/Pull)
- ECS (UpdateService, RegisterTaskDefinition, RunTask)
- SSM (GetParameter for network config)
- CloudWatch Logs (Read)

### Deployment Triggers

| Branch/Tag | Environment | Action |
|------------|-------------|--------|
| `develop` | Staging | Auto-deploy on push |
| `main` | Staging | Auto-deploy on push |
| `v*` tags | Production | Auto-deploy on tag push |

### Manual Deployment

To deploy a specific version:

```bash
# Tag the release
git tag v1.0.0
git push origin v1.0.0

# Or trigger manually via GitHub Actions UI
```

## 🛠️ Management Commands

### View Service Status

```bash
aws ecs describe-services \
  --cluster emergency-response-production \
  --services emergency-response-api emergency-response-worker \
  --region us-east-1
```

### View Logs

```bash
# API logs
aws logs tail /ecs/emergency-response-api-production --follow

# Worker logs
aws logs tail /ecs/emergency-response-worker-production --follow
```

### Scale Services

```bash
# Scale API to 4 tasks
aws ecs update-service \
  --cluster emergency-response-production \
  --service emergency-response-api \
  --desired-count 4 \
  --region us-east-1
```

### Run One-off Tasks

```bash
# Create admin user
aws ecs run-task \
  --cluster emergency-response-production \
  --task-definition emergency-response-api \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"emergency-response-api","command":["python","-m","app.cli","create-admin","admin@yourdomain.com"]}]}' \
  --region us-east-1
```

### Execute Commands in Running Container

```bash
aws ecs execute-command \
  --cluster emergency-response-production \
  --task <task-id> \
  --container emergency-response-api \
  --command "/bin/sh" \
  --interactive \
  --region us-east-1
```

## 🔍 Monitoring & Troubleshooting

### Health Checks

```bash
# ALB health check
curl -v https://your-alb-dns-name/health

# Direct container health
curl http://localhost:8000/health
```

### Common Issues

#### Service Stuck in DEPLOYING

```bash
# Check events
aws ecs describe-services \
  --cluster emergency-response-production \
  --services emergency-response-api \
  --region us-east-1 \
  --query 'services[0].events[:5]'
```

#### Task Fails to Start

```bash
# Check task failure reason
aws ecs describe-tasks \
  --cluster emergency-response-production \
  --tasks <task-arn> \
  --region us-east-1 \
  --query 'tasks[0].stoppedReason'
```

#### Database Connection Issues

1. Verify security groups allow traffic from ECS tasks to RDS (port 5432)
2. Check Secrets Manager has correct DATABASE_URL
3. Verify RDS is in same VPC and subnets

#### Redis Connection Issues

1. Verify security groups allow traffic from ECS tasks to ElastiCache (port 6379)
2. Check Secrets Manager has correct Redis URL with auth token

#### EFS Mount Issues

1. Verify EFS mount targets exist in each subnet
2. Check EFS access point configuration
3. Verify IAM policy allows EFS access

## 🔐 Security Best Practices

1. **Rotate Secrets Regularly**
   ```bash
   # JWT secret rotation (every 90 days)
   ./scripts/setup-secrets.sh production
   ```

2. **Enable Deletion Protection**
   - RDS: Enabled in production
   - EFS: Enabled
   - ALB: Enabled in production

3. **Use Private Subnets Only**
   - ECS tasks: No public IP
   - RDS: Not publicly accessible
   - ElastiCache: Private only

4. **Enable Encryption**
   - RDS: Storage encrypted
   - ElastiCache: At-rest and in-transit
   - EFS: Encrypted
   - ECR: AES256
   - Secrets: KMS encrypted

5. **Least Privilege IAM**
   - Task role: Only SQS, SNS, EFS, Secrets Manager
   - Execution role: ECR, CloudWatch, Secrets Manager

## 💰 Cost Optimization

### Development/Staging
- Use `db.t3.small` for RDS
- Use `cache.t3.micro` for Redis
- Single NAT Gateway
- Minimum task counts (1 API, 1 worker)

### Production
- Use `db.t3.medium` or larger for RDS
- Use `cache.t3.small` or larger for Redis
- Multi-AZ for RDS and Redis
- Multiple NAT Gateways
- Minimum 2 API tasks for HA

### Monitoring Costs
```bash
# Set up billing alerts
aws budgets create-budget --account-id <account-id> --budget file://budget.json
```

## 📝 Checklist Before Going Live

- [ ] Terraform infrastructure deployed
- [ ] ACM certificate validated and attached to ALB
- [ ] Route53 records pointing to ALB
- [ ] Secrets configured in Secrets Manager
- [ ] Docker image built and pushed to ECR
- [ ] Database migrations run successfully
- [ ] ECS services deployed and healthy
- [ ] ALB health checks passing
- [ ] CloudWatch alarms configured
- [ ] Admin user created
- [ ] Test notification flow end-to-end
- [ ] Load test completed
- [ ] Backup/restore tested

## 🆘 Rollback Procedure

### Quick Rollback (ECS)

```bash
# Rollback to previous task definition
aws ecs update-service \
  --cluster emergency-response-production \
  --service emergency-response-api \
  --task-definition emergency-response-api:PREVIOUS_REVISION \
  --force-new-deployment \
  --region us-east-1
```

### Database Rollback

```bash
# Downgrade one migration
./migrate.sh production "downgrade -1"
```

### Full Infrastructure Rollback

```bash
cd terraform
terraform apply -refresh-only
terraform plan -destroy
terraform destroy
```

## 📞 Support

- Check CloudWatch Logs for application errors
- Check ECS service events for deployment issues
- Check RDS/ElastiCache metrics for performance issues
- Review ALB access logs for traffic patterns

---

**Next Steps**: After deployment, configure your frontend to point to the ALB DNS name or custom domain, and test the complete user flow.