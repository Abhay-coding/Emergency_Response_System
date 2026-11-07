# ALB Module Variables

variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "target_group_config" {
  description = "Target group configuration"
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
}

variable "certificate_arn" {
  description = "ACM Certificate ARN for HTTPS"
  type        = string
}

variable "domain_name" {
  description = "Custom domain name for ALB"
  type        = string
  default     = ""
}

variable "access_logs_bucket" {
  description = "S3 bucket for ALB access logs"
  type        = string
  default     = ""
}

variable "enable_waf" {
  description = "Enable WAF"
  type        = bool
  default     = false
}