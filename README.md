# business-tuner-cron

Scheduler-only repository for the **Business Tuner / Voler suite**.

This repo contains **no application code** — only the GitHub Actions workflow that
fires the suite's scheduled cron jobs by `curl`-ing the deployed apps' `/api/cron/**`
endpoints on a schedule. The application code lives in the private `business-tuner`
repo; this repo exists solely so the scheduler runs on **public-repo GitHub Actions**
(unlimited free minutes) instead of consuming the private repo's 2,000 min/month.

## How it works

`.github/workflows/cron-jobs.yml` triggers on `schedule:` (and manual
`workflow_dispatch`). Each job sends an authenticated request:

```
curl -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}" \
     "${{ secrets.ST_DEPLOY_URL }}/api/cron/<job>"
```

The target apps validate the bearer token (`verifyCronRequest`) and reject anything
without the secret with `401`. **The endpoint paths visible in the YAML are not
sensitive on their own** — they cannot be triggered without `CRON_SECRET`.

### Kill-switch

A `st-cron-preflight` job reads `GET /api/cron/pause-status` once per run and exposes
`all` + `paused[]`. Each scheduled ST job self-skips when its category (or `all`) is
paused (set from the BT admin UI → "Pausa Cron"). Manual `workflow_dispatch` runs
always run. The preflight is **fail-open**: if `pause-status` is unreachable, nothing
is paused.

## Required secrets (Settings → Secrets and variables → Actions)

| Secret | Required | Value |
|---|---|---|
| `CRON_SECRET` | yes | Must match each app's `CRON_SECRET` env var on Railway |
| `ST_DEPLOY_URL` | yes | Public base URL of the strategy-tuner deploy (no trailing slash) |
| `CT_DEPLOY_URL` | yes (for the CT dispatch job) | Public base URL of the content-tuner deploy |
| `SLACK_CRON_WEBHOOK` | optional | Slack incoming webhook for failure alerts |

These are **not** stored in this repo's files — only as encrypted GitHub secrets.

## Keep scheduled workflows alive

GitHub disables scheduled workflows after **60 days with no repository activity**.
If this repo is left untouched, the schedule silently stops. Mitigation: a small
periodic commit (or the bundled `keepalive` reminder) every < 60 days.

## Source of truth

The canonical `cron-jobs.yml` is developed in the private `business-tuner` repo and
copied here. Keep them in sync, and ensure the private repo does **not** also run the
schedule (avoid double execution).
