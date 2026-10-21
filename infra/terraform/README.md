# AWS infrastructure (Terraform)

Optional cloud footprint for the Manufacturing Cost Intelligence Platform. The
project runs end-to-end locally (docker compose / kind) without any of this.

## Cost

**Nothing is created unless you run `terraform apply`.** `init`, `validate`
and `plan` are free. With defaults (`create_rds = false`) apply creates only:

| Resource | Approx. cost |
|----------|--------------|
| S3 bucket (versioned, SSE-S3, lifecycle) | pennies/month at demo volumes |
| IAM role + policy | free |

With `create_rds = true` add a `db.t4g.micro` PostgreSQL 15 instance with 20 GiB
gp3 (roughly USD 12-15/month on-demand in us-east-1; free-tier eligible on new
accounts). `skip_final_snapshot = true` and `deletion_protection = false` are
demo settings so `terraform destroy` cleans up completely; change both before
storing anything you care about.

## What it creates

- **Raw landing bucket**: public access fully blocked, ACLs disabled, versioning,
  SSE-S3, TLS-only bucket policy. Lifecycle on `raw/`: STANDARD_IA after 30 days,
  expire after 365 (noncurrent versions after 30). Layout:
  `s3://<bucket>/source/` (`SOURCE_URI`) and `s3://<bucket>/raw/` (`RAW_URI`).
- **Pipeline IAM role**: list + get/put/delete on `source/*` and `raw/*` only.
  Trust is IRSA when `eks_oidc_provider_arn` is set (only
  `system:serviceaccount:mci:mci-runner`), otherwise `trusted_principal_arns`
  (e.g. an MWAA execution role), otherwise the account root.
- **RDS PostgreSQL 15** (optional): encrypted, private, reachable on 5432 only
  from `db_allowed_cidr`.

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # gitignored
export TF_VAR_db_password='...'                # only if create_rds = true
terraform init
terraform plan -out tfplan
terraform apply tfplan
terraform output
terraform destroy                              # when done
```

Wire the outputs into `k8s/overlays/prod`: `rds_address` -> `WAREHOUSE_HOST`
(and the `postgres` ExternalName Service), `raw_bucket_name` -> `SOURCE_URI` /
`RAW_URI`, `pipeline_role_arn` -> the `mci-runner` IRSA annotation.

## Running on Amazon MWAA instead of self-managed Airflow

The DAGs are written to run unchanged on MWAA (Airflow 2.10 is supported):

1. **DAGs**: sync `airflow/dags/` plus the project packages (`common/`,
   `ingestion/`, `quality/`, `close/`, `exporter/`, `data_generator/`) to the
   environment's S3 `dags/` prefix. MWAA puts the DAGs folder on `PYTHONPATH`,
   so the packages import as in the image.
2. **Dependencies**: upload `requirements.txt` (with the Airflow 2.10.5
   constraints line, `-c https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.11.txt`)
   and point the environment at its S3 object version. dbt conflicts with
   Airflow's pins, so do **not** install it into MWAA's environment: either
   build a venv in a `startup.sh` script, or (preferred) run dbt as a container.
3. **Execution mode**: set `EXECUTION_MODE=k8s`. Heavy steps then run as
   `KubernetesPodOperator` tasks on an EKS cluster using the `mci-*` images from
   ECR. MWAA needs an EKS kubeconfig in the DAGs bucket and its execution role
   mapped to a Kubernetes identity with the `mci-runner` Role permissions
   (aws-auth / EKS access entries). The pods themselves get S3 access via IRSA
   from this module. Alternative without EKS: `EcsRunTaskOperator` on Fargate
   with the same images and the pipeline role as task role.
4. **Config/secrets**: put non-secret values in MWAA environment configuration
   / Airflow Variables, and `WAREHOUSE_PASSWORD` / `SLACK_WEBHOOK_URL` in AWS
   Secrets Manager via the Secrets Manager secrets backend.
5. **Networking**: MWAA runs in private subnets of the same VPC; include those
   subnets' CIDR in `db_allowed_cidr`.
