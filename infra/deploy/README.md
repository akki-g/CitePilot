# CitePilot on an existing EC2 website

This deployment keeps CitePilot isolated behind the web server already serving your personal site.
The recommended public address is a first-party subdomain such as
`https://citepilot.example.com`. Only the container web gateway binds to the host, on
`127.0.0.1:3001`; FastAPI, Postgres, Neo4j, and Redis remain private Docker services.

The CI/CD path uses GitHub OpenID Connect to obtain short-lived AWS credentials, then AWS Systems
Manager Run Command to deploy an exact commit. It does not store an AWS access key or EC2 SSH key
in GitHub.

For a full explanation of the container topology, CI/CD lifecycle, and the shared Docker network
needed when the personal website's reverse proxy is containerized, see
`guides/DEVOPS_EC2_AND_PERSONAL_WEBSITE.md`.

## 1. DNS and EC2 prerequisites

Point an `A` record for the CitePilot subdomain at the instance's Elastic IP. The instance should
have enough memory for Neo4j, Postgres, the API, the worker, and image builds; 8 GB is a comfortable
starting point. Keep only ports 80 and 443 public. If you retain SSH, restrict port 22 to your own
IP; GitHub deployment does not use it.

The bootstrap script targets Ubuntu 22.04/24.04:

```bash
sudo APP_USER=ubuntu \
  APP_DIR=/opt/citepilot \
  REPO_URL=https://github.com/akki-g/CitePilot.git \
  bash infra/deploy/bootstrap-ubuntu.sh
```

For a private repository, give the instance a read-only GitHub deploy key and change `origin` to
the SSH clone URL before enabling automatic deployment.

## 2. Production secrets

Edit `/opt/citepilot/.env.production`. Replace every placeholder in
`.env.production.example`; the production API intentionally refuses to boot with development auth
settings, missing Google OAuth credentials, or missing email delivery.

Generate independent URL-safe secrets rather than reusing one value:

```bash
openssl rand -hex 32  # Postgres password
openssl rand -hex 32  # Redis password
openssl rand -hex 32  # Neo4j password
openssl rand -hex 48  # AUTH_SECRET
```

Use the same Postgres and Redis passwords inside their corresponding connection URLs. Keep
`.env.production` mode `0600` and never add it to Git.

In Google Cloud, register:

```text
https://citepilot.example.com/api/auth/oauth/google/callback
```

Set both `FRONTEND_URL` and `BACKEND_URL` to the public CitePilot origin. For verification email,
the recommended configuration is a Resend API key plus a sender on a verified subdomain.

## 3. Connect the personal website

Choose the proxy you already run:

- Nginx: copy `infra/deploy/nginx-citepilot.conf`, replace the hostname, enable it, validate with
  `sudo nginx -t`, and let the existing Certbot/TLS setup issue the certificate.
- Caddy: merge `infra/deploy/Caddyfile.example` into the existing Caddyfile and reload Caddy.

Do not publish ports 5432, 6379, 7474, 7687, or 8000 in the EC2 security group. The production
Compose file does not bind them to the host.

## 4. Create the AWS deployment roles

Deploy the included CloudFormation stack. The GitHub OIDC provider is account-wide, so set
`CreateGitHubOidcProvider=false` and pass its ARN if your AWS account already has one.

```bash
aws cloudformation deploy \
  --stack-name citepilot-github-deploy \
  --template-file infra/aws/github-oidc-ssm.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOwner=akki-g \
    GitHubRepository=CitePilot \
    InstanceId=i-0123456789abcdef0 \
    CreateGitHubOidcProvider=true
```

If the EC2 instance has no IAM profile, attach the stack's `InstanceProfileName` output:

```bash
aws ec2 associate-iam-instance-profile \
  --instance-id i-0123456789abcdef0 \
  --iam-instance-profile Name=citepilot-ec2-ssm-REGION
```

An EC2 instance can have only one profile. If the website already has one, attach the
`AmazonSSMManagedInstanceCore` managed policy to its existing role instead. Confirm that the node
appears in Systems Manager before continuing.

## 5. Configure the GitHub production environment

Create a GitHub environment named `production`. Add branch protection or a required reviewer, then
add these environment variables:

| Variable | Example |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | CloudFormation `GitHubDeployRoleArn` output |
| `AWS_REGION` | `us-east-1` |
| `EC2_INSTANCE_ID` | `i-0123456789abcdef0` |
| `EC2_APP_DIR` | `/opt/citepilot` |
| `EC2_DEPLOY_USER` | `ubuntu` |
| `CITEPILOT_URL` | `https://citepilot.example.com` |

No long-lived AWS credential or SSH key belongs in GitHub secrets. The IAM trust policy only accepts
tokens from `akki-g/CitePilot` using the `production` environment.

## 6. First deployment and normal releases

Run the first deployment manually on EC2 after filling the environment file:

```bash
cd /opt/citepilot
git fetch origin main
git checkout --detach "$(git rev-parse origin/main)"
./infra/deploy/deploy.sh "$(git rev-parse HEAD)" /opt/citepilot
```

After that, every push to `main` runs backend tests, frontend lint/build, and the production deploy.
Pull requests run CI but never deploy. The deploy process:

1. refuses concurrent deploys or a dirty server checkout;
2. starts the durable stores and makes a compressed Postgres backup;
3. builds the exact Git commit with no source bind mounts;
4. applies Alembic migrations;
5. replaces the application containers;
6. waits for `/api/health` through the loopback web gateway;
7. rolls the application commit back when the health gate fails.

Database migrations are not automatically downgraded. Keep migrations backward-compatible using
an expand/contract sequence so the previous application image remains safe during rollback.

## Operations

```bash
make prod-config   # validate interpolation without starting services
make prod-logs     # follow bounded container logs
make prod-backup   # create an on-demand Postgres backup
docker compose --env-file .env.production -f compose.production.yml ps
```

Backups default to `/opt/citepilot/backups` with 14-day local retention. Local backups protect
against a bad migration, not instance or EBS loss; add EBS snapshots or encrypted off-instance
backup replication before treating this as durable production storage.
