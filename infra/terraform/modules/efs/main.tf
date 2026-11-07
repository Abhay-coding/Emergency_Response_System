# EFS Module for Campus Medical Assistance
# Creates EFS file system for persistent uploads storage

# ============================================================
# EFS FILE SYSTEM
# ============================================================

resource "aws_efs_file_system" "main" {
  creation_token = "${var.project_name}-${var.environment}-efs"

  encrypted  = var.encrypted
  kms_key_id = var.kms_key_id

  performance_mode = var.performance_mode
  throughput_mode  = var.throughput_mode
  provisioned_throughput_in_mibps = var.provisioned_throughput_in_mibps

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-efs"
    Environment = var.environment
  }
}

# ============================================================
# EFS MOUNT TARGETS
# ============================================================

resource "aws_efs_mount_target" "main" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = var.security_group_ids

  ip_address = cidrhost(var.private_subnet_ids[count.index], 10)
}

# ============================================================
# EFS ACCESS POINT
# ============================================================

resource "aws_efs_access_point" "uploads" {
  file_system_id = aws_efs_file_system.main.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/uploads"

    creation_info {
      owner_uid = 1000
      owner_gid = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-uploads-ap"
    Environment = var.environment
  }
}

# ============================================================
# EFS BACKUP POLICY
# ============================================================

resource "aws_efs_backup_policy" "main" {
  file_system_id = aws_efs_file_system.main.id

  backup_policy {
    status = "ENABLED"
  }
}

# ============================================================
# OUTPUTS
# ============================================================

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