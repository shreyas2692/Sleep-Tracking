# Deploy status

**Last local deploy:** 2026-07-31  
**Tests before ship:** 235 passed  

## Running now (Docker on this machine)

| | |
|--|--|
| URL | http://127.0.0.1:8080 |
| Health | `GET /healthz` → `{"ok":true}` (public) |
| Auth | HTTP Basic — username `sleep` |
| Password | in `/tmp/sleep-tracker-deploy.env` (not in git) |
| Image | `sleep-tracker:latest` |
| Container | `sleep-tracker` (restart: unless-stopped) |
| Data | Docker volume `sleep-tracker-data` → `/data/sleep.db` |

```bash
# credentials
cat /tmp/sleep-tracker-deploy.env

# logs
docker logs -f sleep-tracker

# stop
docker rm -f sleep-tracker

# rebuild + redeploy
docker build -t sleep-tracker:latest .
docker rm -f sleep-tracker
set -a; source /tmp/sleep-tracker-deploy.env; set +a
docker run -d --name sleep-tracker -p 8080:10000 \
  -v sleep-tracker-data:/data \
  -e SECRET_KEY -e SLEEP_PASSWORD -e SLEEP_USERNAME=sleep \
  -e SLEEP_DB_PATH=/data/sleep.db -e SESSION_COOKIE_SECURE=0 \
  --restart unless-stopped sleep-tracker:latest
```

## Public cloud (Render Blueprint)

Repo already has [`render.yaml`](../render.yaml): Docker web service, disk at
`/var/data`, generated `SECRET_KEY`, required `SLEEP_PASSWORD`.

1. Create a GitHub repo and push `main`.
2. [Render](https://dashboard.render.com) → **New** → **Blueprint** → select repo.
3. When prompted, set a strong `SLEEP_PASSWORD`.
4. After deploy, open the Render URL; login as `sleep` / your password.
5. `SESSION_COOKIE_SECURE=1` is set in the Blueprint (HTTPS only).

Optional CLI (after `brew install render` and login):

```bash
# from repo root once the remote exists
render blueprints apply
```

## LAN access (same Wi‑Fi)

Docker publishes `0.0.0.0:8080`. Find your Mac IP and open
`http://<mac-ip>:8080` from phone/iOS Settings server field. Keep
`SLEEP_PASSWORD` set.

## iOS app point-at deploy

Settings → Server URL:

- Simulator on same Mac: `http://127.0.0.1:8080`
- Physical device: `http://<your-lan-ip>:8080`
- Render: `https://<your-service>.onrender.com`
