
# Install and run the app on Github Codespaces VM

## Clone and prepare the repo 

```bash
git clone https://github.com/2gauravc/aml-cowork2.git
cd aml-cowork2
python -m pip install -r requirements.lock
```

### Set up .env 

Copy the example configuration and leave `DEMO_MODE=false`. 

```bash
cp .env.example .env
```


## Install Codex CLI

```bash
npm install -g @openai/codex
```

### Log in and authenticate Codex with your ChatGPT Plus/Pro account 

Start Codex (on linux terminal)

```bash
codex
```
Sign in with ChatGPT when prompted:

**Note:** When accessing the app from a Cloud VM (such as Github Codespaces), you will need to alter the default return URL. 
Replace `localhost`in the return URL with the machine's hostname (check under ports on your terminal screen).

### Install supporting tools

Install the supporting tools for codex CLI. 

```bash
sudo apt update
sudo apt install -y ripgrep
sudo apt install -y bubblewrap
npm install -g playwright
```


## Run the App 

```
cd aml-cowork2/
python -m uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
```

## Deploy the EC2 HTTP demo

The EC2 deployment is intentionally a temporary HTTP demo, served at a stable
Elastic IP. It has no DNS name or TLS certificate, so do not use it with
production or sensitive customer traffic.

1. Create one Secrets Manager JSON secret from
   [`infrastructure/ec2/secrets.example.json`](infrastructure/ec2/secrets.example.json).
   Replace every placeholder and retain the secret ARN. The secret contains
   `KYCCLIENTID`, `KYCCLIENTSECRET`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, and
   `BRAVE_API_KEY`.
   Do not add `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or
   `AWS_SESSION_TOKEN`; the EC2 instance role supplies temporary AWS credentials.
2. Ensure the deployer has permission to create the CloudFormation, EC2, IAM,
   and networking resources, then run:

   ```bash
   ./infrastructure/ec2/deploy.sh \
     --region us-east-1 \
     --secret-arn arn:aws:secretsmanager:us-east-1:821052193763:secret:demo/amlcowork-1YdyCI
   ```

   `KYCBASEURL` and OpenAI model selections remain normal versioned
   configuration in `.env.example`; the application derives its KYC token
   endpoint from `KYCBASEURL`. The deployment enables the persistent KYC cache
   in `onbo-bkt/kyc-cache/` by default. Use `--s3-bucket`, `--s3-prefix`,
   `--kyc-cache-bucket`, `--kyc-cache-prefix`, or `--secret-kms-key-arn` when
   those defaults do not apply. The script validates the template and secret
   metadata, deploys the stack, waits for the application health check, and
   prints the HTTP Elastic-IP URL and a Session Manager command.

The stack creates a least-privilege EC2 instance profile: scoped document and
KYC-cache S3 access, read access to only the specified application secret, and
Systems Manager access. Bootstrap reads the secret with that role and writes a
root-owned runtime `.env`; it never needs static AWS credentials.

