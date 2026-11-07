# Terraform Configuration for Campus Medical Assistance on AWS
# This file configures the provider and backend

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

  # Remote state backend (configure after first apply)
  # backend "s3" {
  #   bucket         = "emergency-response-terraform-state"
  #   key            = "prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "emergency-response"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# Generate random suffix for unique resource names
resource "random_id" "suffix" {
  byte_length = 4
}

# Generate TLS private key for RDS (if needed for IAM auth)
resource "tls_private_key" "rds" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

# ============================================================
# MODULES
# ============================================================

module "vpc" {
  source  = "./modules/vpc"
  version = "0.0.1"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_cidr           = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  database_subnet_cidrs = var.database_subnet_cidrs
  enable_nat_gateway   = var.enable_nat_gateway
  single_nat_gateway   = var.single_nat_gateway
}

module "security_groups" {
  source  = "./modules/security-groups"
  version = "0.0.1"

  project_name   = var.project_name
  environment    = var.environment
  vpc_id         = module.vpc.vpc_id
  alb_cidr_blocks = var.alb_cidr_blocks
}

module "rds" {
  source  = "./modules/rds"
  version = "0.0.1"

  project_name           = var.project_name
  environment            = var.environment
  vpc_id                 = module.vpc.vpc_id
  database_subnet_ids    = module.vpc.database_subnet_ids
  security_group_ids     = [module.security_groups.rds_sg_id]
  db_instance_class      = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  max_allocated_storage  = var.db_max_allocated_storage
  engine_version         = var.db_engine_version
  username               = var.db_username
  password               = var.db_password
  backup_retention_period = var.db_backup_retention_period
  deletion_protection    = var.db_deletion_protection
  multi_az               = var.db_multi_az
  publicly_accessible    = false
}

module "elasticache" {
  source  = "./modules/elasticache"
  version = "0.0.1"

  project_name          = var.project_name
  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  security_group_ids    = [module.security_groups.elasticache_sg_id]
  node_type             = var.elasticache_node_type
  num_cache_nodes       = var.elasticache_num_nodes
  engine_version        = var.elasticache_engine_version
  parameter_group_name  = var.elasticache_parameter_group
  at_rest_encryption    = true
  transit_encryption    = true
  auth_token            = var.elasticache_auth_token
}

module "ecs" {
  source  = "./modules/ecs"
  version = "0.0.1"

  project_name              = var.project_name
  environment               = var.environment
  vpc_id                    = module.vpc.vpc_id
  private_subnet_ids        = module.vpc.private_subnet_ids
  security_group_ids        = [module.security_groups.ecs_tasks_sg_id]
  alb_target_group_arns     = module.alb.target_group_arns
  container_image           = var.container_image
  cpu                       = var.ecs_cpu
  memory                    = var.ecs_memory
  desired_count             = var.ecs_desired_count
  max_capacity              = var.ecs_max_capacity
  min_capacity              = var.ecs_min_capacity
  execution_role_arn        = module.iam.ecs_execution_role_arn
  task_role_arn             = module.iam.ecs_task_role_arn
  log_group_name            = "/ecs/${var.project_name}-api"
  environment_variables     = var.ecs_environment_variables
  secrets                   = var.ecs_secrets
  health_check_path         = "/health"
  health_check_interval     = 30
  health_check_timeout      = 10
  health_check_retries      = 3
  health_check_start_period = 60
}

module "ecs_worker" {
  source  = "./modules/ecs-worker"
  version = "0.0.1"

  project_name              = var.project_name
  environment               = var.environment
  vpc_id                    = module.vpc.vpc_id
  private_subnet_ids        = module.vpc.private_subnet_ids
  security_group_ids        = [module.security_groups.ecs_tasks_sg_id]
  container_image           = var.container_image
  cpu                       = var.worker_cpu
  memory                    = var.worker_memory
  desired_count             = var.worker_desired_count
  execution_role_arn        = module.iam.ecs_execution_role_arn
  task_role_arn             = module.iam.ecs_task_role_arn
  log_group_name            = "/ecs/${var.project_name}-worker"
  environment_variables     = var.worker_environment_variables
  secrets                   = var.worker_secrets
}

module "alb" {
  source  = "./modules/alb"
  version = "0.0.1"

  project_name       = var.project_name
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  security_group_ids = [module.security_groups.alb_sg_id]
  target_group_config = var.alb_target_group_config
  certificate_arn    = var.alb_certificate_arn
  domain_name        = var.alb_domain_name
}

module "iam" {
  source  = "./modules/iam"
  version = "0.0.1"

  project_name       = var.project_name
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  db_instance_arn    = module.rds.db_instance_arn
  redis_cluster_arn  = module.elasticache.replication_group_arn
  efs_file_system_id = module.efs.file_system_id
  efs_access_point_id = module.efs.access_point_id
  sqs_queue_arn      = module.sqs.queue_arn
  sns_topic_arn      = module.sns.topic_arn
}

module "efs" {
  source  = "./modules/efs"
  version = "0.0.1"

  project_name    = var.project_name
  environment     = var.environment
  vpc_id          = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_ids = [module.security_groups.efs_sg_id]
  encrypted       = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
}

module "sqs" {
  source  = "./modules/sqs"
  version = "0.0.1"

  project_name    = var.project_name
  environment     = var.environment
  queue_name      = "${var.project_name}-notifications"
  visibility_timeout_seconds = 300
  message_retention_seconds = 1209600 # 14 days
  dead_letter_queue_config = {
    max_receive_count = 3
  }
}

module "sns" {
  source  = "./modules/sns"
  version = "0.0.1"

  project_name = var.project_name
  environment  = var.environment
  topic_name   = "${var.project_name}-alerts"
}

module "secrets" {
  source  = "./modules/secrets"
  version = "0.0.1"

  project_name = var.project_name
  environment  = var.environment
  jwt_secret   = var.jwt_secret
  database_url = module.rds.database_url
}

module "cloudwatch" {
  source  = "./modules/cloudwatch"
  version = "0.0.1"

  project_name       = var.project_name
  environment        = var.environment
  log_group_names    = ["/ecs/${var.project_name}-api", "/ecs/${var.project_name}-worker"]
  alarm_sns_topic_arn = module.sns.topic_arn
}

# ============================================================
# OUTPUTS
# ============================================================

output "vpc_id" {
  value       = module.vpc.vpc_id
  description = "VPC ID"
}

output "alb_dns_name" {
  value       = module.alb.alb_dns_name
  description = "ALB DNS Name"
}

output "alb_arn" {
  value       = module.alb.alb_arn
  description = "ALB ARN"
}

output "database_endpoint" {
  value       = module.rds.db_endpoint
  description = "RDS Database Endpoint"
  sensitive   = true
}

output "database_url" {
  value       = module.rds.database_url
  description = "Database Connection URL"
  sensitive   = true
}

output "redis_endpoint" {
  value       = module.elasticache.primary_endpoint
  description = "ElastiCache Redis Endpoint"
}

output "ecs_cluster_name" {
  value       = module.ecs.cluster_name
  description = "ECS Cluster Name"
}

output "ecs_service_name" {
  value       = module.ecs.service_name
  description = "ECS Service Name (API)"
}

output "ecs_worker_service_name" {
  value       = module.ecs_worker.service_name
  description = "ECS Worker Service Name"
}

output "efs_file_system_id" {
  value       = module.efs.file_system_id
  description = "EFS File System ID"
}

output "efs_access_point_id" {
  value       = module.efs.access_point_id
  description = "EFS Access Point ID"
}

output "sqs_queue_url" {
  value       = module.sqs.queue_url
  description = "SQS Queue URL"
}

output "sns_topic_arn" {
  value       = module.sns.topic_arn
  description = "SNS Topic ARN"
}