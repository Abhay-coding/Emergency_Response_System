# SQS Module Variables

variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "queue_name" {
  description = "SQS queue name"
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "Visibility timeout in seconds"
  type        = number
  default     = 300
}

variable "message_retention_seconds" {
  description = "Message retention in seconds"
  type        = number
  default     = 1209600
}

variable "dead_letter_queue_config" {
  description = "Dead letter queue configuration"
  type = object({
    max_receive_count = number
  })
  default = {
    max_receive_count = 3
  }
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for queue policy"
  type        = string
  default     = ""
}