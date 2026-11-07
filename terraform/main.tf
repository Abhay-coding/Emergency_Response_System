# Terraform Configuration for Campus Medical Assistance - AWS ECS Fargate Deployment
#
# Usage:
# 1. Copy terraform.tfvars.example to terraform.tfvars and fill in your values
# 2. Run: terraform init
# 3. Run: terraform plan
# 4. Run: terraform apply
#
# This creates a complete production-ready AWS infrastructure for the application.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    # Configure after first run - replace with your bucket
    # bucket         = "your-terraform-state-bucket"
    # key            = "emergency-response/terraform.tfstate"
    # region         = "us-east-1"
    # encrypt        = true
    # dynamodb_table = "terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "emergency-response"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Random resources for unique names
resource "random_id" "suffix" {
  byte_length = 4
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "random_password" "redis_auth_token" {
  length  = 32
  special = false
}

resource "tls_private_key" "db_ca" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

# ──────────────────────────────────────────────────────────────
# VPC MODULE
# ──────────────────────────────────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project_name}-${var.environment}"

  cidr_block = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway     = true
  single_nat_gateway     = var.environment != "production"
  enable_dns_hostnames   = true
  enable_dns_support     = true
  enable_classiclink     = false
  enable_classiclink_dns = false

  # NAT Gateway configuration
  nat_gateway_elastic_ips = var.environment == "production" ? var.az_count : 1

  # VPC Flow Logs
  vpc_flow_logs = {
    cloudwatch = {
      destination_type = "cloudwatch-logs"
      log_group_name   = "/aws/vpc/flowlogs/${var.project_name}-${var.environment}"
      traffic_type     = "ALL"
    }
  }

  # Tags
  tags = {
    Name = "${var.project_name}-${var.environment}"
  }

  public_subnet_tags = {
    Type = "public"
  }

  private_subnet_tags = {
    Type = "private"
  }
}

# ──────────────────────────────────────────────────────────────
# SECURITY GROUPS
# ──────────────────────────────────────────────────────────────

# ALB Security Group - allows HTTPS from internet
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-${var.environment}"
  description = "Security group for Application Load Balancer"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from anywhere (redirects to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-alb-${var.environment}"
  }
}

# ECS Tasks Security Group - allows traffic from ALB and to RDS/Redis/EFS
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks-${var.environment}"
  description = "Security group for ECS Fargate tasks"
  vpc_id      = module.vpc.vpc_id

  # Ingress from ALB only
  ingress {
    description = "From ALB on port 8000"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Allow all outbound (to RDS, Redis, EFS, Internet via NAT)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ecs-tasks-${var.environment}"
  }
}

# RDS Security Group - only from ECS tasks
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-${var.environment}"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "PostgreSQL from ECS tasks"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = {
    Name = "${var.project_name}-rds-${var.environment}"
  }
}

# ElastiCache Security Group - only from ECS tasks
resource "aws_security_group" "elasticache" {
  name        = "${var.project_name}-elasticache-${var.environment}"
  description = "Security group for ElastiCache Redis"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "Redis from ECS tasks"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = {
    Name = "${var.project_name}-elasticache-${var.environment}"
  }
}

# EFS Security Group - only from ECS tasks
resource "aws_security_group" "efs" {
  name        = "${var.project_name}-efs-${var.environment}"
  description = "Security group for EFS file system"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "NFS from ECS tasks"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = {
    Name = "${var.project_name}-efs-${var.environment}"
  }
}

# ──────────────────────────────────────────────────────────────
# RDS POSTGRESQL
# ──────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "rds" {
  name       = "${var.project_name}-rds-subnet-${var.environment}"
  subnet_ids = module.vpc.private_subnets

  tags = {
    Name = "${var.project_name}-rds-subnet-${var.environment}"
  }
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.project_name}-${var.environment}"
  engine                 = "postgres"
  engine_version         = "15.7"
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  max_allocated_storage  = var.db_max_allocated_storage
  storage_type           = "gp3"
  storage_encrypted      = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_password.result

  vpc_security_group_ids = [aws_security_group.rds.id]
  db_subnet_group_name   = aws_db_subnet_group.rds.name

  # Multi-AZ for production
  multi_az               = var.environment == "production"
  publicly_accessible    = false

  # Backup configuration
  backup_retention_period = var.environment == "production" ? 30 : 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  # Monitoring
  monitoring_interval     = 60
  monitoring_role_arn     = aws_iam_role.rds_monitoring.arn
  performance_insights_enabled = var.environment == "production"

  # Deletion protection for production
  deletion_protection     = var.environment == "production"
  skip_final_snapshot     = var.environment != "production"

  # Parameter group for tuning
  parameter_group_name    = aws_db_parameter_group.postgres.name

  tags = {
    Name = "${var.project_name}-postgres-${var.environment}"
  }
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${var.project_name}-postgres-params-${var.environment}"
  family = "postgres15"

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_iam_role" "rds_monitoring" {
  name = "${var.project_name}-rds-monitoring-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ──────────────────────────────────────────────────────────────
# ELASTICACHE REDIS
# ──────────────────────────────────────────────────────────────

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project_name}-redis-subnet-${var.environment}"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.project_name}-redis-${var.environment}"
  description                = "Redis for ${var.project_name} ${var.environment}"

  engine                     = "redis"
  engine_version             = "7.2"
  node_type                  = var.redis_node_type
  number_cache_clusters      = var.environment == "production" ? 2 : 1
  automatic_failover_enabled = var.environment == "production"
  multi_az_enabled           = var.environment == "production"

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.elasticache.id]

  # Encryption
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth_token.result

  # Backup
  snapshot_retention_limit = var.environment == "production" ? 7 : 1
  snapshot_window          = "03:00-04:00"

  # Maintenance
  maintenance_window = "sun:05:00-sun:06:00"

  # Logging
  log_delivery_configuration {
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
    destination_details {
      cloudwatch_logs {
        log_group = aws_cloudwatch_log_group.redis_slow.name
      }
    }
  }

  log_delivery_configuration {
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "engine-log"
    destination_details {
      cloudwatch_logs {
        log_group = aws_cloudwatch_log_group.redis_engine.name
      }
    }
  }

  tags = {
    Name = "${var.project_name}-redis-${var.environment}"
  }
}

resource "aws_cloudwatch_log_group" "redis_slow" {
  name              = "/aws/elasticache/${var.project_name}-redis-slow-${var.environment}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "redis_engine" {
  name              = "/aws/elasticache/${var.project_name}-redis-engine-${var.environment}"
  retention_in_days = 30
}

# ──────────────────────────────────────────────────────────────
# EFS FILE SYSTEM
# ──────────────────────────────────────────────────────────────

resource "aws_efs_file_system" "uploads" {
  creation_token = "${var.project_name}-uploads-${var.environment}"

  encrypted = true

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name = "${var.project_name}-uploads-${var.environment}"
  }
}

resource "aws_efs_mount_target" "uploads" {
  count = length(module.vpc.private_subnets)

  file_system_id  = aws_efs_file_system.uploads.id
  subnet_id       = module.vpc.private_subnets[count.index]
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "uploads" {
  file_system_id = aws_efs_file_system.uploads.id

  posix_user {
    uid = 1001
    gid = 1001
  }

  root_directory {
    path = "/uploads"
    creation_info {
      owner_uid   = 1001
      owner_gid   = 1001
      permissions = "0755"
    }
  }

  tags = {
    Name = "${var.project_name}-uploads-ap-${var.environment}"
  }
}

# ──────────────────────────────────────────────────────────────
# ECR REPOSITORY
# ──────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle_policy {
    policy = jsonencode({
      rules = [{
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      }]
    })
  }
}

# ──────────────────────────────────────────────────────────────
# ECS CLUSTER
# ──────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs_exec.name
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/aws/ecs/${var.project_name}-exec-${var.environment}"
  retention_in_days = 30
}

# ──────────────────────────────────────────────────────────────
# APPLICATION LOAD BALANCER
# ──────────────────────────────────────────────────────────────

resource "aws_lb" "alb" {
  name               = "${var.project_name}-alb-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = module.vpc.public_subnets

  enable_deletion_protection = var.environment == "production"

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.bucket
    prefix  = "${var.project_name}-alb"
    enabled = true
  }
}

resource "aws_s3_bucket" "alb_logs" {
  bucket = "${var.project_name}-alb-logs-${random_id.suffix.hex}-${var.aws_region}"

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  lifecycle_rule {
    enabled = true
    expiration {
      days = 90
    }
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-api-tg-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = module.vpc.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = false
  }
}

# HTTP listener (redirects to HTTPS)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.alb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS listener (requires ACM certificate)
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.alb.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ──────────────────────────────────────────────────────────────
# SQS QUEUE
# ──────────────────────────────────────────────────────────────

resource "aws_sqs_queue" "notifications" {
  name                       = "${var.project_name}-notifications-${var.environment}.fifo"
  fifo_queue                 = true
  content_based_deduplication = true
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 300
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notifications_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${var.project_name}-notifications-${var.environment}"
  }
}

resource "aws_sqs_queue" "notifications_dlq" {
  name                      = "${var.project_name}-notifications-dlq-${var.environment}.fifo"
  fifo_queue                = true
  content_based_deduplication = true
  message_retention_seconds = 1209600

  tags = {
    Name = "${var.project_name}-notifications-dlq-${var.environment}"
  }
}

# ──────────────────────────────────────────────────────────────
# SNS TOPIC
# ──────────────────────────────────────────────────────────────

resource "aws_sns_topic" "notifications" {
  name = "${var.project_name}-notifications-${var.environment}"

  tags = {
    Name = "${var.project_name}-notifications-${var.environment}"
  }
}

# ──────────────────────────────────────────────────────────────
# IAM ROLES
# ──────────────────────────────────────────────────────────────

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-task-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Custom policy for task execution role (ECR, CloudWatch, Secrets Manager)
resource "aws_iam_policy" "ecs_task_execution_custom" {
  name = "${var.project_name}-ecs-task-execution-custom-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "kms:Decrypt"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_custom" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = aws_iam_policy.ecs_task_execution_custom.arn
}

# ECS Task Role (for application permissions)
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

# Task role policy for application permissions
resource "aws_iam_policy" "ecs_task_application" {
  name = "${var.project_name}-ecs-task-application-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:emergency-response/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-notifications-*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = [
          "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-notifications-*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess"
        ]
        Resource = [
          "arn:aws:elasticfilesystem:${var.aws_region}:${data.aws_caller_identity.current.account_id}:file-system/${aws_efs_file_system.uploads.id}"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_application" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_application.arn
}

# ──────────────────────────────────────────────────────────────
# SECRETS MANAGER
# ──────────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "jwt_secret" {
  name        = "emergency-response/jwt-secret"
  description = "JWT signing secret for emergency-response application"
  kms_key_id  = aws_kms_key.secrets.arn

  rotation_rules {
    automatically_after_days = 90
  }
}

resource "aws_secretsmanager_secret" "database_url" {
  name        = "emergency-response/database-url"
  description = "PostgreSQL database connection URL"
  kms_key_id  = aws_kms_key.secrets.arn
}

resource "aws_secretsmanager_secret" "redis_url" {
  name        = "emergency-response/redis-url"
  description = "Redis connection URL"
  kms_key_id  = aws_kms_key.secrets.arn
}

# Note: Secret values should be set manually or via external process
# terraform apply will create the secrets but not set values for security

resource "aws_kms_key" "secrets" {
  description = "KMS key for Secrets Manager encryption"

  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Allow administration"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "Allow Secrets Manager to use"
        Effect = "Allow"
        Principal = {
          Service = "secretsmanager.amazonaws.com"
        }
        Action   = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
          StringLike = {
            "kms:EncryptionContext:SecretARN" = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:emergency-response/*"
          }
        }
      }
    ]
  })
}

# ──────────────────────────────────────────────────────────────
# CLOUDWATCH LOG GROUPS
# ──────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/emergency-response-api-${var.environment}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/emergency-response-worker-${var.environment}"
  retention_in_days = 30
}

# ──────────────────────────────────────────────────────────────
# SERVICE DISCOVERY (Cloud Map)
# ──────────────────────────────────────────────────────────────

resource "aws_service_discovery_private_dns_namespace" "ecs" {
  name        = "${var.project_name}.local"
  description = "Service discovery for ${var.project_name} ${var.environment}"
  vpc         = module.vpc.vpc_id
}

resource "aws_service_discovery_service" "api" {
  name        = "api"
  namespace_id = aws_service_discovery_private_dns_namespace.ecs.id

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.ecs.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type  = "A"
      ttl   = 60
    }
  }

  health_check_custom_config {
    failure_threshold = 3
  }
}

# ──────────────────────────────────────────────────────────────
# DATA SOURCES
# ──────────────────────────────────────────────────────────────

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# ──────────────────────────────────────────────────────────────
# OUTPUTS
# ──────────────────────────────────────────────────────────────

output "vpc_id" {
  value       = module.vpc.vpc_id
  description = "VPC ID"
}

output "private_subnet_ids" {
  value       = module.vpc.private_subnets
  description = "Private subnet IDs"
}

output "public_subnet_ids" {
  value       = module.vpc.public_subnets
  description = "Public subnet IDs"
}

output "alb_dns_name" {
  value       = aws_lb.alb.dns_name
  description = "ALB DNS name"
}

output "alb_arn" {
  value       = aws_lb.alb.arn
  description = "ALB ARN"
}

output "target_group_arn" {
  value       = aws_lb_target_group.api.arn
  description = "Target group ARN"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS cluster name"
}

output "ecs_cluster_arn" {
  value       = aws_ecs_cluster.main.arn
  description = "ECS cluster ARN"
}

output "rds_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "RDS endpoint"
  sensitive   = true
}

output "rds_port" {
  value       = aws_db_instance.postgres.port
  description = "RDS port"
}

output "redis_primary_endpoint" {
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  description = "Redis primary endpoint"
}

output "redis_port" {
  value       = aws_elasticache_replication_group.redis.port
  description = "Redis port"
}

output "efs_file_system_id" {
  value       = aws_efs_file_system.uploads.id
  description = "EFS file system ID"
}

output "efs_access_point_id" {
  value       = aws_efs_access_point.uploads.id
  description = "EFS access point ID"
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "ECR repository URL"
}

output "ecs_task_execution_role_arn" {
  value       = aws_iam_role.ecs_task_execution.arn
  description = "ECS task execution role ARN"
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.ecs_task.arn
  description = "ECS task role ARN"
}

output "sqs_queue_url" {
  value       = aws_sqs_queue.notifications.url
  description = "SQS queue URL"
}

output "sns_topic_arn" {
  value       = aws_sns_topic.notifications.arn
  description = "SNS topic ARN"
}

output "service_discovery_namespace_id" {
  value       = aws_service_discovery_private_dns_namespace.ecs.id
  description = "Service discovery namespace ID"
}

output "service_discovery_service_arn" {
  value       = aws_service_discovery_service.api.arn
  description = "Service discovery service ARN"
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "ALB security group ID"
}

output "ecs_tasks_security_group_id" {
  value       = aws_security_group.ecs_tasks.id
  description = "ECS tasks security group ID"
}

output "db_password" {
  value       = random_password.db_password.result
  description = "Database password (generated)"
  sensitive   = true
}

output "redis_auth_token" {
  value       = random_password.redis_auth_token.result
  description = "Redis auth token (generated)"
  sensitive   = true
}