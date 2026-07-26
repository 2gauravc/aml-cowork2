#!/usr/bin/env bash
# Deploy the HTTP EC2 demo. Application credentials must already exist in AWS
# Secrets Manager; this script passes only the secret ARN to CloudFormation.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
template_file="${project_root}/infrastructure/cloudformation/ec2-demo.yml"

stack_name="aml-cowork2-demo"
secret_arn=""
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
s3_bucket="onbo-bkt"
s3_prefix=""
kyc_cache_bucket="onbo-bkt"
kyc_cache_prefix="kyc-cache"
secret_kms_key_arn=""
repository_branch="main"

usage() {
  cat <<'USAGE'
Usage:
  infrastructure/ec2/deploy.sh --secret-arn ARN [options]

Required:
  --secret-arn ARN             Existing Secrets Manager JSON secret ARN.

Options:
  --region REGION              AWS Region (or set AWS_REGION/AWS_DEFAULT_REGION).
  --stack-name NAME            CloudFormation stack name (default: aml-cowork2-demo).
  --s3-bucket NAME             Document bucket (default: onbo-bkt).
  --s3-prefix PREFIX           Optional document bucket prefix.
  --kyc-cache-bucket NAME      KYC cache bucket (default: onbo-bkt).
  --kyc-cache-prefix PREFIX    KYC cache prefix (default: kyc-cache).
  --secret-kms-key-arn ARN     Customer-managed KMS key for the secret, if applicable.
  --repository-branch BRANCH   Branch cloned by EC2 (default: main).
  -h, --help                   Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secret-arn) secret_arn="${2:?--secret-arn requires a value}"; shift 2 ;;
    --region) region="${2:?--region requires a value}"; shift 2 ;;
    --stack-name) stack_name="${2:?--stack-name requires a value}"; shift 2 ;;
    --s3-bucket) s3_bucket="${2:?--s3-bucket requires a value}"; shift 2 ;;
    --s3-prefix) s3_prefix="${2:?--s3-prefix requires a value}"; shift 2 ;;
    --kyc-cache-bucket) kyc_cache_bucket="${2:?--kyc-cache-bucket requires a value}"; shift 2 ;;
    --kyc-cache-prefix) kyc_cache_prefix="${2:?--kyc-cache-prefix requires a value}"; shift 2 ;;
    --secret-kms-key-arn) secret_kms_key_arn="${2:?--secret-kms-key-arn requires a value}"; shift 2 ;;
    --repository-branch) repository_branch="${2:?--repository-branch requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${secret_arn}" ]]; then
  echo "--secret-arn is required." >&2
  usage >&2
  exit 2
fi
if [[ -z "${region}" ]]; then
  echo "Set --region, AWS_REGION, or AWS_DEFAULT_REGION." >&2
  exit 2
fi

command -v aws >/dev/null || { echo "AWS CLI v2 is required." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required for the final health check." >&2; exit 1; }

# Verify deployer access and secret existence without retrieving secret contents.
aws sts get-caller-identity --region "${region}" >/dev/null
aws secretsmanager describe-secret --region "${region}" --secret-id "${secret_arn}" >/dev/null
aws cloudformation validate-template --region "${region}" --template-body "file://${template_file}" >/dev/null

parameters=(
  "ApplicationSecretArn=${secret_arn}"
  "S3BucketName=${s3_bucket}"
  "S3Prefix=${s3_prefix}"
  "KycCacheBucketName=${kyc_cache_bucket}"
  "KycCachePrefix=${kyc_cache_prefix}"
  "RepositoryBranch=${repository_branch}"
)
if [[ -n "${secret_kms_key_arn}" ]]; then
  parameters+=("SecretKmsKeyArn=${secret_kms_key_arn}")
fi

aws cloudformation deploy \
  --region "${region}" \
  --stack-name "${stack_name}" \
  --template-file "${template_file}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${parameters[@]}"

application_url="$(aws cloudformation describe-stacks \
  --region "${region}" \
  --stack-name "${stack_name}" \
  --query "Stacks[0].Outputs[?OutputKey=='ApplicationUrl'].OutputValue | [0]" \
  --output text)"
instance_id="$(aws cloudformation describe-stacks \
  --region "${region}" \
  --stack-name "${stack_name}" \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue | [0]" \
  --output text)"

echo "Stack deployed. Waiting for ${application_url} to become healthy..."
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --connect-timeout 5 "${application_url}/" > /dev/null; then
    echo "Deployment complete: ${application_url}"
    echo "Session Manager: aws ssm start-session --region ${region} --target ${instance_id}"
    exit 0
  fi
  sleep 10
done

echo "The stack was created, but the app did not become healthy within 10 minutes." >&2
echo "Inspect bootstrap logs with: aws ssm start-session --region ${region} --target ${instance_id}" >&2
exit 1
