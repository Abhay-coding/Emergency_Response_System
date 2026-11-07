# Terraform Variables for Campus Medical Assistance on AWS

# ============================================================
# GENERAL SETTINGS
# ============================================================

variable "project_name" {
  description = "Name of the project (used for resource naming)"
  type        = string
  default     = "emergency-response"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod"
  }
}

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

# ============================================================
# VPC SETTINGS
# ============================================================

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "database_subnet_cidrs" {
  description = "CIDR blocks for database subnets (one per AZ, separate from private)"
  type        = list(string)
  default     = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnet internet access"
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Use single NAT Gateway (cost savings) vs one per AZ"
  type        = bool
  default     = false
}

# ============================================================
# ALB SETTINGS
# ============================================================

variable "alb_cidr_blocks" {
  description = "CIDR blocks allowed to access ALB (restrict for security)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "alb_certificate_arn" {
  description = "ACM Certificate ARN for HTTPS (required for production)"
  type        = string
  default     = ""
}

variable "alb_domain_name" {
  description = "Custom domain name for ALB (e.g., api.example.com)"
  type        = string
  default     = ""
}

variable "alb_target_group_config" {
  description = "Target group configuration for ALB"
  type = object({
    protocol               = string
    port                   = number
    health_check_path      = string
    health_check_interval  = number
    health_check_timeout   = number
    healthy_threshold      = number
    unhealthy_threshold    = number
    matcher                = string
  })
  default = {
    protocol               = "HTTP"
    port                   = 8000
    health_check_path      = "/health"
    health_check_interval  = 30
    health_check_timeout   = 10
    healthy_threshold      = 2
    unhealthy_threshold    = 3
    matcher                = "200"
  }
}

# ============================================================
# RDS SETTINGS
# ============================================================

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
  validation {
    condition     = contains(["db.t3.micro", "db.t3.small", "db.t3.medium", "db.t3.large", "db.r6g.large", "db.r6g.xlarge"], var.db_instance_class)
    error_message = "Invalid instance class"
  }
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Maximum allocated storage for autoscaling (GB)"
  type        = number
  default     = 100
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15.4"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "Database master password (use Secrets Manager in production)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "db_backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
  default     = true
}

variable "db_multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = true
}

# ============================================================
# ELASTICACHE SETTINGS
# ============================================================

variable "elasticache_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
  validation {
    condition     = contains(["cache.t3.micro", "cache.t3.small", "cache.t3.medium", "cache.r6g.large"], var.elasticache_node_type)
    error_message = "Invalid node type"
  }
}

variable "elasticache_num_nodes" {
  description = "Number of cache nodes (1 for dev, 2+ for prod with replica)"
  type        = number
  default     = 1
  validation {
    condition     = var.elasticache_num_nodes >= 1 && var.elasticache_num_nodes <= 5
    error_message = "Number of nodes must be between 1 and 5"
  }
}

variable "elasticache_engine_version" {
  description = "Redis engine version"
  type        = string
  default     = "7.0"
}

variable "elasticache_parameter_group" {
  description = "ElastiCache parameter group name"
  type        = string
  default     = "default.redis7"
}

variable "elasticache_auth_token" {
  description = "Redis auth token (leave empty to auto-generate)"
  type        = string
  default     = ""
  sensitive   = true
}

# ============================================================
# ECS SETTINGS
# ============================================================

variable "container_image" {
  description = "Docker image URI for the container (ECR URI)"
  type        = string
  default     = ""
}

variable "ecs_cpu" {
  description = "CPU units for API task (256 = 0.25 vCPU)"
  type        = string
  default     = "512"
}

variable "ecs_memory" {
  description = "Memory for API task in MiB"
  type        = string
  default     = "1024"
}

variable "ecs_desired_count" {
  description = "Desired number of API tasks"
  type        = number
  default     = 2
}

variable "ecs_max_capacity" {
  description = "Maximum capacity for auto scaling"
  type        = number
  default     = 10
}

variable "ecs_min_capacity" {
  description = "Minimum capacity for auto scaling"
  type        = number
  default     = 1
}

variable "ecs_environment_variables" {
  description = "Environment variables for API container"
  type        = map(string)
  default = {
    ENVIRONMENT          = "production"
    NOTIFICATION_MODE    = "sns"
    LOG_LEVEL            = "INFO"
    LOG_FORMAT           = "json"
    ACCESS_TOKEN_MINUTES = "30"
    REFRESH_TOKEN_DAYS   = "3"
    RATE_LIMIT_REQUESTS  = "200"
    RATE_LIMIT_WINDOW    = "60"
    MAX_UPLOAD_SIZE_MB   = "10"
  }
}

variable "ecs_secrets" {
  description = "Secrets for API container (from Secrets Manager)"
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = [
    {
      name      = "JWT_SECRET"
      valueFrom = "arn:aws:secretsmanager:${aws_region}:${account_id}:secret:emergency-response/jwt-secret"
    },
    {
      name      = "DATABASE_URL"
      valueFrom = "arn:aws:secretsmanager:${aws_region}:${account_id}:secret:emergency-response/database-url"
    }
  ]
}

# ============================================================
# WORKER SETTINGS
# ============================================================

variable "worker_cpu" {
  description = "CPU units for worker task"
  type        = string
  default     = "256"
}

variable "worker_memory" {
  description = "Memory for worker task in MiB"
  type        = string
  default     = "512"
}

variable "worker_desired_count" {
  description = "Desired number of worker tasks"
  type        = number
  default     = 1
}

variable "worker_environment_variables" {
  description = "Environment variables for worker container"
  type        = map(string)
  default = {
    ENVIRONMENT       = "production"
    NOTIFICATION_MODE = "sns"
    LOG_LEVEL         = "INFO"
  }
}

variable "worker_secrets" {
  description = "Secrets for worker container"
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = [
    {
      name      = "JWT_SECRET"
      valueFrom = "arn:aws:secretsmanager:${aws_region}:${account_id}:secret:emergency-response/jwt-secret"
    },
    {
      name      = "DATABASE_URL"
      valueFrom = "arn:aws:secretsmanager:${aws_region}:${account_id}:secret:emergency-response/database-url"
    }
  ]
}

# ============================================================
# APPLICATION SETTINGS
# ============================================================

variable "jwt_secret" {
  description = "JWT secret for token signing (use Secrets Manager in production)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "campus_emergency_phone" {
  description = "Campus emergency phone number"
  type        = string
  default     = ""
}

variable "backup_phone" {
  description = "Backup phone number"
  type        = string
  default     = ""
}

# ============================================================
# MONITORING SETTINGS
# ============================================================

variable "enable_monitoring" {
  description = "Enable CloudWatch monitoring and alarms"
  type        = bool
  default     = true
}