data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name            = "${var.name_prefix}-${var.environment}"
  raw_bucket_name = coalesce(var.raw_bucket_name, "${local.name}-raw-${data.aws_caller_identity.current.account_id}")
  use_irsa        = var.eks_oidc_provider_arn != null

  # "arn:aws:iam::123:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/ABC"
  #   -> "oidc.eks.us-east-1.amazonaws.com/id/ABC"
  oidc_issuer = local.use_irsa ? element(split("oidc-provider/", var.eks_oidc_provider_arn), 1) : ""
}

# ---------------------------------------------------------------------------
# Raw landing bucket
#   s3://<bucket>/source/...  synthetic source drop (SOURCE_URI)
#   s3://<bucket>/raw/...     immutable raw zone     (RAW_URI)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "raw" {
  bucket        = local.raw_bucket_name
  force_destroy = var.force_destroy_bucket
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    object_ownership = "BucketOwnerEnforced" # disables ACLs
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  # Versioning must be on before noncurrent-version rules apply.
  depends_on = [aws_s3_bucket_versioning.raw]

  rule {
    id     = "raw-tiering-and-expiry"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    transition {
      days          = var.raw_ia_transition_days
      storage_class = "STANDARD_IA"
    }

    expiration {
      days = var.raw_expiration_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Deny any non-TLS access.
data "aws_iam_policy_document" "raw_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [
      aws_s3_bucket.raw.arn,
      "${aws_s3_bucket.raw.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket = aws_s3_bucket.raw.id
  policy = data.aws_iam_policy_document.raw_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.raw]
}

# ---------------------------------------------------------------------------
# Pipeline IAM role (IRSA for mci-runner, or explicit trusted principals)
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "pipeline_trust" {
  dynamic "statement" {
    for_each = local.use_irsa ? [1] : []

    content {
      sid     = "EksIrsa"
      effect  = "Allow"
      actions = ["sts:AssumeRoleWithWebIdentity"]

      principals {
        type        = "Federated"
        identifiers = [var.eks_oidc_provider_arn]
      }

      condition {
        test     = "StringEquals"
        variable = "${local.oidc_issuer}:sub"
        values   = ["system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"]
      }

      condition {
        test     = "StringEquals"
        variable = "${local.oidc_issuer}:aud"
        values   = ["sts.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.trusted_principal_arns) > 0 ? [1] : []

    content {
      sid     = "TrustedPrincipals"
      effect  = "Allow"
      actions = ["sts:AssumeRole"]

      principals {
        type        = "AWS"
        identifiers = var.trusted_principal_arns
      }
    }
  }

  # Fallback so the document is never empty: only the account root (i.e.
  # IAM principals in this account that are explicitly granted sts:AssumeRole).
  dynamic "statement" {
    for_each = !local.use_irsa && length(var.trusted_principal_arns) == 0 ? [1] : []

    content {
      sid     = "AccountRoot"
      effect  = "Allow"
      actions = ["sts:AssumeRole"]

      principals {
        type        = "AWS"
        identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
      }
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name                 = "${local.name}-pipeline"
  description          = "Manufacturing Cost Intelligence pipeline workloads (land/load/export)."
  assume_role_policy   = data.aws_iam_policy_document.pipeline_trust.json
  max_session_duration = 3600
}

# Least privilege: list the bucket (scoped to the two prefixes) and
# read/write/delete objects under them. No bucket-level admin actions.
data "aws_iam_policy_document" "pipeline_s3" {
  statement {
    sid       = "ListPipelinePrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.raw.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["", "source/*", "raw/*", "source", "raw"]
    }
  }

  statement {
    sid     = "ObjectAccess"
    effect  = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = [
      "${aws_s3_bucket.raw.arn}/source/*",
      "${aws_s3_bucket.raw.arn}/raw/*",
    ]
  }
}

resource "aws_iam_policy" "pipeline_s3" {
  name        = "${local.name}-pipeline-s3"
  description = "Least-privilege access to the MCI raw landing bucket."
  policy      = data.aws_iam_policy_document.pipeline_s3.json
}

resource "aws_iam_role_policy_attachment" "pipeline_s3" {
  role       = aws_iam_role.pipeline.name
  policy_arn = aws_iam_policy.pipeline_s3.arn
}

# ---------------------------------------------------------------------------
# Optional warehouse: RDS for PostgreSQL 15
# ---------------------------------------------------------------------------
resource "aws_security_group" "db" {
  count = var.create_rds ? 1 : 0

  name        = "${local.name}-warehouse-db"
  description = "MCI warehouse Postgres"
  vpc_id      = var.vpc_id

  ingress {
    description = "Postgres from allowed CIDR"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.db_allowed_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    precondition {
      condition     = var.vpc_id != null && length(var.db_subnet_ids) >= 2
      error_message = "create_rds = true requires vpc_id and at least two db_subnet_ids."
    }
  }
}

resource "aws_db_subnet_group" "db" {
  count = var.create_rds ? 1 : 0

  name       = "${local.name}-warehouse"
  subnet_ids = var.db_subnet_ids
}

resource "aws_db_instance" "warehouse" {
  count = var.create_rds ? 1 : 0

  identifier     = "${local.name}-warehouse"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.db[0].name
  vpc_security_group_ids = [aws_security_group.db[0].id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period    = 1
  auto_minor_version_upgrade = true
  deletion_protection        = false
  skip_final_snapshot        = true # demo only; set false + final_snapshot_identifier for real data
  apply_immediately          = true

  lifecycle {
    precondition {
      condition     = var.db_password != null
      error_message = "create_rds = true requires db_password (set TF_VAR_db_password)."
    }
  }
}
