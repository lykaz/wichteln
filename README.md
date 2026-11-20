# Wichteln

Wichteln mit der Familie!

## Running the Docker image

The image expects the SQLite DB at `/data/wichteln.db` (baked in as the `DB_PATH` env var) — mount a volume there or the DB is lost whenever the container is recreated:

```
docker volume create wichteln-data
docker run -d \
  --name wichteln \
  -p 5000:5000 \
  -v wichteln-data:/data \
  -e SECRET_KEY=... \
  -e OIDC_ISSUER=... \
  -e OIDC_CLIENT_ID=... \
  -e OIDC_CLIENT_SECRET=... \
  ghcr.io/lykaz/wichteln:latest
```

To back up the DB: `docker run --rm -v wichteln-data:/data -v "$PWD":/backup alpine cp /data/wichteln.db /backup/`.
