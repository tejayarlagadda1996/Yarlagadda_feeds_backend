# Yarlagadda Feeds Backend

FastAPI backend for Yarlagadda Feeds factory management.

- **Runtime:** Python 3.9+ (EC2 uses system Python 3.9)
- **DB:** SQLite on EC2 (same instance — lowest cost)
- **Deploy:** push to `main` → GitHub Actions → EC2 `t3.micro`

## Live API

```
http://35.154.195.118:8000/health
http://35.154.195.118:8000/docs
http://35.154.195.118:8000/api/v1/modules
```

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Auto-deploy (GitHub Actions)

On every push to `main`, `.github/workflows/deploy-ec2.yml`:

1. Copies app files to `/opt/yarlagadda-feeds` on EC2
2. Installs Python deps
3. Restarts `yarlagadda-feeds` systemd service

Required repo secrets:

| Secret | Value |
|--------|--------|
| `EC2_HOST` | `35.154.195.118` |
| `EC2_USER` | `ec2-user` |
| `EC2_SSH_KEY` | contents of `yarlagadda-feeds-key.pem` |

## Flutter app

API URL is hard-coded in `mobile/lib/config/api_config.dart` as `ApiConfig.baseUrl`.

```bash
cd ../mobile && flutter run -d "iPhone 13 Pro Max"
```
