# EFS Module Outputs

output "file_system_id" {
  value       = aws_efs_file_system.main.id
  description = "EFS File System ID"
}

output "file_system_arn" {
  value       = aws_efs_file_system.main.arn
  description = "EFS File System ARN"
}

output "access_point_id" {
  value       = aws_efs_access_point.uploads.id
  description = "EFS Access Point ID"
}

output "access_point_arn" {
  value       = aws_efs_access_point.uploads.arn
  description = "EFS Access Point ARN"
}

output "mount_target_ids" {
  value       = aws_efs_mount_target.main[*].id
  description = "EFS Mount Target IDs"
}