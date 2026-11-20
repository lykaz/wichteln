# Wichteln

Wichteln mit der Familie!

## Running the Docker image

The image expects the SQLite DB at `/data/wichteln.db` (baked in as the `DB_PATH` env var) — mount a volume there or the DB is lost whenever the container is recreated:

The app also takes a periodic online backup of the DB (safe to run against a live, in-use database) and writes it to `/backups` with a timestamped filename, pruning old ones automatically. Bind-mount `/backups` to a real directory on the host so backups survive even if the `/data` volume is lost:

```
docker volume create wichteln-data
mkdir -p ./wichteln-backups
docker run -d \
  --name wichteln \
  -p 5000:5000 \
  -v wichteln-data:/data \
  -v "$PWD/wichteln-backups":/backups \
  -e SECRET_KEY=... \
  -e OIDC_ISSUER=... \
  -e OIDC_CLIENT_ID=... \
  -e OIDC_CLIENT_SECRET=... \
  ghcr.io/lykaz/wichteln:latest
```

Backup frequency and retention are configurable via `BACKUP_INTERVAL_HOURS` (default `24`) and `BACKUP_KEEP` (default `14`, i.e. keep the last 14 backups).
