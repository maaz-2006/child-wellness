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

Useful surfaces to verify after a D5 deploy:

| URL | Expected when signed out |
|---|---|
| `/healthz/` | JSON `status: ok`, `debug: false` |
| `/alerts/` | redirect to sign-in (mentor queue) |
| `/alerts/family/` | redirect to sign-in (guardian view) |
| `/cohort/alerts/` | redirect to sign-in (admin aggregate) |
| `/cohort/pulse/` | redirect to sign-in (admin aggregate) |
| `/children/1/pulse/history/` | redirect to sign-in |
| `/alerts/999999/` | 404, not a 500 |

---

## 8. Deploying later updates

Open a **new** Bash console (consoles do not remember the virtualenv), then:

```bash
workon kito
cd ~/child-wellness
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py recompute_wellness   # rebuild derived scores/baselines
python manage.py evaluate_alerts      # run alert rules, persist findings
python manage.py collectstatic --noinput
```

`recompute_wellness` is only needed when the scoring method changes or the raw
data was imported outside the web app. It is safe to run every deploy: it
deletes and rebuilds the stored windows, and the same entries always produce the
same numbers for a given `method_version`. The score tables are derived, so a
missing run shows empty trends, not wrong ones.

`evaluate_alerts` recomputes scores first by default and then evaluates the
rules. It is idempotent: an alert already open for a rule is updated, not
duplicated, and `occurrences` only increments once per day. Safe to run as often
as you like. On the synthetic demo cohort it prints:

```
Evaluated 24 children as of <date>: 17 findings, 17 alerts
(urgent 4, concern 13, watch 0).
```

`backtest_alerts` is an evaluation tool, not part of a deploy. It replays the
rules over the labelled synthetic trajectories and prints precision, recall and
median lead time; it restores the current scores when it finishes. Do not run it
against a real cohort.

Before the first alert run on the host, make sure the school has a designated
safeguarding lead — urgent findings are assigned to that named person. Either
set it in `/django-admin/` under **School → safeguarding lead**, or let
`seed_demo` set one on a fresh demo database.

Then **Reload** in the Web tab. Reload is required every time — changes to disk
are not picked up by the running process.

`workon kito` is the step that is easy to forget. Without it, `python` resolves
to the system interpreter, which does not have your dependencies, and you get
`ModuleNotFoundError: No module named 'django'`. If `workon` itself is not
found, run `source ~/.bashrc` first, or activate directly:

```bash
source ~/.virtualenvs/kito/bin/activate
```

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
