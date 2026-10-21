variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names and tags (e.g. dev, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]{2,16}$", var.environment))
    error_message = "environment must be 2-16 lowercase alphanumerics or hyphens."
  }
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "mci"
}

variable "raw_bucket_name" {
  description = "Globally unique name for the raw landing bucket. Null derives <prefix>-<env>-raw-<account_id>."
  type        = string
  default     = null
}

variable "raw_ia_transition_days" {
  description = "Days after which objects under raw/ move to STANDARD_IA."
  type        = number
  default     = 30
}

variable "raw_expiration_days" {
  description = "Days after which objects under raw/ expire."
  type        = number
  default     = 365
}

variable "force_destroy_bucket" {
  description = "Allow terraform destroy to delete a non-empty bucket (demo convenience; keep false for real data)."
  type        = bool
  default     = false
}

# --- IRSA ----------------------------------------------------------------

variable "eks_oidc_provider_arn" {
  description = "ARN of the EKS cluster's IAM OIDC provider. Null => the pipeline role trusts var.trusted_principal_arns instead of IRSA."
  type        = string
  default     = null
}

variable "k8s_namespace" {
  description = "Kubernetes namespace of the pipeline service account (IRSA condition)."
  type        = string
  default     = "mci"
}

variable "k8s_service_account" {
  description = "Kubernetes service account allowed to assume the pipeline role (IRSA condition)."
  type        = string
  default     = "mci-runner"
}

variable "trusted_principal_arns" {
  description = "IAM principal ARNs allowed to assume the pipeline role when IRSA is not used (e.g. an MWAA execution role or a CI role)."
  type        = list(string)
  default     = []
}

# --- RDS -----------------------------------------------------------------

variable "create_rds" {
  description = "Create an RDS PostgreSQL 15 instance for the warehouse."
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC for the RDS instance and its security group. Required when create_rds = true."
  type        = string
  default     = null
}

variable "db_subnet_ids" {
  description = "Private subnet IDs (>= 2 AZs) for the RDS subnet group. Required when create_rds = true."
  type        = list(string)
  default     = []
}

variable "db_allowed_cidr" {
  description = "CIDR allowed to reach Postgres on 5432 (e.g. the EKS node/pod CIDR or VPC CIDR)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GiB."
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "PostgreSQL major (or major.minor) version."
  type        = string
  default     = "15"
}

variable "db_name" {
  description = "Warehouse database name (WAREHOUSE_DB)."
  type        = string
  default     = "mfg_cost"
}

variable "db_username" {
  description = "Master username (WAREHOUSE_USER)."
  type        = string
  default     = "mci"
}

variable "db_password" {
  description = "Master password (WAREHOUSE_PASSWORD). Pass via TF_VAR_db_password, never commit it."
  type        = string
  default     = null
  sensitive   = true
}

variable "extra_tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}
