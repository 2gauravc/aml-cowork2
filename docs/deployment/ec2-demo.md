# EC2 demo deployment

This guide provisions one `t3.medium` EC2 instance for an internal/demo
deployment. It is intentionally not a production architecture: the endpoint is
HTTP-only on an Elastic IP, and sessions, active CDD jobs, and reviewer state
are held in process memory.

## Prerequisites

- An AWS account with permission to create CloudFormation, EC2, IAM, Elastic
  IP, and networking resources in the target region. The template creates its
  own VPC, public subnet, Internet Gateway, and route table.
- AWS CLI credentials for the deployer.
- One existing Secrets Manager JSON secret containing `KYCCLIENTID`,
  `KYCCLIENTSECRET`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, and `BRAVE_API_KEY`.
  Start with [`infrastructure/ec2/secrets.example.json`](../../infrastructure/ec2/secrets.example.json).
- An existing S3 bucket for generated documents, if document storage is
  required. The EC2 role is scoped to the configured bucket and prefix.

Do not put AWS access keys in the application secret. The EC2 instance role
provides temporary credentials for S3, Secrets Manager, and Systems Manager.

## Deploy

From the repository root, run:

```bash
./infrastructure/ec2/deploy.sh \
  --region us-east-1 \
  --secret-arn arn:aws:secretsmanager:us-east-1:123456789012:secret:demo/amlcowork-xxxxx
```

The script validates the CloudFormation template and secret metadata, creates
or updates the stack, waits for the HTTP health check, and prints the public
URL and an SSM Session Manager command. `main` is the default repository
branch. Use `--repository-branch` only when deliberately deploying another
pushed branch, for example an isolated test branch.

The deployment is HTTP-only and uses no DNS name or TLS certificate. Do not
use it with production or sensitive customer traffic.

## Runtime configuration

Bootstrap downloads the selected repository branch, fetches the application
secret through the EC2 role, and creates `/opt/aml-cowork2/.env` with
`DEMO_MODE=false`, the configured S3 location, and restrictive permissions.
Normal, non-secret configuration remains in `.env.example`, including
`KYCBASEURL` and optional OpenAI model overrides. The application derives the
KYC token endpoint from `KYCBASEURL`.

No SSH ingress is opened. Use Systems Manager for host access:

```bash
aws ssm start-session --region us-east-1 --target <instance-id>
```

## Smoke test

1. Open the printed `http://<elastic-ip>` URL and confirm the CDD tab loads.
2. Run a live CDD case and confirm documents use the configured S3 location.
3. In the SSM session, run `cd /opt/aml-cowork2 && docker compose ps` to
   confirm both services are healthy.

## Updating the application

The initial bootstrap runs when an EC2 instance is first launched. On the
current single-instance template, changing CloudFormation user data restarts an
existing EBS-backed instance but does not rerun its Linux bootstrap script.
Until automated instance replacement is added, update the running application
through an SSM session after the target branch is pushed:

```bash
sudo -i
cd /opt/aml-cowork2
git fetch --depth 1 origin main
git checkout --force origin/main
docker compose up --build --detach --wait
curl --fail http://127.0.0.1/
```

This does not change the existing runtime `.env`. Do not edit it to add static
AWS credentials.

## Teardown

Delete the stack when the demo is finished:

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name aml-cowork2-demo
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name aml-cowork2-demo
```

This releases the Elastic IP and terminates the EC2 instance. It does not
delete the existing S3 document bucket or Secrets Manager secret.
