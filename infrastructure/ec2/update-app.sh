#!/usr/bin/env bash
# Update the EC2 demo application to a remote branch and rebuild its Compose stack.
set -euo pipefail

app_dir="/opt/aml-cowork2"
branch="main"

usage() {
  cat <<'USAGE'
Usage: infrastructure/ec2/update-app.sh [options]

Run this script on the EC2 instance, normally as root through an SSM session.

Options:
  --app-dir PATH       Application checkout (default: /opt/aml-cowork2).
  --branch BRANCH      Remote origin branch to deploy (default: main).
  -h, --help           Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="${2:?--app-dir requires a value}"; shift 2 ;;
    --branch) branch="${2:?--branch requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root (for example: sudo -i)." >&2
  exit 1
fi
if [[ ! -d "${app_dir}/.git" ]]; then
  echo "No Git checkout found at ${app_dir}." >&2
  exit 1
fi
if [[ ! -f "${app_dir}/docker-compose.yml" ]]; then
  echo "No docker-compose.yml found at ${app_dir}." >&2
  exit 1
fi
command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required for the health check." >&2; exit 1; }

cd "${app_dir}"
git fetch --depth 1 origin "${branch}"
git checkout --force "origin/${branch}"
docker compose up --build --detach --wait
curl --fail --silent --show-error http://127.0.0.1/

echo "Deployment complete: $(git rev-parse --short HEAD)"
