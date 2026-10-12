"""Read-only Gmail access for Homestead Scout — stdlib only.

Scope is exactly `gmail.readonly`, and that is enforced twice: the authorization request
asks for nothing else, and `api_get` refuses any endpoint outside a GET allowlist. There
is no code path in this module that can send, delete, label, archive, trash, or mark mail
read, because the functions that would do so do not exist.

Credentials are Homestead's own, at /var/lib/homestead/scout-gmail/. Prospect's token is
never read: sharing one mutable token file across two services means either service's
re-authorization silently breaks the other, and it widens one credential's blast radius
to both projects.

Nothing here prints a client secret, refresh token, access token, or authorization code.
"""
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me/"

# Every endpoint this client may ever request. Read-only by construction: `messages` for
# the bounded list and `messages/<id>` for one message.
_ALLOWED_ENDPOINTS = re.compile(r"^messages(?:/[A-Za-z0-9_-]+)?$")

DEFAULT_CREDENTIALS_PATH = "/var/lib/homestead/scout-gmail/client_secret.json"
DEFAULT_TOKEN_PATH = "/var/lib/homestead/scout-gmail/token.json"


class GmailError(RuntimeError):
    pass


def _installed(document):
    credentials = document.get("installed") or document.get("web") or {}
    if not credentials.get("client_id") or not credentials.get("client_secret"):
        raise GmailError("OAuth client JSON must contain installed.client_id and client_secret")
    return credentials


def _post_form(url, payload):
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        # `detail` is Google's error code (invalid_grant, ...) -- never the secret.
        raise GmailError(f"OAuth request failed ({exc.code}): {detail or 'no detail'}") from None


def _write_private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.chmod(path, 0o600)


def authorize(credentials_path=DEFAULT_CREDENTIALS_PATH, token_path=DEFAULT_TOKEN_PATH):
    """Interactive one-time authorization against a loopback redirect.

    Prints the authorization URL and nothing else of substance. The resulting token is
    written 0600 and its contents are never echoed.
    """
    document = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
    credentials = _installed(document)
    state = secrets.token_urlsafe(24)
    captured = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != "/oauth2callback":
                self.send_response(404)
                self.end_headers()
                return
            ok = query.get("state", [""])[0] == state and query.get("code")
            captured["code"] = query.get("code", [""])[0] if ok else ""
            captured["error"] = "" if ok else (query.get("error", ["state mismatch"])[0])
            body = (b"Homestead Scout Gmail access is authorized. You may close this tab."
                    if ok else b"Authorization failed.")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    # Port 0 picks a free port, which is right when the browser is on this host. Alpha is
    # headless, so authorizing from a laptop means tunnelling the callback back here --
    # and a tunnel needs a port known before the URL is printed.
    port = int(os.environ.get("HOMESTEAD_SCOUT_OAUTH_PORT", "0") or 0)
    server = HTTPServer(("127.0.0.1", port), Callback)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    parameters = {
        "client_id": credentials["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "false",
        "prompt": "consent",
        "state": state,
    }
    print(f"AUTHORIZATION_URL={_AUTH_ENDPOINT}?{urllib.parse.urlencode(parameters)}", flush=True)
    try:
        server.handle_request()
    finally:
        server.server_close()
    if not captured.get("code"):
        raise GmailError(f"authorization did not complete: {captured.get('error') or 'no code'}")

    token = _post_form(_TOKEN_ENDPOINT, {
        "code": captured["code"],
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    if token.get("scope") and GMAIL_READONLY_SCOPE not in token["scope"].split():
        raise GmailError("Google returned a token without the gmail.readonly scope")
    token["expiry_epoch"] = time.time() + float(token.get("expires_in", 3600))
    _write_private_json(token_path, token)
    return {"token_path": str(token_path), "scope": GMAIL_READONLY_SCOPE}


def load_auth(credentials_path=DEFAULT_CREDENTIALS_PATH, token_path=DEFAULT_TOKEN_PATH):
    try:
        document = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
        token = json.loads(Path(token_path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GmailError(
            f"missing Gmail credential file: {exc.filename}. Run `scout_gmail.py authorize` first."
        ) from None
    return {"credentials": _installed(document), "token": token, "token_path": str(token_path)}


def _access_token(auth):
    token = auth["token"]
    if token.get("access_token") and float(token.get("expiry_epoch", 0)) > time.time() + 60:
        return token["access_token"]
    if not token.get("refresh_token"):
        # Google only returns a refresh_token on a consent-prompt authorization. Without
        # one there is no unattended path back; say so instead of failing obscurely at 2am.
        raise GmailError("stored token has no refresh_token; run `scout_gmail.py authorize` again")
    refreshed = _post_form(_TOKEN_ENDPOINT, {
        "client_id": auth["credentials"]["client_id"],
        "client_secret": auth["credentials"]["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type": "refresh_token",
    })
    token.update(refreshed)
    token["expiry_epoch"] = time.time() + float(refreshed.get("expires_in", 3600))
    # Google does not resend refresh_token on refresh; preserve the original.
    _write_private_json(auth["token_path"], token)
    return token["access_token"]


def api_get(auth, endpoint, parameters=None):
    """Perform one authenticated GET against an allowlisted read-only endpoint."""
    if not _ALLOWED_ENDPOINTS.match(endpoint):
        raise GmailError(f"refusing non-allowlisted Gmail endpoint: {endpoint}")
    url = _API_ROOT + endpoint
    query = {k: str(v) for k, v in (parameters or {}).items() if v is not None}
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {_access_token(auth)}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        raise GmailError(f"Gmail API {exc.code}: {message or 'request failed'}") from None
    except urllib.error.URLError as exc:
        raise GmailError(f"Gmail API unreachable: {exc.reason}") from None


def list_messages(auth, query, max_results=100):
    payload = api_get(auth, "messages", {"q": query, "maxResults": max_results})
    return payload.get("messages") or []


def get_message(auth, message_id):
    return api_get(auth, f"messages/{urllib.parse.quote(message_id, safe='')}", {"format": "full"})
