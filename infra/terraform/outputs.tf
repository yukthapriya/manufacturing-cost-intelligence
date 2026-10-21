output "raw_bucket_name" {
  description = "Raw landing bucket. SOURCE_URI=s3://<this>/source, RAW_URI=s3://<this>/raw."
  value       = aws_s3_bucket.raw.bucket
}

output "raw_bucket_arn" {
  description = "ARN of the raw landing bucket."
  value       = aws_s3_bucket.raw.arn
}

output "pipeline_role_arn" {
  description = "IAM role for pipeline workloads; annotate ServiceAccount mci-runner with it (eks.amazonaws.com/role-arn)."
  value       = aws_iam_role.pipeline.arn
}

output "rds_address" {
  description = "RDS hostname for WAREHOUSE_HOST (null when create_rds = false)."
  value       = try(aws_db_instance.warehouse[0].address, null)
}

output "rds_port" {
  description = "RDS port for WAREHOUSE_PORT (null when create_rds = false)."
  value       = try(aws_db_instance.warehouse[0].port, null)
}
