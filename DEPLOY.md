# Deploying to PythonAnywhere

Target: `https://Maaz2006.pythonanywhere.com` — free "Beginner" account,
"innit" system image, Python 3.13, SQLite, always-on.

Run everything in the PythonAnywhere **Bash console** unless the step says
*Web tab*.

---

## 1. Get the code

```bash
cd ~
git clone https://github.com/maaz-2006/child-wellness.git
cd child-wellness
```

If the repository is private, use a GitHub personal access token in the URL:

```bash
git clone https://<TOKEN>@github.com/maaz-2006/child-wellness.git
```

---

## 2. Virtualenv and dependencies

```bash
mkvirtualenv --python=/usr/bin/python3.13 kito
pip install -r requirements.txt
```

Verify the versions actually installed:

```bash
python -V          # expect 3.13.x
python -m django --version
```

---

## 3. Generate the secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Copy the output. You need it in step 5 — do **not** commit it anywhere.

---

## 4. Database and static files

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

`collectstatic` writes to `~/child-wellness/staticfiles/`. That exact path is
mapped in step 6.

---

## 5. Web tab — WSGI file

*Web tab → the link to your WSGI configuration file*. Delete everything in it
and paste this, substituting your secret key from step 3:

```python
import os
import sys

project_home = "/home/Maaz2006/child-wellness"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_SECRET_KEY"] = "PASTE_THE_KEY_FROM_STEP_3"
os.environ["DJANGO_DEBUG"] = "false"
os.environ["DJANGO_ALLOWED_HOSTS"] = "Maaz2006.pythonanywhere.com"
os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = "https://Maaz2006.pythonanywhere.com"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Environment variables live here, not in a `.env` file: the WSGI file is the one
place PythonAnywhere guarantees is loaded before the app starts.

---

## 6. Web tab — the rest of the configuration

| Field | Value |
|---|---|
| Source code | `/home/Maaz2006/child-wellness` |
| Working directory | `/home/Maaz2006/child-wellness` |
| Virtualenv | `/home/Maaz2006/.virtualenvs/kito` |
| Static URL | `/static/` |
| Static paths | URL `/static/` → Directory `/home/Maaz2006/child-wellness/staticfiles` |

No `/media/` mapping is needed — the platform accepts no user file uploads.

---

## 7. Reload and verify

Click **Reload**, then:

```bash
curl -s https://Maaz2006.pythonanywhere.com/healthz/
```

Expected:

```json
{"status": "ok", "database": "ok", "debug": false}
```

Then open `https://Maaz2006.pythonanywhere.com/` in a browser and sign in.

---

## 8. Deploying later updates

```bash
cd ~/child-wellness
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Then **Reload** in the Web tab. Reload is required every time — changes to disk
are not picked up by the running process.

---

## Troubleshooting

**403 Forbidden / CSRF verification failed**
`DJANGO_CSRF_TRUSTED_ORIGINS` must include the scheme and exact host:
`https://Maaz2006.pythonanywhere.com`.

**DisallowedHost**
`DJANGO_ALLOWED_HOSTS` must contain `Maaz2006.pythonanywhere.com` (no scheme).

**CSS missing / unstyled pages**
Static mapping in step 6 points at `staticfiles/`, not `static/`. Re-run
`collectstatic` after any CSS change.

**`no module named config`**
Source code path and working directory are both `/home/Maaz2006/child-wellness`,
and the WSGI file inserts that path into `sys.path` (step 5).

**`database is locked`**
Rare under SQLite with concurrent writes. Retry; if persistent, the report
should note PostgreSQL as the migration path.

**Error log**
`/var/log/Maaz2006.pythonanywhere.com.error.log` in the Bash console.

---

## Uptime note

PythonAnywhere free apps are always-on, unlike most free hosts, so no keep-alive
pinger is required. The `/healthz/` endpoint exists anyway so an external
monitor (e.g. a free cron pinger) can prove availability during marking week and
give you a screenshot for the report.
