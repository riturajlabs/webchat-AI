# Oracle Free VM - Zero-Cost Deployment (Phase 17)

Deploy WebChat AI on an **Oracle Cloud Free Tier ARM VM** (4 OCPUs / 24 GB RAM,
always free) for **$0/month**. This is the canonical deployment path described
in `docs/ZERO_COST_DEPLOYMENT.md` and complements the generic guide in
`docs/DEPLOYMENT.md`.

External dependencies (managed outside the VM, all free tier):

| Service          | Role                 | Free provider / note                     |
| ---------------- | -------------------- | ---------------------------------------- |
| MongoDB Atlas    | database             | M0 (no Vector Search -> brute-force RAG) |
| Redis            | queue broker + cache | Upstash free, or self-hosted on the VM   |
| Resend           | transactional email  | 3k emails/month                          |
| Cloudflare       | DNS + CDN + TLS      | free plan, proxy + HSTS                  |
| Cloudflare Pages | widget SDK CDN       | hashed bundle, immutable cache           |

---

## 1. Ubuntu VM setup

1. Create a VM in the OCI Console: **Free Tier - AMD/ARM Compute**, Ubuntu
   24.04 (or 22.04) LTS, the free shape with ≥2 GB RAM (use ARM for 24 GB).
2. Upload your SSH public key; save the private key locally.
3. Assign a **public IP** (ephemeral is fine; reserve if you want stability)
   and open security-list/NSG ingress for `22`, `80`, `443`.
4. Bootstrapping is automated by `scripts/server-init.sh` (run as root):

```bash
ssh -i ~/.ssh/oracle_rsa ubuntu@<PUBLIC_IP>
sudo -i
APP_DIR=/opt/webchat-ai \
REPO_URL=https://github.com/your-org/webchat-AI.git \
bash <(curl -fsSL https://raw.githubusercontent.com/your-org/webchat-AI/main/scripts/server-init.sh)
```

The script is idempotent: safe to re-run on every bootstrap.

## 2. Docker installation

`server-init.sh` installs Docker Engine + the compose plugin from the official
Docker apt repository when they are missing (it refuses non-Ubuntu/Debian
distros). Manual equivalent:

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg git jq ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
```

Verify: `docker version` and `docker compose version` (Compose **v2** plugin,
not the legacy `docker-compose` binary).

## 3. Firewall rules

`server-init.sh` configures UFW. Expose only the edge:

```bash
ufw allow 22/tcp            # SSH
ufw allow 80/tcp            # HTTP (Cloudflare origin)
ufw allow 443/tcp           # HTTPS (Cloudflare origin)
ufw --force enable
ufw status verbose          # confirm
```

Everything else is unreachable: the app containers publish no host ports
(the API/worker/dashboard/widget use compose `expose`, which is bridge-internal
only; nginx is the sole `ports` publisher). If you self-host Redis on the VM,
bind it to the Docker bridge only - never publish it to the host.

## 4. Cloning the repository

`server-init.sh` clones into `$APP_DIR` (`/opt/webchat-ai` by default) when
`REPO_URL` is set. Manual equivalent:

```bash
mkdir -p /opt/webchat-ai
git clone https://github.com/your-org/webchat-AI.git /opt/webchat-ai
```

`deploy-production.sh` handles `git fetch` + `git pull --ff-only` on every run.

## 5. Environment setup

1. `server-init.sh` copies `.env.production.example` to `.env.production` when
   it is missing. Fill it in:

```bash
cd /opt/webchat-ai
openssl rand -hex 32        # -> JWT_SECRET
nano .env.production        # edit every value
```

2. Every variable is documented inline. Required ones are enforced twice:
   compose fails fast with `:?` markers, and the API validates policy at boot
   (short JWT secret, mock payments, wildcard/loopback CORS, etc. are boot
   errors in production).
3. Permissions: `chmod 600 .env.production` and never commit it.

## 6. Production compose commands

```bash
cd /opt/webchat-ai
set -a; source .env.production; set +a     # exports the secrets to compose

# Build and start everything behind nginx
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# Inspect
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api worker nginx

# Verify the whole stack end-to-end
scripts/deployment-check.sh
```

Routing (single origin `https://app.example.com`):

| Path                  | Backend        |
| --------------------- | -------------- |
| `/api/*`              | api:8000       |
| `/widget/*`           | widget:80      |
| `/` and `/dashboard/` | dashboard:3000 |

All five services `restart: unless-stopped` (auto-recovery on crash/reboot) and
are healthchecked; nginx waits for `api`, `dashboard` and `widget` to be
healthy before serving. Only nginx publishes host ports (80/443).

**Self-hosted Redis (optional, instead of Upstash):** add an override file
`docker-compose.override.yml` in `/opt/webchat-ai`:

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ['redis-server', '--appendonly', 'yes']
    volumes:
      - redis_data:/data
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 10s
      timeout: 3s
      retries: 5
  # point the app + worker at the bridge-resolved name
  api:
    environment: { REDIS_URL: redis://redis:6379 }
  worker:
    environment: { REDIS_URL: redis://redis:6379 }
volumes:
  redis_data:
```

## 7. First deployment

```bash
cd /opt/webchat-ai
set -a; source .env.production; set +a
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
scripts/deployment-check.sh      # must print 0 failed
```

Then, from your workstation, run the post-deploy checklist in
`docs/DEPLOYMENT.md` (widget CDN upload, DNS/Cloudflare proxy, HSTS, security
spot-checks, admin smoke test). Prefer `scripts/deploy-production.sh` for
everything after the first boot.

## 8. Update deployment

One command (recommended):

```bash
cd /opt/webchat-ai && scripts/deploy-production.sh
```

Flow: `git pull --ff-only` -> load `.env.production` -> build with a fresh
tag (git short SHA) -> `up -d` -> wait for all healthchecks -> run
`scripts/deployment-check.sh`. On failure it rolls back to the previously
running image tag automatically.

Manual equivalent (same steps, explicit):

```bash
cd /opt/webchat-ai
git fetch origin && git pull --ff-only
set -a; source .env.production; set +a
export TAG=$(git rev-parse --short HEAD)          # keep old tag intact
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
scripts/deployment-check.sh
```

Using a per-deploy `TAG` preserves the previous image on the host, which is
what makes rollback instant.

## 9. Backup strategy

**Data lives outside the VM** (Atlas, Upstash, Resend), so the VM itself holds
no application state - only code, images and certs. That makes backups simple:

- **Database**: enable Atlas M0 continuous backups, or nightly `mongodump`
  (job / cron) to Object Storage:
  ```bash
  mongodump --uri="$MONGODB_URI" --db="$MONGODB_DB" --archive | gzip > backup-$(date +%F).archive.gz
  ```
- **Redis (if self-hosted)**: RDB/AOF snapshots live in the `redis_data`
  volume; snapshot the volume with `docker run --rm -v redis_data:/data -v /backup:/backup alpine tar czf /backup/redis-$(date +%F).tgz -C /data .`
- **Certificates** (`$APP_DIR/tls`): reissue via Cloudflare Origin CA; keep the
  private key copy elsewhere.
- **Secrets** (`.env.production`): store a copy in your password manager /
  vault - not in git.
- **Test restoration** quarterly: restore the latest mongodump into a scratch
  database and boot a staging stack against it.

## 10. Update strategy

- Roll forward with `scripts/deploy-production.sh`; it never destroys old
  images (per-deploy `TAG`).
- Check `docs/DEPLOYMENT.md` for the migration contract before applying:
  `init_indexes()` is idempotent, migrations are additive - so a rollback to an
  older image is always safe.
- Verify `scripts/deployment-check.sh` prints `0 failed` after every update;
  stop for a manual smoke test when the release notes flag auth/billing/rag
  changes.
- Watch resources: `df -h` (image/volume growth) and `free -m`. Clean stale
  images with `docker image prune -f` after a successful update.

## 11. Emergency rollback

Instant - no rebuild required (previous images are still tagged on the host):

```bash
cd /opt/webchat-ai
set -a; source .env.production; set +a
OLD_TAG=<tag-of-the-image-before-the-bad-deploy>   # docker images | grep webchat-api
TAG=$OLD_TAG docker compose -f docker-compose.prod.yml up -d
scripts/deployment-check.sh
```

Rollback contract (why it is safe):

- `init_indexes()` is idempotent; migrations are additive and non-destructive.
- ARQ (worker) jobs are persistent in Redis; a rolled-back worker resumes the
  queue - no data loss.
- Widget bundles are content-hashed: browsers/CNDs keep the version they
  fetched, so the widget and the API never disagree.
- DNS/Cloudflare can roll back to a previous origin if the VM itself is
  compromised.
- If rollback image tags were pruned (e.g. `docker image prune -f` ran after a
  failed deploy), rebuild from the previous git ref:
  `git checkout <previous-sha> && TAG=<previous-sha> docker compose ... build && up -d`.

If the VM is unreachable entirely, boot a fresh one, re-run
`scripts/server-init.sh`, restore `.env.production` + certs, and run
`scripts/deploy-production.sh` with the previous `TAG` (or rebuild from the
previous git SHA).
