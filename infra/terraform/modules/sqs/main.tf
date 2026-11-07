# SQS Module for Campus Medical Assistance
# Creates SQS queue for notification processing with dead letter queue

# ============================================================
# DEAD LETTER QUEUE
# ============================================================

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.project_name}-${var.environment}-notifications-dlq"
  message_retention_seconds = var.message_retention_seconds
  fifo_queue                = false
  content_based_deduplication = false

  tags = {
    Name        = "${var.project_name}-${var.environment}-notifications-dlq"
    Environment = var.environment
  }
}

# ============================================================
# MAIN QUEUE
# ============================================================

resource "aws_sqs_queue" "main" {
  name                      = var.queue_name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20
  fifo_queue                 = false
  content_based_deduplication = false

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = var.dead_letter_queue_config.max_receive_count
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-notifications"
    Environment = var.environment
  }
}

# ============================================================
# QUEUE POLICY (allow SNS to send messages)
# ============================================================

resource "aws_sqs_queue_policy" "main" {
  queue_url = aws_sqs_queue.main.id
  policy    = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sns.amazonaws.com"
        }
        Action = "sqs:SendMessage"
        Resource = aws_sqs_queue.main.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = var.sns_topic_arn
          }
        }
      }
    ]
  })
}

# ============================================================
# OUTPUTS
# ============================================================

output "queue_url" {
  value       = aws_sqs_queue.main.url
  description = "SQS Queue URL"
}

output "queue_arn" {
  value       = aws_sqs_queue.main.arn
  description = "SQS Queue ARN"
}

output "dead_letter_queue_url" {
  value       = aws_sqs_queue.dead_letter.url
  description = "Dead Letter Queue URL"
}

output "dead_letter_queue_arn" {
  value       = aws_sqs_queue.dead_letter.arn
  description = "Dead Letter Queue ARN"
}