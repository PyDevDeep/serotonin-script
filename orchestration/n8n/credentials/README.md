# n8n Credentials & Workflow Setup

This document covers credential configuration and import instructions for the two n8n workflows
that power Serotonin Script's publishing pipeline.

> **Note:** All credentials are stored in n8n's encrypted internal store.
> They are never committed to the repository and never appear in `.env`.

---

## Workflows

| File | Name | Status |
|------|------|--------|
| `Main Publisher [Template].json` | Main Publisher | Template — requires credential wiring |
| `Seratonin Error Handler [Template].json` | Seratonin Error Handler | Template — requires URL update |

Both files are stored in `orchestration/n8n/` and imported manually via the n8n UI.
They are shipped as **templates** (placeholders instead of real credentials) so they are safe to commit.

---

## Main Publisher — Architecture

```
POST /webhook/publish-post
  └─► Switch (platform field)
        ├─► [0] telegram  → Send Telegram Message → Confirm Publication
        ├─► [1] twitter   → ⚠️  see note below
        └─► [2] threads   → Threads: Create Container → Threads: Publish → Confirm Publication
```

After any successful publish, `Confirm Publication` calls:
```
POST https://<your-api>/api/v1/confirm  {post_id, platform, content}
```
This is the callback that triggers `vectorize_post` in the Python backend.

> ⚠️ **Twitter/X branch (Switch output [1]) is not included in the current template.**
> The workflow file was exported without the configured X nodes.
> Import the X-enabled version separately when available, or add the X node manually:
> connect Switch output [1] → Twitter node (n8n built-in) → Confirm Publication.

---

## Required Credentials

### 1. Telegram

**n8n credential type:** `Telegram API`

Steps:
1. Create a bot via [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the HTTP API token
3. n8n → **Credentials** → **New** → search `Telegram API` → paste token
4. In the `Send Telegram Message` node, set **Chat ID** to your channel/group ID

To find Chat ID: forward a message from your channel to [@username_to_id_bot](https://t.me/username_to_id_bot)
or use `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message.

Placeholder to replace in workflow JSON:
```
"chatId": "YOUR_TELEGRAM_CHAT_ID"
credential id: "select-your-telegram-credential"
```

---

### 2. Threads

**n8n credential type:** none (raw HTTP requests with access token in query params)

Steps:
1. Go to [Meta for Developers](https://developers.facebook.com/) → your app → Threads API
2. Generate a long-lived access token (valid 60 days, refresh before expiry)
3. Find your Threads User ID: `GET https://graph.threads.net/v1.0/me?access_token=<TOKEN>`

Placeholders to replace in workflow JSON (two nodes — `Threads: Create Container` and `Threads: Publish`):
```
YOUR_THREADS_USER_ID   → your numeric Threads user ID
YOUR_THREADS_ACCESS_TOKEN → your long-lived access token
```

> **Token rotation:** Threads access tokens expire after 60 days.
> Add a calendar reminder to refresh the token before expiry.
> Refresh endpoint: `GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=<TOKEN>`

---

### 3. Twitter / X

**n8n credential type:** `Twitter OAuth2 API`

**Prerequisite:** Twitter Developer account on **Basic tier** ($100/month minimum) — the Free tier does not include write access to the v2 API.

Steps:
1. Go to [developer.twitter.com](https://developer.twitter.com) → **Projects & Apps** → **New App**
2. In the app settings → **User authentication settings** → enable **OAuth 2.0**
3. Set **App permissions** to `Read and write`
4. Set **Type of App** to `Web App, Automated App or Bot`
5. Set **Callback URI** to `https://your-n8n-domain.com/rest/oauth2-credential/callback`
   (or `http://localhost:5678/rest/oauth2-credential/callback` for local setup)
6. Copy **Client ID** and **Client Secret** from the **Keys and tokens** tab
7. n8n → **Credentials** → **New** → search `Twitter OAuth2 API` → paste Client ID and Client Secret → click **Connect** → authorize in the browser popup

Required OAuth 2.0 scopes: `tweet.write`, `tweet.read`, `users.read`, `offline.access`

The `offline.access` scope is required for n8n to refresh the token automatically without re-authorization.

**In the Main Publisher workflow**, Switch output `[1]` (twitter branch) connects to the X node. The node is configured to post via `POST https://api.twitter.com/2/tweets`. For long-form content that exceeds 280 characters, the workflow splits the text into a thread: each chunk is posted sequentially, with each reply referencing the previous tweet's `id` in the `reply.in_reply_to_tweet_id` field.

After the final tweet in the thread, the flow proceeds to `Confirm Publication` — same as Telegram and Threads branches.

> **Token refresh:** n8n handles OAuth 2.0 token refresh automatically when `offline.access` scope is granted. No manual rotation needed, unlike the Threads long-lived token.

---

### 4. Internal API URL

Both workflows make HTTP calls back to the FastAPI backend.

**Main Publisher** — `Confirm Publication` node:
```
https://your-api-domain.com/api/v1/confirm
```

**Seratonin Error Handler** — `Notify Error Slack` node:
```
https://your-internal-api.com/api/v1/slack/error
```

Replace both placeholders with your actual domain (or `http://backend:8001` if n8n runs in the same Docker network).

If n8n is in the same Docker Compose network as the backend, use the internal hostname directly — no public DNS needed:
```
http://backend:8001/api/v1/confirm
http://backend:8001/api/v1/slack/error
```

---

## Seratonin Error Handler — How It Works

This workflow is set as the **Error Workflow** for `Main Publisher`. When any node in `Main Publisher` throws an unhandled error, n8n automatically triggers this workflow.

It extracts from the error context:
- `post_id` — from the failed node's input body
- `platform` — inferred from the node name (`threads` or `telegram`; extend for `twitter`)
- `error_message` — the raw exception message
- `user_id` — from the node's query parameters

Then POSTs to `/api/v1/slack/error`, which sends a Block Kit error notification to the physician's Slack channel.

**To link it to Main Publisher:**
1. Open `Main Publisher` in n8n
2. Click the `⚙` (workflow settings) icon
3. Set **Error Workflow** → `Seratonin Error Handler`

---

## Import Instructions

1. Open n8n at `http://localhost:5678`
2. Go to **Workflows** → **Import from File**
3. Import `Seratonin Error Handler [Template].json` first
4. Import `Main Publisher [Template].json`
5. Open each workflow and replace all placeholders (see sections above)
6. Wire `Main Publisher` error workflow → `Seratonin Error Handler` (workflow settings)
7. Create and assign credentials in each node that requires them
8. Update both internal API URLs to point to the backend
9. Toggle **Active** on both workflows

Do not activate `Main Publisher` before `Seratonin Error Handler` is active — otherwise publish failures will have no error notification path.

---

## Placeholders Checklist

Before activating, confirm every placeholder has been replaced:

**Main Publisher:**
- [ ] `YOUR_TELEGRAM_CHAT_ID` in `Send Telegram Message`
- [ ] Telegram credential assigned in `Send Telegram Message`
- [ ] `YOUR_THREADS_USER_ID` in `Threads: Create Container`
- [ ] `YOUR_THREADS_ACCESS_TOKEN` in `Threads: Create Container`
- [ ] `YOUR_THREADS_USER_ID` in `Threads: Publish`
- [ ] `YOUR_THREADS_ACCESS_TOKEN` in `Threads: Publish`
- [ ] `https://your-api-domain.com` in `Confirm Publication`
- [ ] Twitter OAuth2 API credential created and authorized in n8n
- [ ] Twitter credential assigned in the X node (Switch output `[1]`)
- [ ] `offline.access` scope confirmed in Twitter app settings

**Seratonin Error Handler:**
- [ ] `https://your-internal-api.com` in `Notify Error Slack`
- [ ] Error workflow linked in Main Publisher settings