# Jarvis Assistant (starter)

A small cloud-hostable web assistant for the requested account. It can show up to 20 inbox messages from the last 30 days after the account owner authorizes Google OAuth, and turn a song request into a YouTube search link.

## Important limits and safety

- This app has **read-only Gmail access**. It does not send, delete, archive, or modify email, and it does not execute instructions found in email content.
- Email access is granted by signing in through Google OAuth; knowing an email address is not access permission. Google OAuth must be configured by the account owner/admin. If `xavier.edu.np` is managed by an organization, its admin may need to allow the OAuth app.
- Song playback occurs in the browser/device that opens YouTube, not on the cloud server. YouTube may require a user click/sign-in and this app does not bypass ads, account restrictions, or playback rules.
- OAuth tokens are held in server process memory and are not written to the repo or browser cookie. Restarting/redeploying the service clears them and requires reconnecting Gmail. Use HTTPS and keep the service private; do not expose this starter to other users.
- The configured hosting plan is a paid always-on web-service plan. A cloud service can keep running while your laptop is closed, but it cannot produce sound from a closed or powered-off laptop.

## Deploy on Render

1. Push this repository to GitHub and create a Render Web Service from it (or use the included `render.yaml` blueprint). The `starter` plan is intended to stay running; confirm current pricing before deployment.
2. In Google Cloud Console, create/select a project, enable the Gmail API, and configure the OAuth consent screen. Add the account as a test user if the consent screen is in testing mode.
3. Create an OAuth client ID of type **Web application**. Add the deployed URL plus `/oauth2callback` as an authorized redirect URI, for example `https://YOUR-SERVICE.onrender.com/oauth2callback`. Add the deployed origin as an authorized JavaScript origin if prompted.
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Render's environment settings. The blueprint supplies `FLASK_SECRET_KEY` and the requested `GMAIL_ADDRESS`.
5. Open the deployed service and choose **Connect Gmail**. Sign in as `manish11428@xavier.edu.np` and review/approve the read-only permission. If the account is Workspace-managed, ask its administrator about app access.

Do not put OAuth client secrets, API keys, or Google token files in GitHub. Set `COOKIE_SECURE=true` for HTTPS production.

## Local development

Use Python 3.11+, install `requirements.txt`, and set the variables in `.env.example` in your shell. Create a Google OAuth web client and authorize `http://localhost:8080/oauth2callback`. Start with `python app.py`, then open `http://localhost:8080`.

This is a safe starter, not a fully autonomous AI agent: it currently supports read-only recent email viewing and YouTube search links only. It does not use an AI model or perform arbitrary tasks.
