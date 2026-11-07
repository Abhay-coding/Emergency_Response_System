# ECS Worker Module Variables

variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
}

variable "cluster_name" {
  description = "ECS Cluster name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "container_image" {
  description = "Docker image URI"
  type        = string
}

variable "cpu" {
  description = "CPU units for task"
  type        = string
  default     = "256"
}

variable "memory" {
  description = "Memory for task in MiB"
  type        = string
  default     = "512"
}

variable "desired_count" {
  description = "Desired number of tasks"
  type        = number
  default     = 1
}

variable "execution_role_arn" {
  description = "ECS execution role ARN"
  type        = string
}

variable "task_role_arn" {
  description = "ECS task role ARN"
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group name"
  type        = string
}

variable "environment_variables" {
  description = "Environment variables for container"
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secrets for container"
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = []
}