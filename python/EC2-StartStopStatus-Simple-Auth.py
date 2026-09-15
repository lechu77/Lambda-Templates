from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import html
from http.cookies import SimpleCookie
import json
import logging
import os
import secrets
from typing import Any, Dict, Mapping, Optional
import urllib.parse

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore

# Logging configuration
logger = logging.getLogger("ec2_control")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

# Configuration constants
AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "lechu")
AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")
SESSION_SECRET: str = os.getenv("SESSION_SECRET", "") or secrets.token_hex(32)
DEFAULT_SESSION_HOURS: int = 24

COMMON_CSS: str = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    background: #f5f7fb;
    color: #333;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.card {
    background: #ffffff;
    border-radius: 10px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    width: 100%;
    max-width: 540px;
    padding: 32px;
}
h1 {
    font-size: 22px;
    color: #1a202c;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.error {
    background: #fed7d7;
    border: 1px solid #feb2b2;
    color: #9b2c2c;
    padding: 12px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-size: 14px;
}
.form-group { margin-bottom: 16px; }
label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 13px; color: #4a5568; }
input {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-size: 14px;
}
input:focus { outline: 2px solid #3182ce; border-color: transparent; }
.btn {
    display: inline-block;
    padding: 10px 18px;
    border: none;
    border-radius: 6px;
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.2s;
}
.btn-primary { background: #3182ce; color: #fff; width: 100%; }
.btn-primary:hover { background: #2b6cb0; }
.btn-start { background: #38a169; color: #fff; margin-right: 10px; }
.btn-start:hover { background: #2f855a; }
.btn-stop { background: #e53e3e; color: #fff; }
.btn-stop:hover { background: #c53030; }
.logout {
    font-size: 13px;
    color: #e53e3e;
    text-decoration: none;
    font-weight: 500;
}
.logout:hover { text-decoration: underline; }
.info-row {
    display: flex;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid #edf2f7;
    font-size: 14px;
}
.actions { margin-top: 24px; text-align: center; }
"""

STATE_CONFIG: Dict[str, Dict[str, str]] = {
    "running": {"color": "#38a169", "emoji": "&#128994;"},
    "pending": {"color": "#d69e2e", "emoji": "&#128993;"},
    "stopping": {"color": "#dd6b20", "emoji": "&#128993;"},
    "shutting-down": {"color": "#dd6b20", "emoji": "&#128993;"},
    "stopped": {"color": "#e53e3e", "emoji": "&#128308;"},
    "terminated": {"color": "#718096", "emoji": "&#9899;"},
}


def build_headers(extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Build standardized HTTP response headers including security protections."""
    headers: Dict[str, str] = {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def create_session_token(
    username: str, secret: str = SESSION_SECRET, ttl_hours: int = DEFAULT_SESSION_HOURS
) -> str:
    """Create a stateless, cryptographically signed session token."""
    expiry_ts = int(datetime.now(timezone.utc).timestamp()) + (ttl_hours * 3600)
    payload_raw = json.dumps({"u": username, "exp": expiry_ts}, separators=(",", ":"))
    payload_b64 = (
        base64.urlsafe_b64encode(payload_raw.encode("utf-8")).decode("ascii").rstrip("=")
    )
    sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: Optional[str], secret: str = SESSION_SECRET) -> Optional[str]:
    """Verify stateless session token integrity and expiration."""
    if not token or not secret or "." not in token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    payload_b64, sig = parts
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            return None
        if datetime.now(timezone.utc).timestamp() > exp:
            return None
        return str(payload.get("u", ""))
    except Exception as exc:
        logger.debug("Error decoding session token: %s", exc)
        return None


def get_cookie(headers: Mapping[str, Any], name: str) -> Optional[str]:
    """Extract a cookie value by name case-insensitively."""
    cookie_header: str = ""
    for key, val in headers.items():
        if key.lower() == "cookie":
            cookie_header = str(val)
            break
    if not cookie_header:
        return None
    simple_cookie: SimpleCookie = SimpleCookie()
    try:
        simple_cookie.load(cookie_header)
        morsel = simple_cookie.get(name)
        return morsel.value if morsel else None
    except Exception as exc:
        logger.debug("Failed parsing cookie header: %s", exc)
        return None


def verify_credentials(username: str, password: str) -> bool:
    """Verify submitted username and password against configured hash."""
    if not AUTH_PASSWORD_HASH:
        logger.warning("AUTH_PASSWORD_HASH is not configured. Rejecting authentication.")
        return False
    if hmac.compare_digest(username, AUTH_USERNAME):
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(password_hash, AUTH_PASSWORD_HASH)
    return False


def parse_form_body(body: str, is_base64: bool = False) -> Dict[str, str]:
    """Safely parse urlencoded form body with proper URL decoding."""
    if not body:
        return {}
    if is_base64:
        try:
            body = base64.b64decode(body).decode("utf-8")
        except Exception as exc:
            logger.error("Failed to decode base64 body: %s", exc)
            return {}
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    return {key: val[0] for key, val in parsed.items() if val}


def render_login_page(error_message: str = "") -> Dict[str, Any]:
    """Render login form HTML."""
    escaped_err = (
        f'<div class="error">{html.escape(error_message)}</div>' if error_message else ""
    )
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Control Panel - Login</title>
    <style>{COMMON_CSS}</style>
</head>
<body>
    <div class="card">
        <h1>EC2 Control Panel</h1>
        {escaped_err}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn btn-primary">Login</button>
        </form>
    </div>
</body>
</html>"""
    return {"statusCode": 200, "headers": build_headers(), "body": body}


def render_status_rows(
    instance_id: str,
    instance_state: str,
    system_status: str,
    instance_status: str,
    cfg: Dict[str, str],
) -> str:
    """Render table rows for EC2 status card."""
    escaped_id = html.escape(instance_id)
    escaped_state = html.escape(instance_state.upper())
    escaped_sys = html.escape(system_status)
    escaped_inst = html.escape(instance_status)
    return f"""
        <div class="info-row"><strong>Instance ID</strong><span>{escaped_id}</span></div>
        <div class="info-row">
            <strong>State</strong>
            <span style="font-weight:bold; color:{cfg['color']};">
                {cfg['emoji']} {escaped_state}
            </span>
        </div>
        <div class="info-row"><strong>System Status</strong><span>{escaped_sys}</span></div>
        <div class="info-row"><strong>Instance Status</strong><span>{escaped_inst}</span></div>
    """


def render_status_page(
    instance_id: str,
    instance_state: str,
    system_status: str,
    instance_status: str,
) -> Dict[str, Any]:
    """Render instance status dashboard with POST action forms."""
    cfg = STATE_CONFIG.get(instance_state, {"color": "#4a5568", "emoji": "&#10067;"})
    escaped_id = html.escape(instance_id)
    rows_html = render_status_rows(
        instance_id, instance_state, system_status, instance_status, cfg
    )
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Status - {escaped_id}</title>
    <style>{COMMON_CSS}</style>
</head>
<body>
    <div class="card">
        <h1><span>EC2 Status</span><a href="/logout" class="logout">Logout</a></h1>
        {rows_html}
        <div class="actions">
            <form method="POST" action="/start" style="display:inline-block;">
                <button type="submit" class="btn btn-start">Start Instance</button>
            </form>
            <form method="POST" action="/stop" style="display:inline-block;">
                <button type="submit" class="btn btn-stop">Stop Instance</button>
            </form>
        </div>
    </div>
</body>
</html>"""
    return {"statusCode": 200, "headers": build_headers(), "body": body}


def render_action_page(message: str, is_error: bool = False) -> Dict[str, Any]:
    """Render action confirmation or error page."""
    escaped_msg = html.escape(message)
    msg_class = "error" if is_error else "info-row"
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Action Result</title>
    <style>{COMMON_CSS}</style>
</head>
<body>
    <div class="card" style="text-align:center;">
        <h1>EC2 Action Result</h1>
        <div class="{msg_class}" style="padding: 16px; margin: 16px 0; justify-content: center;">
            <p>{escaped_msg}</p>
        </div>
        <a href="/status" class="btn btn-primary" style="display:inline-block; width:auto;">
            View Status
        </a>
    </div>
</body>
</html>"""
    status_code = 400 if is_error else 200
    return {"statusCode": status_code, "headers": build_headers(), "body": body}


def get_ec2_client(region_name: Optional[str] = None) -> Any:
    """Instantiate and return boto3 ec2 client."""
    if boto3 is None:
        raise RuntimeError("boto3 library is required to interact with AWS EC2")
    return boto3.client("ec2", region_name=region_name)


def handle_ec2_status(ec2_client: Any, instance_id: str) -> Dict[str, Any]:
    """Query EC2 instance state and status checks."""
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    reservations = response.get("Reservations", [])
    if not reservations or not reservations[0].get("Instances"):
        raise ValueError(f"Instance {instance_id} was not found.")

    instance = reservations[0]["Instances"][0]
    instance_state = instance.get("State", {}).get("Name", "unknown")
    system_status = "N/A"
    instance_status = "N/A"

    if instance_state == "running":
        status_resp = ec2_client.describe_instance_status(InstanceIds=[instance_id])
        statuses = status_resp.get("InstanceStatuses", [])
        if statuses:
            system_status = statuses[0].get("SystemStatus", {}).get("Status", "N/A")
            instance_status = statuses[0].get("InstanceStatus", {}).get("Status", "N/A")

    return render_status_page(instance_id, instance_state, system_status, instance_status)


def handle_login(event: Dict[str, Any]) -> Dict[str, Any]:
    """Process login form submission and issue session cookie if valid."""
    form_data = parse_form_body(
        event.get("body", ""), event.get("isBase64Encoded", False)
    )
    username = form_data.get("username", "")
    password = form_data.get("password", "")

    if verify_credentials(username, password):
        token = create_session_token(username)
        cookie_val = (
            f"session={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=86400"
        )
        return {
            "statusCode": 302,
            "headers": build_headers(
                {"Location": "/status", "Set-Cookie": cookie_val}
            ),
            "body": "",
        }
    return render_login_page("Invalid username or password")


def handle_ec2_action(ec2_client: Any, path: str, instance_id: str) -> Dict[str, Any]:
    """Execute start or stop operations on target EC2 instance."""
    if path == "/start":
        ec2_client.start_instances(InstanceIds=[instance_id])
        return render_action_page(f"Instance {instance_id} is starting.")
    if path == "/stop":
        ec2_client.stop_instances(InstanceIds=[instance_id])
        return render_action_page(f"Instance {instance_id} is stopping.")
    return render_action_page(
        "Invalid path. Use /start, /stop, or /status.", is_error=True
    )


def is_authenticated(path: str, headers: Mapping[str, Any]) -> bool:
    """Determine whether request has valid authentication for protected path."""
    if not AUTH_PASSWORD_HASH or path in ("/login", "/logout"):
        return True
    session_token = get_cookie(headers, "session")
    return verify_session_token(session_token) is not None


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main AWS Lambda entrypoint."""
    path = (event.get("rawPath") or event.get("path") or "/").lower()
    http_ctx = event.get("requestContext", {}).get("http", {})
    method = (http_ctx.get("method") or event.get("httpMethod") or "GET").upper()
    headers = event.get("headers", {}) or {}

    instance_id = os.getenv("INSTANCE_ID", "")
    region_name = os.getenv("AWS_ALT_REGION")

    if path == "/login" and method == "POST":
        return handle_login(event)
    if not is_authenticated(path, headers):
        return render_login_page()
    if path in ("/", ""):
        return {"statusCode": 302, "headers": build_headers({"Location": "/status"}), "body": ""}
    if path == "/logout":
        expired = "session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"
        return {
            "statusCode": 302,
            "headers": build_headers({"Location": "/login", "Set-Cookie": expired}),
            "body": "",
        }
    if not instance_id:
        return render_action_page(
            "INSTANCE_ID environment variable is not configured.", is_error=True
        )
    if path in ("/start", "/stop") and method != "POST":
        err = render_action_page("Method Not Allowed. Action requires POST.", is_error=True)
        return {"statusCode": 405, "headers": build_headers({"Allow": "POST"}), "body": err["body"]}

    try:
        ec2_client = get_ec2_client(region_name=region_name)
        if path == "/status":
            return handle_ec2_status(ec2_client, instance_id)
        return handle_ec2_action(ec2_client, path, instance_id)
    except Exception as exc:
        logger.error("EC2 execution error: %s", exc)
        return render_action_page(
            "An error occurred while managing the EC2 instance.", is_error=True
        )