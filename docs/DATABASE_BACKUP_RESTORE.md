# Database Backup & Restore Guide

Practical backup/restore procedures for the WebChat AI stack (MongoDB + Redis).

---

## MongoDB (Docker — Local / Self-Hosted)

The `mongo` service has **no host port exposed** (internal Docker network only).
All backup/restore commands run inside the container via `docker compose exec`.

### Backup

```bash
# Source the env file to get credentials
source .env.production

# Create a gzipped archive backup
docker compose exec -T mongo mongodump \
  --username "$MONGO_USERNAME" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --archive --gzip \
  > "backup-$(date +%F).archive.gz"
```

> **Tip:** For Atlas or URI-based auth (credentials embedded in `MONGODB_URI`), extract
> the username/password from the URI or use `mongosh` to authenticate first and then
> run `mongodump` without explicit credential flags.

### Restore

```bash
source .env.production

docker compose exec -T mongo mongorestore \
  --archive="backup-2025-01-15.archive.gz" --gzip \
  --username "$MONGO_USERNAME" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --drop
```

The `--drop` flag removes existing collections before restoring. Omit it to merge
instead of replace.

### Export a Single Database

```bash
docker compose exec -T mongo mongodump \
  --username "$MONGO_USERNAME" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --db webchat_ai \
  --archive --gzip \
  > "backup-webchat_ai-$(date +%F).archive.gz"
```

### Scheduled Backup (Cron)

Add to the host crontab (`crontab -e`):

```cron
# Daily MongoDB backup at 03:00 UTC
0 3 * * * cd /path/to/webchat-AI && source .env.production && docker compose exec -T mongo mongodump --username "$MONGO_USERNAME" --password "$MONGO_PASSWORD" --authenticationDatabase admin --archive --gzip > "backups/backup-$(date +\%F).archive.gz" 2>/dev/null

# Prune backups older than 30 days
0 4 * * * find /path/to/webchat-AI/backups -name 'backup-*.archive.gz' -mtime +30 -delete
```

Ensure the `backups/` directory exists (`mkdir -p backups`).

---

## MongoDB Atlas (Managed)

For production deployments on MongoDB Atlas:

- **Use Atlas continuous backups or point-in-time snapshots** — these are
  infrastructure-level and don't require `mongodump`.
- Atlas provides a **Backup** tab in the cluster dashboard for on-demand snapshots
  and continuous backup with point-in-time recovery.
- For scripted backups, use Atlas Data API or the `mongodump` command with your
  Atlas connection string (embedded credentials via `MONGODB_URI`):

```bash
source .env.production

mongodump \
  --uri "$MONGODB_URI" \
  --archive --gzip \
  > "backup-atlas-$(date +%F).archive.gz"
```

- **SCRAM authentication** is the default for Atlas. Credentials are embedded in
  the `mongodb+srv://` connection string — no separate `--username`/`--password`
  flags needed.
- Restore with:

```bash
mongorestore \
  --uri "$MONGODB_URI" \
  --archive="backup-atlas-2025-01-15.archive.gz" --gzip \
  --drop
```

---

## Redis

The `redis` service uses RDB persistence (`--save 60 1`) and stores data in the
`redis_data` Docker volume. Redis is primarily a **cache and message broker** for
this stack — full backups are usually **not required** since data is ephemeral or
reconstructible. However, if you need to export Redis data:

### Trigger a Snapshot

```bash
# Force an immediate RDB save
docker compose exec redis redis-cli SAVE

# Or background it (non-blocking)
docker compose exec redis redis-cli BGSAVE
```

### Copy the Dump File

```bash
# Find the volume mount path
docker compose exec redis redis-cli CONFIG GET dir
# Typically /data inside the container

# Copy the RDB dump from the container
docker compose cp redis:/data/dump.rdb ./redis-dump-$(date +%F).rdb
```

### Restore from Dump

```bash
# Stop Redis, replace the dump, restart
docker compose stop redis
docker compose cp ./redis-dump-2025-01-15.rdb redis:/data/dump.rdb
docker compose start redis
```

### Volume Note

The `redis_data` Docker volume persists RDB snapshots across container restarts.
For disaster recovery, back up the volume itself:

```bash
docker run --rm -v webchat-ai_redis_data:/data -v "$(pwd)":/backup \
  alpine tar czf /backup/redis-volume-$(date +%F).tar.gz -C /data .
```

---

## Production Checklist

Tie these procedures to the 5 security checks in `scripts/check-database-security.sh`:

| #   | Check                            | What It Validates                                                 | Backup Relevance                                                  |
| --- | -------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1   | MongoDB authentication enabled   | Production requires auth on MongoDB                               | Backups must use authenticated connections                        |
| 2   | MongoDB port not exposed to host | No `ports:` mapping on the `mongo` service                        | Backups run via `docker compose exec`, not direct host connection |
| 3   | Credentials not committed to git | No `.env.*` files or password literals in tracked files           | Backup scripts should source env files, not hardcode credentials  |
| 4   | Connection string validation     | `Settings` object boots successfully with the env file            | Ensures backup commands will work with the same credentials       |
| 5   | Backup documentation exists      | `docs/DATABASE_BACKUP_RESTORE.md` contains mongodump/mongorestore | You are reading this document                                     |

### Before any production deployment:

- [ ] Run `bash scripts/check-database-security.sh --env-file .env.production`
- [ ] Verify backup cron is scheduled and `backups/` directory exists
- [ ] Test a backup + restore cycle on a staging environment
- [ ] Confirm Atlas continuous backups are enabled (if using Atlas)
- [ ] Store backup encryption keys securely (if encrypting backups)
