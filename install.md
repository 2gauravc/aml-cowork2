# Install and run the app

## 1. Run locally in GitHub Codespaces or another development environment

### Clone and prepare the repository

```bash
git clone https://github.com/2gauravc/aml-cowork2.git
cd aml-cowork2
python -m pip install -r requirements.lock
```

### Set up `.env`

Copy the example file, then add the credentials needed for live mode. Keep
`.env` private: it is ignored by Git and must never be committed.

```bash
cp .env.example .env
```

Set `DEMO_MODE=false` to run live workflows. The required credentials and their
sources are:

- `KYCCLIENTID` and `KYCCLIENTSECRET` — request KYC sandbox/API access from
  [Know Your Customer Developers](https://knowyourcustomer.com/developers/access/).
  Leave `KYCBASEURL` set to the sandbox URL unless KYC supplies a different API
  base URL.
- `OPENAI_API_KEY` — create a project API key in the
  [OpenAI Platform](https://platform.openai.com/api-keys).
- `TAVILY_API_KEY` — create an API key in the [Tavily dashboard](https://app.tavily.com/).
- `BRAVE_API_KEY` — create a Search API key in the
  [Brave Search API dashboard](https://api.search.brave.com/app/keys).

The S3 settings are optional for local development. Configure them when you
need durable storage:

- `KYC_CACHE_S3_BUCKET` stores cached KYC API responses, avoiding repeated API
  requests for the same company.
- `S3_DOCUMENT_BUCKET` stores generated and uploaded documents outside the app
  container, so they survive a restart.
- `CDD_STATE_S3_BUCKET` stores completed CDD case snapshots. Leave it blank to
  reuse `KYC_CACHE_S3_BUCKET` with a separate prefix.

Use AWS credentials from your normal local AWS profile. Do not put static AWS
access keys in `.env`.

### Run the app

```bash
python -m uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
```

Open the forwarded port or `http://localhost:8000`.

## 2. Deploy the app on AWS EC2

The repository includes a CloudFormation-based EC2 deployment for an internal
demo environment.

1. In AWS Secrets Manager, create a JSON secret using
   [`infrastructure/ec2/secrets.example.json`](infrastructure/ec2/secrets.example.json)
   as the template. Replace the placeholders and keep the secret ARN. It must
   contain `KYCCLIENTID`, `KYCCLIENTSECRET`, `OPENAI_API_KEY`, `TAVILY_API_KEY`,
   and `BRAVE_API_KEY`.

   Use Secrets Manager rather than an `.env` file on EC2: the instance receives
   the values at bootstrap through its IAM role, so credentials are not stored
   in the repository, baked into an image, or manually copied onto the server.
   It also supports controlled access, auditing, rotation, and KMS encryption.
   Do not add `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or
   `AWS_SESSION_TOKEN`; the EC2 instance role supplies temporary AWS
   credentials.

2. Ensure the deployer can create the CloudFormation, EC2, IAM, and networking
   resources. Then run:

   ```bash
   ./infrastructure/ec2/deploy.sh \
     --region us-east-1 \
     --secret-arn arn:aws:secretsmanager:us-east-1:123456789012:secret:demo/amlcowork-xxxxx
   ```

   By default, generated/uploaded documents use `onbo-bkt`, and the KYC cache
   uses `onbo-bkt/kyc-cache/`. Provide the S3 flags only when you need different
   buckets or prefixes. The script validates the deployment inputs, deploys the
   stack, waits for the health check, then prints the application URL and an SSM
   Session Manager command.

This deployment is HTTP-only and intended for demos; do not use it for
production or sensitive customer traffic without the controls described in
[`docs/deployment/ec2-demo.md`](docs/deployment/ec2-demo.md).

## 3. Install the Codex CLI

Install Codex in your GitHub Codespaces VM:

```bash
npm install -g @openai/codex
```

Start Codex and sign in with your ChatGPT account when prompted:

```bash
codex
```

When authenticating from a cloud VM such as GitHub Codespaces, replace
`localhost` in the return URL with the Codespaces hostname shown in the Ports
panel.

### Install supporting tools

```bash
sudo apt update
sudo apt install -y ripgrep
sudo apt install -y bubblewrap
npm install -g playwright
```
