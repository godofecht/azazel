# VPS Auto-Deploy via GitHub Webhook

Push to `main` → GitHub webhook → VPS pulls + deploys. Already running on `93.127.202.196`.

## What Already Exists

| Component | Location | Purpose |
|-----------|----------|---------|
| Webhook server | `/opt/webhook/server.py` | Python HTTP server on port 9000, systemd managed |
| Deploy script | `/opt/webhook/deploy.sh` | `git pull` + copy `site/` to deploy dir |
| Repo clones | `/opt/webhook/repos/<repo>/` | Local clones for fast pulls |
| HMAC secret | `/opt/webhook/.secret` | Shared between GitHub and server |
| Systemd service | `webhook.service` | Auto-restarts, logs to journalctl |
| Nginx proxy | `location = /webhook` | Proxies `https://abhishek-shivakumar.com/webhook` → `localhost:9000` |

## To Add a New Repo

### 1. Clone the repo on the VPS

```bash
cd /opt/webhook/repos
git clone https://github.com/godofecht/<REPO>.git
```

### 2. Add a route to the webhook server

Edit `/opt/webhook/server.py` and add an entry to the `ROUTES` dict:

```python
ROUTES = {
    "godofecht/azazel": {
        "branch": "refs/heads/main",
        "deploy_dir": "/var/www/azazel",
        "repo": "azazel"
    },
    # Add new repo here:
    "godofecht/<REPO>": {
        "branch": "refs/heads/main",
        "deploy_dir": "/var/www/<REPO>",
        "repo": "<REPO>"
    }
}
```

### 3. Create the deploy target directory

```bash
mkdir -p /var/www/<REPO>
```

### 4. Add nginx location block

Add to `/etc/nginx/sites-enabled/abhishek-shivakumar.com`:

```nginx
location = /<REPO> { return 301 /<REPO>/; }

location ^~ /<REPO>/ {
    alias /var/www/<REPO>/;
    index index.html;
    try_files $uri $uri/ /<REPO>/index.html;
}
```

Then: `nginx -t && nginx -s reload`

### 5. Restart the webhook server

```bash
systemctl restart webhook
```

### 6. Create the GitHub webhook

```bash
WEBHOOK_SECRET=$(cat /opt/webhook/.secret)
gh api repos/godofecht/<REPO>/hooks -X POST \
  -f name=web \
  -F active=true \
  -F 'events[]=push' \
  -f 'config[url]=https://abhishek-shivakumar.com/webhook' \
  -f "config[secret]=$WEBHOOK_SECRET" \
  -f 'config[content_type]=json' \
  -f 'config[insecure_ssl]=0'
```

That's it. Pushes to `main` will now auto-deploy.

## How It Works

```
git push → GitHub POST /webhook → nginx proxy → server.py
  → verify HMAC-SHA256 signature
  → match repo name in ROUTES
  → match branch (refs/heads/main)
  → run deploy.sh <repo> <deploy_dir>
    → cd /opt/webhook/repos/<repo>
    → git fetch origin main && git reset --hard origin/main
    → cp -r site/* <deploy_dir>/
```

## Deploy Script Convention

The deploy script copies everything from the `site/` directory in the repo to the deploy dir. If your repo uses a different directory for static files, edit `/opt/webhook/deploy.sh` or add per-repo logic.

## Debugging

```bash
# Check webhook server status
systemctl status webhook

# View deploy logs
cat /opt/webhook/deploy.log

# View server logs
journalctl -u webhook -f

# Test webhook endpoint
curl https://abhishek-shivakumar.com/webhook

# Manually trigger a deploy
/opt/webhook/deploy.sh <repo> /var/www/<repo>
```

## Key Details

- **Secret**: All repos share the same HMAC secret at `/opt/webhook/.secret`
- **Branch**: Only `refs/heads/main` triggers deploys (configurable per route)
- **Static files**: Deploy script expects a `site/` directory in the repo root
- **SSH**: Use the `universal-ssh` skill with aissh toolkit at `/Users/abhishekshivakumar/website/aissh`
- **VPS**: `93.127.202.196`, root access via SSH
