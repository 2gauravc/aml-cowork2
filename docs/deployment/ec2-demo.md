# EC2 demo deployment

This guide provisions a single `t3.medium` EC2 instance for an internal/demo deployment. It is intentionally not a production architecture: sessions, active CDD jobs, and reviewer state are held in process memory and are lost if the instance restarts.

## Prerequisites

- An AWS account, a VPC, and a **public subnet** with an Internet Gateway route.
- AWS CLI credentials that can create CloudFormation, EC2, IAM, and Elastic IP resources.
- A DNS name, such as `demo.example.com`. Caddy needs the name to obtain a browser-trusted HTTPS certificate.
- The deployment branch pushed to the configured repository. User data downloads `infrastructure/ec2/user-data.sh` from that branch.
- Optional: an existing S3 bucket/prefix for documents. The stack grants only the supplied bucket/prefix access to the EC2 role.

## Deploy

Create the stack from the repository root:

```bash
aws cloudformation deploy \
  --stack-name aml-cowork2-demo \
  --template-file infrastructure/cloudformation/ec2-demo.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    VpcId=vpc-0123456789abcdef0 \
    SubnetId=subnet-0123456789abcdef0 \
    DomainName=demo.example.com \
    RepositoryBranch=deploy/ec2-demo \
    S3BucketName=your-existing-document-bucket \
    S3Prefix=aml-cowork2/
```

Get the Elastic IP, then create a DNS `A` record from `DomainName` to that IP:

```bash
aws cloudformation describe-stacks \
  --stack-name aml-cowork2-demo \
  --query 'Stacks[0].Outputs' \
  --output table
```

Do not open port 22. The instance profile includes Systems Manager permissions, so access it with:

```bash
aws ssm start-session --target <instance-id>
```

## Configure the application

Bootstrap creates `/opt/aml-cowork2/.env` with `DEMO_MODE=true`, the supplied domain, and restrictive file permissions. Add live credentials only when ready:

```bash
sudo -i
cd /opt/aml-cowork2
nano .env
chmod 600 .env
docker compose up --detach
```

For demo mode, leave `DEMO_MODE=true`; no OpenAI, KYC, Tavily, or S3 credentials are required. For live mode, set `DEMO_MODE=false` and add the values from `.env.example`. Do not commit `.env` or copy it into the CloudFormation template, user data, or logs.

After DNS propagation, Caddy obtains the HTTPS certificate automatically. If DNS was created after Caddy started, retry with:

```bash
cd /opt/aml-cowork2
docker compose restart caddy
```

## Smoke test

1. Open `https://<your-domain>` and confirm the CDD tab loads.
2. Confirm the floating chat launcher opens on CDD and is hidden on other tabs.
3. In demo mode, select **Load Demo Case** and review the CDD and Case Review tabs.
4. In live mode, run a CDD case and confirm document actions use the configured S3 location.
5. Reboot the instance with `sudo reboot`, reconnect using Session Manager, and run `docker compose ps` to confirm both services restart.

## Update and rollback

To deploy a new application commit, update `RepositoryBranch` or recreate the stack after the branch is pushed, then on the instance run:

```bash
cd /opt/aml-cowork2
git fetch origin
git checkout <branch-or-commit>
docker compose up --build --detach
```

CloudFormation rollback applies to infrastructure failures. It does not preserve in-memory sessions or active jobs.

## Teardown

Delete the stack when the demo is finished:

```bash
aws cloudformation delete-stack --stack-name aml-cowork2-demo
aws cloudformation wait stack-delete-complete --stack-name aml-cowork2-demo
```

This releases the Elastic IP and terminates the EC2 instance. It does not delete the existing S3 document bucket.
