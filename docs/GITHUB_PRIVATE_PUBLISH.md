# Private GitHub Publishing

The project is intended for a private GitHub repository. Do not publish real
API keys, Bilibili cookies, generated videos, models, or logs.

## 1. Create a GitHub token

Create a fine-grained personal access token in GitHub with permission to create
and write private repositories for your account.

In the current PowerShell session:

```powershell
$env:GITHUB_TOKEN = "YOUR_TEMPORARY_GITHUB_TOKEN"
```

Do not write this token into any project file.

## 2. Run the publisher

```powershell
cd E:\projects\media-operator-service
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_private_github.ps1 -Owner YOUR_GITHUB_OWNER -Repo media-operator-service
```

The script will:

- back up `scripts\media.local.env.ps1`
- initialize Git if needed
- run a secret scan
- create or reuse a private repository
- commit safe files only
- push using a temporary auth header
- restore your real local env file

## 3. Verify privacy

Open:

```text
https://github.com/YOUR_GITHUB_OWNER/media-operator-service
```

Confirm the repository says `Private`.

## 4. Verify no secrets were committed

```powershell
git ls-files
git grep -n "sk-"
git grep -n "SESSDATA"
git grep -n "BILI_JCT"
```

The grep commands should only find placeholder documentation or nothing.

## 5. Clone test

```powershell
cd E:\projects
git clone https://github.com/YOUR_GITHUB_OWNER/media-operator-service.git media-operator-service-clean
cd .\media-operator-service-clean
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -SkipHealthCheck
```

Then fill `scripts\media.local.env.ps1` and follow
[Windows setup](SETUP_WINDOWS.md).

