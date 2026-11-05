# Running locally on Ubuntu / Linux (no Docker)

Docker is optional. The app runs fine with just Python + Redis + SQLite — which
is the simplest path on a personal Linux machine.

## 1. If apt is broken (dpkg interrupted)

If you see *"dpkg was interrupted, you must manually run 'sudo dpkg --configure -a'"*,
fix it first:

```bash
sudo dpkg --configure -a
```

You do **not** need Docker Desktop — you can remove that half-installed package
if you want:

```bash
sudo apt remove docker-desktop || true
```

## 2. Install what you need

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip redis-server git
```

Redis starts automatically as a service. Verify:

```bash
redis-cli ping     # should print: PONG
```

## 3. Get the code

```bash
git clone https://github.com/ThompsonShell/Assistant-Bot
cd Assistant-Bot
```

## 4. Run it (one command)

```bash
chmod +x scripts/run-local.sh
./scripts/run-local.sh
```

On first run this creates a `.env` with a random secret and a default password
(`change-me-now`). **Open `.env` and set a real `ADMIN_PASSWORD`**, then run the
script again.

Open **http://localhost:8000/docs** and log in with the username/password from
your `.env`.

## Manual alternative (without the script)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export APP_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export ADMIN_PASSWORD='choose-a-strong-password'
export DATABASE_URL='sqlite+pysqlite:///./lifeos.db'
export REDIS_URL='redis://localhost:6379/0'
export ENABLE_SCHEDULER=false
export DISPLAY_TIMEZONE='Asia/Tashkent'

uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

## Prefer Docker instead?

If you do want Docker (not Docker Desktop — just the engine):

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"   # then log out/in once
cp .env.example .env              # edit APP_SECRET_KEY + ADMIN_PASSWORD
docker compose up --build
```
