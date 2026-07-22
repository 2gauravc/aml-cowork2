#!/usr/bin/env bash
set -euo pipefail

repository_url="$1"
repository_branch="$2"
domain_name="$3"

app_dir="/opt/aml-cowork2"
compose_plugin_version="v2.29.7"

dnf update -y
dnf install -y docker git curl
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
if [[ ! -f .env ]]; then
  cp .env.example .env
fi

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "${key}" "${value}" >> .env
  fi
}

# Operators add live API keys through Session Manager after bootstrap. Keep this
# file private and never commit it to the repository.
upsert_env "DEMO_MODE" "true"
upsert_env "DOMAIN_NAME" "${domain_name}"
chmod 600 .env

docker compose up --build --detach
