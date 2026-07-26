#!/usr/bin/env bash
set -euo pipefail

repository_url="$1"
repository_branch="$2"
application_secret_arn="$3"
s3_bucket_name="$4"
s3_prefix="$5"
aws_region="$6"

app_dir="/opt/aml-cowork2"
compose_plugin_version="v2.29.7"
bootstrap_log="/var/log/aml-cowork2-bootstrap.log"

exec > >(tee -a "${bootstrap_log}") 2>&1
trap 'status=$?; echo "AML Case Review bootstrap failed (exit ${status}). See ${bootstrap_log}."; exit "${status}"' ERR

if [[ -z "${application_secret_arn}" ]]; then
  echo "ApplicationSecretArn is required."
  exit 1
fi

dnf update -y
dnf install -y awscli2 docker git curl jq
systemctl enable --now docker

mkdir -p /usr/local/lib/docker/cli-plugins
curl --fail --location --retry 5 \
  "https://github.com/docker/compose/releases/download/${compose_plugin_version}/docker-compose-linux-x86_64" \
  --output /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

if [[ -d "${app_dir}/.git" ]]; then
  git -C "${app_dir}" fetch --depth 1 origin "${repository_branch}"
  git -C "${app_dir}" checkout --force "origin/${repository_branch}"
else
  git clone --depth 1 --branch "${repository_branch}" "${repository_url}" "${app_dir}"
fi

cd "${app_dir}"
secret_file="$(mktemp)"
trap 'rm -f "${secret_file}"' EXIT

# The AWS CLI obtains temporary credentials from the EC2 instance profile. Do
# not add AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY to this host or container.
aws secretsmanager get-secret-value \
  --region "${aws_region}" \
  --secret-id "${application_secret_arn}" \
  --query SecretString \
  --output text > "${secret_file}"

python3 - \
  "${secret_file}" \
  ".env.example" \
  ".env" \
  "${aws_region}" \
  "${s3_bucket_name}" \
  "${s3_prefix}" <<'PY'
import json
import re
import sys
from pathlib import Path

secret_path = Path(sys.argv[1])
example_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
region = sys.argv[4]
bucket = sys.argv[5]
prefix = sys.argv[6]

with secret_path.open(encoding="utf-8") as stream:
    secret = json.load(stream)

if not isinstance(secret, dict):
    raise SystemExit("Application secret must be a JSON object.")

key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
blocked_keys = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "DEMO_MODE",
}
for key, value in secret.items():
    if not key_pattern.fullmatch(key):
        raise SystemExit(f"Application secret contains an invalid environment key: {key!r}")
    if key in blocked_keys:
        raise SystemExit(f"Application secret must not include {key}; EC2 uses its instance role.")
    if not isinstance(value, (str, int, float, bool)):
        raise SystemExit(f"Application secret value for {key} must be a scalar.")
    if "\n" in str(value) or "\r" in str(value):
        raise SystemExit(f"Application secret value for {key} must not contain a newline.")

required_keys = {"KYCCLIENTID", "KYCCLIENTSECRET", "OPENAI_API_KEY", "TAVILY_API_KEY"}
missing_keys = sorted(key for key in required_keys if not str(secret.get(key, "")).strip())
if missing_keys:
    raise SystemExit("Application secret is missing required values: " + ", ".join(missing_keys))

runtime_values = {
    **{key: str(value) for key, value in secret.items()},
    "DEMO_MODE": "false",
    "AWS_REGION": region,
}
if bucket:
    runtime_values["S3_DOCUMENT_BUCKET"] = bucket
    runtime_values["S3_DOCUMENT_BUCKET_URL"] = f"https://{bucket}.s3.{region}.amazonaws.com"
if prefix:
    runtime_values["S3_DOCUMENT_PREFIX"] = prefix.strip("/")

existing_lines = example_path.read_text(encoding="utf-8").splitlines()
assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
rendered_lines = []
for line in existing_lines:
    match = assignment.match(line)
    if match and match.group(1) in runtime_values:
        continue
    rendered_lines.append(line)

def quote_dotenv(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

if rendered_lines and rendered_lines[-1]:
    rendered_lines.append("")
rendered_lines.append("# Runtime values loaded from AWS Secrets Manager during EC2 bootstrap.")
for key in sorted(runtime_values):
    rendered_lines.append(f"{key}={quote_dotenv(runtime_values[key])}")

output_path.write_text("\n".join(rendered_lines) + "\n", encoding="utf-8")
PY

chown root:root .env
chmod 600 .env

docker compose up --build --detach --wait
curl --fail --silent --show-error http://127.0.0.1/ > /dev/null
echo "AML Case Review bootstrap completed successfully."
