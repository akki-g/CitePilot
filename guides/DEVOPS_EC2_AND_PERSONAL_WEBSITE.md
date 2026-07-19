# CitePilot DevOps and personal website integration

This guide explains how CitePilot is packaged, deployed, and connected to a personal website on
the same EC2 instance. It covers both common EC2 layouts:

1. a reverse proxy runs directly on the EC2 host; or
2. the personal website's reverse proxy runs inside Docker.

The recommended public URL is a subdomain such as `https://citepilot.example.com`. Keep the
personal website at `https://example.com` and add a portfolio link to CitePilot's demo. A subdomain
keeps routing, OAuth callbacks, cookies, and frontend asset paths straightforward while still
presenting CitePilot as part of the same personal site.

## 1. The production architecture

The default deployment looks like this:

```text
User browser
    |
    | HTTPS: citepilot.example.com
    v
EC2 reverse proxy / TLS termination
    |
    | HTTP on the EC2 host or a private Docker network
    v
CitePilot web gateway (Nginx + compiled React application)
    |
    | /api/* on the private CitePilot app network
    v
FastAPI backend --------------------> external research and model APIs
    |
    +------> ARQ worker
    +------> PostgreSQL + pgvector
    +------> Neo4j
    +------> Redis
```

The browser sees one origin. The CitePilot web gateway serves the React application and forwards
`/api/*` to FastAPI, so the browser never needs the backend container's address.

### Container responsibilities

| Service | Responsibility | Publicly exposed? | Persistent state? |
|---|---|---:|---:|
| `web` | React assets, SPA routing, `/api` reverse proxy | Through the edge proxy only | No |
| `backend` | HTTP API, authentication, graph, agent and LaTeX orchestration | No | No |
| `worker` | Background ARQ jobs | No | No |
| `postgres` | Users, projects, metadata, compiled-PDF records and vectors | No | Yes |
| `neo4j` | Citation graph mirror | No | Yes |
| `redis` | Job queue and short-lived coordination | No | Yes |

The application services are disposable. Durable data lives in named Docker volumes. This is why
a new application image can replace the old image without deleting user projects.

## 2. What the production Docker files do

The production stack is defined by `compose.production.yml` rather than the development Compose
configuration.

Important production properties include:

- no source-code bind mounts;
- pinned, locked application dependencies;
- non-root backend and worker processes;
- read-only application container filesystems;
- bounded Docker log rotation;
- health checks and restart policies;
- named volumes for all durable stores;
- a private `data` network for PostgreSQL, Neo4j, and Redis;
- only the `web` gateway published to the EC2 host; and
- a prewarmed Tectonic cache so normal PDF previews do not fetch LaTeX packages.

The default host publication is:

```text
127.0.0.1:3001 -> CitePilot web container port 8080
```

Binding to `127.0.0.1` means port 3001 is usable by software running on the EC2 host but is not a
public listener. PostgreSQL, Redis, Neo4j, and FastAPI have no host port mappings at all.

## 3. The CI/CD path

The deployment workflow is `.github/workflows/ci-deploy-ec2.yml`.

```text
Pull request
    -> backend tests and lint
    -> frontend lint and production build
    -> no deployment

Push to main
    -> backend tests and lint
    -> frontend lint and production build
    -> GitHub obtains a short-lived AWS session through OIDC
    -> AWS Systems Manager runs the deployment on the selected EC2 instance
    -> EC2 fetches and deploys the exact Git commit
```

GitHub does not need an EC2 SSH key or a permanent AWS access key. The AWS trust policy only accepts
an OIDC token for this repository's `production` environment. The IAM policy can send an SSM
command only to the configured EC2 instance.

The server-side deployment script then:

1. rejects unsafe input, concurrent deployments, and tracked server edits;
2. checks out the exact commit that passed CI;
3. validates the production Compose configuration;
4. starts the durable services;
5. creates a compressed PostgreSQL backup;
6. builds the backend and web images;
7. runs Alembic migrations;
8. replaces the application containers;
9. checks `/api/health` through the web gateway; and
10. returns to the previous application commit if the health gate fails.

Database migrations are not automatically downgraded during rollback. Production migrations
should therefore remain compatible with both the new release and the immediately previous release.

## 4. Recommended connection: host reverse proxy

Use this layout when Nginx or Caddy runs directly on the EC2 host. This is the layout already
supported by `compose.production.yml` without any Compose changes.

```text
EC2 ports 80/443
        |
        v
Host Nginx or Caddy
    |                  |
    | example.com      | citepilot.example.com
    v                  v
Personal-site       127.0.0.1:3001
container              |
                       v
                   CitePilot web
```

Your personal website can still be containerized. The host proxy simply routes one hostname to the
personal-site container's published loopback port and the CitePilot hostname to port 3001.

### Nginx host configuration

Start from `infra/deploy/nginx-citepilot.conf`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name citepilot.example.com;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Do not enable proxy buffering for this application. Agent responses use streaming endpoints, and
buffering can make the chat appear frozen until a large response has accumulated.

Enable the site and TLS using the same process as the personal website:

```bash
sudo ln -s /etc/nginx/sites-available/citepilot /etc/nginx/sites-enabled/citepilot
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d citepilot.example.com
```

If the instance already uses a wildcard certificate, reuse it instead of requesting another one.

### Caddy host configuration

Merge `infra/deploy/Caddyfile.example` into the host Caddyfile:

```caddy
citepilot.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:3001
}
```

## 5. Container-to-container connection

Use this layout when the personal website's Nginx, Caddy, or Traefik container owns EC2 ports 80
and 443. A container cannot reach an EC2-host listener by using `127.0.0.1`; inside a container,
that address refers to the container itself. The clean solution is a shared external Docker
network used only for edge HTTP traffic.

```text
EC2 ports 80/443
        |
        v
Personal-site proxy container
        |
        | shared network: website_edge
        v
citepilot-web:8080
        |
        | private CitePilot app network
        v
backend:8000
```

Do not attach PostgreSQL, Neo4j, Redis, or the worker to the shared edge network.

### Step 1: create a stable external network

Run this once on EC2:

```bash
docker network create website_edge
```

Because the network is external, bringing either Compose project down does not delete it.

### Step 2: attach CitePilot's web gateway

Create a committed file named `compose.website-network.yml` in the CitePilot repository:

```yaml
services:
  web:
    networks:
      app:
      website_edge:
        aliases:
          - citepilot-web

networks:
  website_edge:
    external: true
    name: website_edge
```

Use both Compose files when deploying:

```bash
docker compose \
  --env-file .env.production \
  -f compose.production.yml \
  -f compose.website-network.yml \
  up -d
```

The current automated deployment script explicitly selects `compose.production.yml`. If this
shared-network layout is selected, update its Compose array to include the override:

```bash
compose=(
  docker compose
  --env-file .env.production
  -f compose.production.yml
  -f compose.website-network.yml
)
```

Make the same adjustment to any operational command that needs the fully merged configuration.
The database backup script can continue using only the base file because it addresses PostgreSQL,
not the edge network.

### Step 3: attach the personal-site proxy

Add the same external network to the personal website's Compose file. The exact proxy service name
may be `nginx`, `caddy`, `traefik`, or `proxy`:

```yaml
services:
  proxy:
    # Existing image, ports, volumes, and configuration stay here.
    networks:
      - default
      - website_edge

networks:
  website_edge:
    external: true
    name: website_edge
```

Do not add CitePilot's database containers to the personal website Compose project. Keeping the two
projects separate allows either application to deploy without restarting the other.

### Step 4: route the CitePilot hostname

For an Nginx proxy container, use the Docker alias instead of a host port:

```nginx
server {
    listen 80;
    server_name citepilot.example.com;

    client_max_body_size 2m;

    location / {
        proxy_pass http://citepilot-web:8080;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

For a Caddy proxy container:

```caddy
citepilot.example.com {
    encode zstd gzip
    reverse_proxy citepilot-web:8080
}
```

After recreating both projects, verify name resolution from the proxy container:

```bash
docker compose exec proxy getent hosts citepilot-web
docker compose exec proxy wget -qO- http://citepilot-web:8080/healthz
```

Use the actual personal-site Compose service name in place of `proxy`.

## 6. Connecting the portfolio experience

The personal website should usually link to CitePilot rather than place the authenticated
workspace in an iframe.

A practical portfolio flow is:

```text
example.com/projects/citepilot
    -> project explanation, screenshots, architecture and technology
    -> "Try the live demo" links to https://citepilot.example.com/demo
    -> "Sign in" links to https://citepilot.example.com/login
```

This keeps the marketing page inside the personal website while the full application retains its
own routing and security boundary. An iframe can be used for a constrained visual demo, but browser
cookie policies and frame-security headers make it a poor default for the authenticated workspace.

Hosting the complete application at `https://example.com/citepilot/` is not a proxy-only change.
It would also require a matching Vite base path, router basename, asset URLs, API rewrites, OAuth
callback URLs, and email links. Use the subdomain unless path-based hosting is an explicit product
requirement.

## 7. DNS, OAuth, email, and cookies

Before the first production deployment:

1. point `citepilot.example.com` to the EC2 Elastic IP;
2. obtain a valid TLS certificate;
3. set both `FRONTEND_URL` and `BACKEND_URL` to `https://citepilot.example.com`;
4. register `https://citepilot.example.com/api/auth/oauth/google/callback` with Google;
5. verify the email-sending domain and configure `RESEND_API_KEY` or SMTP; and
6. leave `SESSION_COOKIE_DOMAIN` empty unless cookies intentionally need to be shared across
   subdomains.

Host-only cookies are the safer default. The personal website does not need access to CitePilot's
authentication cookie.

## 8. EC2 network and security boundary

The EC2 security group should normally expose only:

| Port | Source | Purpose |
|---:|---|---|
| 80 | Internet | HTTP redirect and certificate validation |
| 443 | Internet | HTTPS traffic |
| 22 | Your IP only, optional | Emergency SSH access |

Do not add public ingress rules for ports `3001`, `8000`, `5432`, `6379`, `7474`, or `7687`.
GitHub deployment uses AWS Systems Manager, so CI does not require inbound SSH.

The shared `website_edge` network is not equivalent to a public EC2 port. It allows only containers
joined to that Docker network to address `citepilot-web` directly.

## 9. Production secrets

The real environment file lives at `/opt/citepilot/.env.production` and should have mode `0600`.
It is not copied into either application image.

Use separate generated values for:

- `POSTGRES_PASSWORD`;
- `NEO4J_PASSWORD`;
- `REDIS_PASSWORD`; and
- `AUTH_SECRET`.

Do not reuse the development `.env`, commit production secrets, put them in the personal website's
frontend bundle, or pass them through Vite variables. Any `VITE_*` value becomes browser-readable.

GitHub's production environment contains deployment coordinates such as the instance ID and role
ARN. It does not need database, OAuth, email, or model-provider secrets because those remain on EC2.

## 10. First deployment checklist

On EC2:

```bash
cd /opt/citepilot
chmod 600 .env.production
docker compose --env-file .env.production -f compose.production.yml config --quiet
./infra/deploy/deploy.sh "$(git rev-parse HEAD)" /opt/citepilot
curl --fail http://127.0.0.1:3001/healthz
curl --fail http://127.0.0.1:3001/api/health
```

If using the shared edge network, include its override file in the Compose validation and update
the deployment script before the first automated release.

From another machine:

```bash
curl --fail https://citepilot.example.com/healthz
curl --fail https://citepilot.example.com/api/health
```

Then verify these browser flows:

- demo project creation and its enforced limits;
- account signup and receipt of the verification email;
- email verification and password login;
- Google OAuth callback;
- agent streaming without long pauses caused by proxy buffering;
- LaTeX preview without a download option in demo mode; and
- returning to the PDF tab shows the latest successful compilation.

## 11. Operations and failure handling

Useful commands:

```bash
make prod-config
make prod-logs
make prod-backup
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=200 backend worker web
```

For a shared edge network, add `-f compose.website-network.yml` to commands that inspect or replace
the `web` service.

### If the public URL returns 502

Check the path one layer at a time:

1. `docker compose ... ps` shows `web` and `backend` healthy;
2. `curl http://127.0.0.1:3001/healthz` works in host-proxy mode;
3. `wget http://citepilot-web:8080/healthz` works from the proxy container in shared-network mode;
4. the proxy configuration uses the correct hostname and upstream; and
5. the proxy was reloaded after its configuration changed.

### If the UI loads but API calls fail

Check `/api/health`, not only `/healthz`. The first endpoint traverses the web-to-backend proxy;
the second checks only the web gateway.

### If agent responses arrive all at once

Confirm that every proxy layer has response buffering disabled and sufficiently long read/send
timeouts. Both the personal-site edge proxy and CitePilot's internal web gateway participate in the
request path.

### If OAuth redirects to localhost or the wrong domain

Correct `FRONTEND_URL`, `BACKEND_URL`, and the provider's registered callback URL, then recreate the
backend container so it receives the updated environment.

### If a deployment fails after migration

The script restores the previous application commit, but it does not reverse the database schema.
Inspect the deployment logs and use the pre-migration PostgreSQL backup only when a deliberate data
restore is required.

## 12. Related files

- `compose.production.yml`: production container topology and health checks
- `.env.production.example`: production environment contract
- `.github/workflows/ci-deploy-ec2.yml`: tests and automatic deployment
- `infra/deploy/deploy.sh`: exact-commit deployment, migration, health gate and rollback
- `infra/deploy/bootstrap-ubuntu.sh`: initial Ubuntu and Docker setup
- `infra/deploy/backup-postgres.sh`: compressed local PostgreSQL backups
- `infra/deploy/nginx-citepilot.conf`: host Nginx example
- `infra/deploy/Caddyfile.example`: host Caddy example
- `infra/aws/github-oidc-ssm.yml`: GitHub OIDC and EC2 Systems Manager roles
- `infra/deploy/README.md`: concise EC2 setup runbook

Official background references:

- [GitHub Actions: OpenID Connect in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [Docker Compose in production](https://docs.docker.com/compose/how-tos/production/)
- [Docker networking](https://docs.docker.com/engine/network/)
- [AWS EC2 security groups](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html)
