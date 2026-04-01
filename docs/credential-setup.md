# Credential Setup Guide

nstd syncs tasks from four systems — GitHub, Jira, Asana, and Google
Calendar. Each requires its own credentials. This guide walks through
obtaining, configuring, and verifying each one.

All API tokens are stored in **macOS Keychain** via the `keyring` library.
They never appear in config files, logs, or source code. Google Calendar
is the exception — it uses OAuth files instead of Keychain.

> **Note:** `nstd setup` is not yet wired to the interactive setup wizard.
> For now, this guide is the **only supported setup path**. Once the wizard
> is implemented, it will wrap these same steps with interactive token
> verification and project discovery.

---

## Prerequisites

- macOS (Keychain Access required)
- Python 3.11+ with nstd installed (`pip install -e ".[dev]"`)
- A browser for Google Calendar OAuth

---

## 1. GitHub Personal Access Token

### Where to create it

<https://github.com/settings/tokens>

### Token type

Fine-grained PAT (recommended) or classic PAT.

### Required permissions

**Classic PAT scopes:**

| Scope | Why |
|-------|-----|
| `repo` | Read issues from private repos |
| `read:org` | Verify org membership for filtered repos |
| `read:project` | Read GitHub Projects v2 boards |

**Fine-grained PAT permissions:**

| Permission | Access | Why |
|------------|--------|-----|
| Issues | Read-only | Fetch assigned issues |
| Projects | Read-only | Read project board items |

Set repository access to the specific repos you want to sync.

### Steps

1. Go to **Settings → Developer settings → Personal access tokens**
2. Click **Generate new token**
3. Name: `nstd sync`
4. Expiration: 90 days recommended (you'll get email reminders)
5. Select the permissions above
6. Click **Generate token** and copy it

### Load into Keychain

```bash
# Avoid pasting tokens directly on the command line — they can leak via
# shell history. This flow prompts you securely instead.
read -s -p "GitHub PAT: " NSTD_TOKEN && echo
security add-generic-password \
  -s "nstd-github" \
  -a "YOUR_GITHUB_USERNAME" \
  -w "$NSTD_TOKEN" \
  -U
unset NSTD_TOKEN
```

### Keychain entry

| Field | Value |
|-------|-------|
| Service | `nstd-github` |
| Account | Your GitHub username (e.g., `nate-double-u`) |

### Verify manually

```bash
curl -s -H "Authorization: Bearer ghp_YOUR_TOKEN" \
  https://api.github.com/user | jq .login
```

Should print your GitHub username.

---

## 2. Jira API Token

### Determine your instance type

nstd needs to know whether your Jira instance is **Atlassian Cloud** or
**Jira Server / Data Center**, because the authentication mechanism differs.

| Instance | URL pattern | Auth method |
|----------|-------------|-------------|
| Atlassian Cloud | `*.atlassian.net` | API token (from id.atlassian.com) |
| Jira Server / Data Center | Custom domain (e.g., `jira.example.org`) | Personal Access Token (from Jira profile) |

> ⚠️ **Known issue:** The spec and setup wizard currently assume
> Atlassian Cloud and use Cloud API endpoints
> (`/rest/api/3/`). If your instance is Jira Server/Data Center
> (e.g., `jira.example.org`), the API version is `/rest/api/2/`
> and auth may differ. See [Jira Server notes](#jira-server--data-center) below.

### Atlassian Cloud

**Token URL:** <https://id.atlassian.com/manage-profile/security/api-tokens>

1. Click **Create API token**
2. Label: `nstd sync`
3. Copy the token

Permissions are inherited from your Jira user account — no scopes to
configure. You need at minimum:

- Browse and read issues in your configured projects
- View issue transitions (for write-back)

### Jira Server / Data Center

1. Log in to your Jira instance
2. Go to **Profile → Personal Access Tokens**
3. Click **Create token**
4. Name: `nstd sync`
5. Set an expiry if required by your admin
6. Copy the token

nstd uses the `jira` Python library with Basic auth (`username:token`),
which works for both Cloud API tokens and Server PATs.

**Quick connectivity check:**

```bash
# Cloud:
curl -s -u "you@example.com:YOUR_TOKEN" \
  https://YOUR_INSTANCE.atlassian.net/rest/api/3/myself | jq .displayName

# Server:
curl -s -u "you@example.com:YOUR_TOKEN" \
  https://jira.example.org/rest/api/2/myself | jq .displayName
```

### Load into Keychain

```bash
read -s -p "Jira token: " NSTD_TOKEN && echo
security add-generic-password \
  -s "nstd-jira" \
  -a "your.email@example.org" \
  -w "$NSTD_TOKEN" \
  -U
unset NSTD_TOKEN
```

### Keychain entry

| Field | Value |
|-------|-------|
| Service | `nstd-jira` |
| Account | Your Jira username (typically your email address) |

### What else you'll need

The setup wizard will prompt for these, but have them ready:

- **Server URL** — e.g., `https://jira.example.org` or
  `https://yourinstance.atlassian.net` or `https://jira.example.org`
- **Projects** — Jira project keys to sync (e.g., `MYPROJECT`)
- **Start date field** — Setup auto-discovers this from your instance's
  custom fields

---

## 3. Asana Personal Access Token

### Where to create it

<https://app.asana.com/0/my-apps>

### Steps

1. Scroll to **Personal access tokens**
2. Click **Create new token**
3. Name: `nstd sync`
4. Read and accept the API terms
5. Copy the token

Asana PATs inherit your user's permissions — no granular scopes to
configure. You need read access to your workspaces and projects.

### Load into Keychain

```bash
read -s -p "Asana PAT: " NSTD_TOKEN && echo
security add-generic-password \
  -s "nstd-asana" \
  -a "YOUR_GITHUB_USERNAME" \
  -w "$NSTD_TOKEN" \
  -U
unset NSTD_TOKEN
```

> **Note:** The Keychain account for Asana is your **GitHub username**,
> not your Asana email. This is intentional — it keeps Keychain lookups
> consistent across services.

### Keychain entry

| Field | Value |
|-------|-------|
| Service | `nstd-asana` |
| Account | Your GitHub username (e.g., `nate-double-u`) |

### Verify manually

```bash
curl -s -H "Authorization: Bearer YOUR_ASANA_PAT" \
  https://app.asana.com/api/1.0/users/me | jq .data.name
```

### What else you'll need

Setup will auto-discover these, but for reference:

- **Workspace GID** — discovered from your Asana account
- **Project GIDs** — you'll pick from a list of your projects

---

## 4. Google Calendar (OAuth 2.0)

Google Calendar uses OAuth 2.0, not a static API token. This requires a
Google Cloud project with the Calendar API enabled.

> ⚠️ **Managed Google Workspace:** If your Google account is managed by
> your organization, the OAuth consent screen may
> require admin approval. If you hit a "This app is blocked" screen during
> the OAuth flow, contact your Workspace admin to allowlist the app or add
> you as a test user.

### Step 1: Create a Google Cloud OAuth client

1. Go to <https://console.cloud.google.com/>
2. Create a new project (or use an existing personal one)
   - Suggested name: `nstd`
3. **Enable the Google Calendar API:**
   - Navigate to **APIs & Services → Library**
   - Search for "Google Calendar API"
   - Click **Enable**
4. **Configure the OAuth consent screen:**
   - Go to **APIs & Services → OAuth consent screen**
   - User type: **Internal** (if your Workspace allows) or **External**
   - App name: `nstd`
   - Add scope: `https://www.googleapis.com/auth/calendar`
   - If External: add your email as a test user (testing mode supports
     up to 100 users without Google review)
5. **Create OAuth client credentials:**
   - Go to **APIs & Services → Credentials**
   - Click **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name: `nstd`
   - Click **Create**, then **Download JSON**

### Step 2: Install the client secret file

```bash
mkdir -p ~/.config/nstd/credentials/

cp ~/Downloads/client_secret_*.json \
   ~/.config/nstd/credentials/google_client_secret.json
```

### Step 3: Authorize (first run)

The first time nstd accesses Google Calendar, it will:

1. Open your default browser to Google's consent page
2. You sign in and authorize nstd to access your calendar
3. The OAuth token is saved to `~/.config/nstd/credentials/google_token.json`
4. Future runs auto-refresh the token silently

### OAuth scope

`https://www.googleapis.com/auth/calendar` — full read and write access.

nstd needs write access to create and update time-block events on your
NSTD Planning calendar. Read access alone is insufficient.

### Files

| File | Path | Source |
|------|------|--------|
| Client secret | `~/.config/nstd/credentials/google_client_secret.json` | Downloaded from Cloud Console |
| OAuth token | `~/.config/nstd/credentials/google_token.json` | Auto-generated on first authorization |

The token file is auto-managed. Don't edit it. If authorization breaks,
delete `google_token.json` and re-authorize.

### What else you'll need

Before running setup, create a calendar named **NSTD Planning** in
Google Calendar. This is the calendar nstd will write time blocks to.
You'll also pick which other calendars to observe for availability
(e.g., your primary calendar, team shared calendars).

---

## Summary

| System | Auth type | Where to get it | Keychain service | Keychain account |
|--------|-----------|-----------------|------------------|------------------|
| GitHub | PAT | [github.com/settings/tokens](https://github.com/settings/tokens) | `nstd-github` | GitHub username |
| Jira | API token / PAT | [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens) or Jira profile | `nstd-jira` | Jira username (email) |
| Asana | PAT | [app.asana.com/0/my-apps](https://app.asana.com/0/my-apps) | `nstd-asana` | GitHub username |
| Google Calendar | OAuth 2.0 | [Cloud Console](https://console.cloud.google.com/) | *(files, not Keychain)* | — |

## Directory layout after setup

```
~/.config/nstd/
├── config.toml                     # Non-secret configuration
├── credentials/
│   ├── google_client_secret.json   # Downloaded from Cloud Console
│   └── google_token.json           # Auto-generated on first OAuth
└── nstd.db                         # SQLite database (created on first sync)
```

## Troubleshooting

**"GitHub/Jira/Asana token not found in Keychain"**
: Use the `security add-generic-password` commands above to store the token.
  Verify with `security find-generic-password -s "nstd-github"`.

**"This app is blocked" (Google OAuth)**
: Your Google Workspace admin needs to approve the OAuth app, or you need
  to add yourself as a test user in the Cloud Console OAuth consent screen.

**Jira 401 / 403 errors**
: Confirm whether your instance is Cloud or Server and use the matching
  auth method. Server instances use `/rest/api/2/`, Cloud uses
  `/rest/api/3/`.

**Token expired**
: GitHub and Asana PATs expire based on your settings (check email for
  reminders). Google OAuth tokens auto-refresh. Jira Cloud API tokens
  don't expire but can be revoked by admins.

**Updating a stored token**
: Re-run the `read -s` + `security add-generic-password` flow from above.
  The `-U` flag updates an existing entry.
