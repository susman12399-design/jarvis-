import base64
import os
import secrets
from email.header import decode_header, make_header
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import quote_plus

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "")
if not app.secret_key:
    raise RuntimeError("Set FLASK_SECRET_KEY to a long, random secret before starting the app.")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EXPECTED_EMAIL = os.environ.get("GMAIL_ADDRESS", "").strip().lower()
# Tokens are kept in process memory, not in browser cookies or repository files.
_credentials_by_session = {}


def oauth_config():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [url_for("oauth_callback", _external=True)],
        }
    }


def get_credentials():
    sid = session.get("sid")
    credentials = _credentials_by_session.get(sid)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
    return credentials


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)


def decode_part(data):
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def plain_text_body(payload):
    """Return plain-text MIME content only; never render email HTML as markup."""
    if payload.get("mimeType") == "text/plain":
        return decode_part(payload.get("body", {}).get("data"))
    for part in payload.get("parts", []):
        result = plain_text_body(part)
        if result:
            return result
    if payload.get("mimeType") == "text/html":
        parser = TextExtractor()
        parser.feed(decode_part(payload.get("body", {}).get("data")))
        return " ".join(parser.parts)
    return ""


def decoded_header(value):
    try:
        return str(make_header(decode_header(value or "")))
    except (ValueError, TypeError):
        return value or ""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis Assistant</title><style>
body{font:16px system-ui,sans-serif;max-width:850px;margin:3rem auto;padding:0 1rem;color:#172033;background:#f5f7fb}
main{background:white;border-radius:14px;padding:1.5rem;box-shadow:0 4px 24px #17203312}button,a.button{background:#2457d6;color:white;border:0;border-radius:7px;padding:.7rem 1rem;text-decoration:none;cursor:pointer}
input{padding:.7rem;width:min(70%,500px);border:1px solid #bbc3d1;border-radius:7px}.email{border-top:1px solid #e4e7ed;padding:1rem 0;overflow-wrap:anywhere}.muted{color:#5d6678}.notice{background:#fff7dc;padding:.8rem;border-radius:8px}
</style></head><body><main><h1>Jarvis Assistant</h1>
<p class="muted">A private starter for read-only Gmail access and YouTube song searches.</p>
<p class="notice">Email content is untrusted. Jarvis only displays email and helps summarize it; it does not follow instructions in messages, send mail, or change your account.</p>
{% if connected %}<p>Connected to <strong>{{ email }}</strong> · <a href="{{ url_for('disconnect') }}">Disconnect</a></p>
<form action="{{ url_for('emails_page') }}" method="get"><button>Read recent inbox emails</button></form>
{% else %}<p>Connect your Google account to authorize Gmail read-only access.</p><a class="button" href="{{ url_for('login') }}">Connect Gmail</a>{% endif %}
<h2>Ask Jarvis</h2><form action="{{ url_for('command') }}" method="post"><input name="command" placeholder="e.g. play Here Comes the Sun" required><button>Go</button></form>
{% if result %}<p>{{ result }}</p>{% endif %}
{% for email in emails %}<article class="email"><strong>{{ email.subject or '(No subject)' }}</strong><br><span class="muted">From {{ email.sender }} · {{ email.date }}</span><p>{{ email.body }}</p></article>{% endfor %}
</main></body></html>"""


@app.get("/")
def home():
    credentials = get_credentials()
    return render_template_string(PAGE, connected=bool(credentials), email=EXPECTED_EMAIL, emails=[], result=None)


@app.get("/auth/google")
def login():
    config = oauth_config()
    flow = Flow.from_client_config(config, scopes=SCOPES, state=session.get("oauth_state"))
    flow.redirect_uri = url_for("oauth_callback", _external=True)
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="false", prompt="consent")
    session["oauth_state"] = state
    return redirect(authorization_url)


@app.get("/oauth2callback")
def oauth_callback():
    expected_state = session.pop("oauth_state", None)
    if not expected_state or request.args.get("state") != expected_state:
        return "OAuth state check failed. Please try connecting again.", 400
    flow = Flow.from_client_config(oauth_config(), scopes=SCOPES, state=expected_state)
    flow.redirect_uri = url_for("oauth_callback", _external=True)
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    actual_email = profile.get("emailAddress", "").lower()
    if EXPECTED_EMAIL and actual_email != EXPECTED_EMAIL:
        return "The connected Google account does not match the configured GMAIL_ADDRESS.", 403
    sid = secrets.token_urlsafe(32)
    session["sid"] = sid
    _credentials_by_session[sid] = credentials
    return redirect(url_for("home"))


@app.get("/emails")
def emails_page():
    credentials = get_credentials()
    if not credentials:
        return redirect(url_for("login"))
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    listing = service.users().messages().list(userId="me", q="in:inbox newer_than:30d", maxResults=20).execute()
    emails = []
    for item in listing.get("messages", []):
        message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        headers = {h["name"].lower(): h.get("value", "") for h in message.get("payload", {}).get("headers", [])}
        sender_name, sender_address = parseaddr(decoded_header(headers.get("from", "")))
        emails.append({
            "subject": decoded_header(headers.get("subject", "")),
            "sender": sender_name or sender_address,
            "date": headers.get("date", ""),
            "body": plain_text_body(message.get("payload", {}))[:4000],
        })
    return render_template_string(PAGE, connected=True, email=EXPECTED_EMAIL or "your Google account", emails=emails, result=f"Showing up to {len(emails)} inbox messages from the last 30 days.")


@app.post("/command")
def command():
    text = request.form.get("command", "").strip()
    lowered = text.lower()
    if any(word in lowered for word in ("play", "song", "music")):
        query = text
        for phrase in ("play me", "play", "a song", "song", "music", "please"):
            query = query.replace(phrase, " ")
        query = " ".join(query.split()) or text
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        result = f"Open YouTube to play: {url} (playback happens in your browser and may require a click)."
        return render_template_string(PAGE, connected=bool(get_credentials()), email=EXPECTED_EMAIL, emails=[], result=result)
    if any(word in lowered for word in ("email", "inbox", "mail")):
        if not get_credentials():
            return redirect(url_for("login"))
        return redirect(url_for("emails_page"))
    return render_template_string(PAGE, connected=bool(get_credentials()), email=EXPECTED_EMAIL, emails=[], result="I can currently show recent Gmail messages or find a song on YouTube. This starter does not execute other actions.")


@app.get("/disconnect")
def disconnect():
    sid = session.pop("sid", None)
    session.pop("oauth_state", None)
    if sid:
        _credentials_by_session.pop(sid, None)
    return redirect(url_for("home"))


@app.get("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
