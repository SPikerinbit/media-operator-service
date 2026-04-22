# Dify Setup

Dify is used as the visual orchestrator. Operator performs the heavy work
through `/stage-jobs/*`.

## 1. Start Dify

Use your existing Dify Docker stack. On the original machine the startup script
expects these WSL container names:

- `docker-nginx-1`
- `docker-api-1`
- `docker-worker-1`
- `docker-worker_beat-1`
- `docker-plugin_daemon-1`
- `docker-db_postgres-1`
- `docker-redis-1`
- `docker-web-1`
- `docker-sandbox-1`
- `docker-ssrf_proxy-1`
- `docker-weaviate-1`

If your Dify stack uses different container names, update
`scripts\start_media_full_stack.ps1`.

## 2. Generate workflow JSON for your Docker gateway

Dify containers must be able to call the Windows host service. The default is:

```powershell
$env:OPERATOR_BASE_URL = "http://172.17.144.1:8090"
.\.venv-win\Scripts\python.exe .\scripts\build_media_dify_workflow.py
```

If your Docker gateway differs, change `OPERATOR_BASE_URL` before generating.
Common alternatives are `http://host.docker.internal:8090` or another WSL
gateway address.

## 3. Import workflow in Dify

In Dify:

1. Create or open the media Workflow app.
2. Import `dify_workflows\youtube_main_pipeline_workflow.json`.
3. Publish the workflow.
4. Copy the app id from the app URL or database.
5. Put it in `scripts\media.local.env.ps1`:

```powershell
$env:DIFY_APP_ID = "YOUR_DIFY_APP_ID"
```

## 4. Token lookup

`scripts\start_media_full_stack.ps1` reads the API token directly from Dify
PostgreSQL:

```sql
select token from api_tokens where app_id='<DIFY_APP_ID>' limit 1;
```

It also reads the published workflow id:

```sql
select workflow_id from apps where id='<DIFY_APP_ID>' limit 1;
```

The token is only placed in the Operator process environment. It is not sent to
the browser and is not written to Git.

## 5. Smoke test

After startup:

```powershell
Invoke-RestMethod http://localhost:8090/health | ConvertTo-Json -Depth 6
```

Confirm:

- `dify.configured` is `true`
- `dify.workflow_id` is not empty

Then submit one short video in `http://localhost:8090/media-ui`.

