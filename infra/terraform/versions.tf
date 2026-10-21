terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state by default. For shared use, configure a remote backend, e.g.:
  # backend "s3" {
  #   bucket         = "<tf-state-bucket>"
  #   key            = "mci/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "<tf-lock-table>"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = "manufacturing-cost-intelligence"
        Environment = var.environment
        ManagedBy   = "terraform"
      },
      var.extra_tags,
    )
  }
}
