# Terraform Variables for Campus Medical Assistance AWS Deployment
#
# Copy terraform.tfvars.example to terraform.tfvars and customize values

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "emergency-response"
}

variable "environment" {
  description = "Environment name (development, staging, production)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "Environment must be development, staging, or production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to use (2-3)"
  type        = number
  default     = 2

  validation {
    condition     = contains([2, 3], var.az_count)
    error_message = "AZ count must be 2 or 3."
  }
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

# Database configuration
variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Maximum allocated storage in GB for autoscaling"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "emergency"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "admin"
}

# Redis configuration
variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

# ACM Certificate ARN for HTTPS
variable "acm_certificate_arn" {
  description = "ACM certificate ARN for ALB HTTPS listener (must be in us-east-1 for CloudFront, or same region as ALB)"
  type        = string
  default     = ""
}

# Container configuration
variable "api_cpu" {
  description = "CPU units for API task (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory in MiB for API task (512, 1024, 2048, 4096, 8192, 16384, 30720)"
  type        = number
  default     = 1024
}

variable "worker_cpu" {
  description = "CPU units for worker task"
  type        = number
  default     = 256
}

variable "worker_memory" {
  description = "Memory in MiB for worker task"
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Desired count of API tasks"
  type        = number
  default     = 2
}

variable "worker_desired_count" {
  description = "Desired count of worker tasks"
  type        = number
  default     = 1
}

# Domain configuration (optional)
variable "domain_name" {
  description = "Custom domain name (optional, for Route53)"
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route53 hosted zone ID for custom domain"
  type        = string
  default     = ""
}

# Notification configuration
variable "campus_emergency_phone" {
  description = "Campus emergency phone number (E.164 format)"
  type        = string
  default     = ""
}

variable "backup_phone" {
  description = "Backup phone number (E.164 format)"
  type        = string
  default     = ""
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}