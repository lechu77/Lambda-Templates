import boto3
import os
import hashlib
import hmac
import secrets
import json
from datetime import datetime, timedelta

instance_id = os.getenv('INSTANCE_ID')
region_name = os.getenv('AWS_ALT_REGION')
ec2 = boto3.client('ec2', region_name=region_name)

AUTH_USERNAME = os.getenv('AUTH_USERNAME', 'lechu')
AUTH_PASSWORD_HASH = os.getenv('AUTH_PASSWORD_HASH', '')
SESSION_SECRET = os.getenv('SESSION_SECRET', secrets.token_hex(32))

# Simple in-memory session storage (for demo - use DynamoDB in production)
sessions = {}

def create_session_token(username):
    """Create a secure session token"""
    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(hours=24)
    sessions[token] = {'username': username, 'expiry': expiry}
    return token

def verify_session_token(token):
    """Verify session token is valid"""
    if not token or token not in sessions:
        return False
    session = sessions[token]
    if datetime.utcnow() > session['expiry']:
        del sessions[token]
        return False
    return True

def get_cookie(headers, name):
    """Extract cookie value from headers"""
    cookie_header = headers.get('cookie', '')
    for cookie in cookie_header.split(';'):
        cookie = cookie.strip()
        if cookie.startswith(f'{name}='):
            return cookie[len(name)+1:]
    return None

def verify_credentials(username, password):
    """Verify username and password"""
    if username == AUTH_USERNAME:
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(password_hash, AUTH_PASSWORD_HASH)
    return False

def create_login_page(error_message=''):
    """Return login page HTML"""
    error_html = f'<div class="error">{error_message}</div>' if error_message else ''
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-cache, no-store, must-revalidate'
        },
        'body': f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Control Panel - Login</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .login-container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 400px;
        }}
        .lock-icon {{
            font-size: 48px;
            text-align: center;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
            text-align: center;
        }}
        .subtitle {{
            color: #666;
            text-align: center;
            margin-bottom: 30px;
            font-size: 14px;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            color: #333;
            font-weight: 500;
            margin-bottom: 8px;
        }}
        input {{
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            transition: border-color 0.3s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .btn-login {{
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.3s;
        }}
        .btn-login:hover {{
            background: #5568d3;
        }}
        .error {{
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            text-align: center;
        }}
        .powered-by {{
            text-align: center;
            font-size: 12px;
            color: #999;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="login-container">
        <div class="lock-icon">&#128274;</div>
        <h1>EC2 Control Panel</h1>
        <p class="subtitle">Please login to continue</p>
        {error_html}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn-login">Login</button>
        </form>
        <div class="powered-by">Secured Session Authentication</div>
    </div>
</body>
</html>'''
    }

def lambda_handler(event, context):
    print(f"Event: {json.dumps(event)}")
    
    # Get path and method
    path = event.get('rawPath', '/').lower()
    method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    headers = event.get('headers', {})
    
    # Handle login POST
    if path == '/login' and method == 'POST':
        try:
            body = event.get('body', '')
            if event.get('isBase64Encoded', False):
                import base64
                body = base64.b64decode(body).decode('utf-8')
            
            # Parse form data
            params = {}
            for param in body.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    # URL decode
                    value = value.replace('+', ' ')
                    params[key] = value
            
            username = params.get('username', '')
            password = params.get('password', '')
            
            if verify_credentials(username, password):
                # Create session
                token = create_session_token(username)
                
                # Redirect to status with session cookie
                return {
                    'statusCode': 302,
                    'headers': {
                        'Location': '/status',
                        'Set-Cookie': f'session={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=86400',
                        'Content-Type': 'text/html'
                    },
                    'body': ''
                }
            else:
                return create_login_page('Invalid username or password')
                
        except Exception as e:
            print(f"Login error: {e}")
            return create_login_page('Login error occurred')
    
    # Check authentication for protected paths
    if AUTH_PASSWORD_HASH and path not in ['/login', '/']:
        session_token = get_cookie(headers, 'session')
        
        if not verify_session_token(session_token):
            # Not authenticated - show login
            return create_login_page()
    
    # Root path - redirect to status or show login
    if path == '/' or path == '':
        session_token = get_cookie(headers, 'session')
        if AUTH_PASSWORD_HASH and not verify_session_token(session_token):
            return create_login_page()
        return {
            'statusCode': 302,
            'headers': {'Location': '/status'},
            'body': ''
        }
    
    # Handle EC2 operations
    try:
        if path == '/start':
            ec2.start_instances(InstanceIds=[instance_id])
            action_message = f"Instance {instance_id} is starting."
        
        elif path == '/stop':
            ec2.stop_instances(InstanceIds=[instance_id])
            action_message = f"Instance {instance_id} is stopping."
        
        elif path == '/status':
            instance_response = ec2.describe_instances(InstanceIds=[instance_id])
            instance_state = instance_response['Reservations'][0]['Instances'][0]['State']['Name']

            if instance_state == 'running':
                status_response = ec2.describe_instance_status(InstanceIds=[instance_id])
                if status_response['InstanceStatuses']:
                    instance_status_data = status_response['InstanceStatuses'][0]
                    system_status = instance_status_data['SystemStatus']['Status']
                    instance_status = instance_status_data['InstanceStatus']['Status']
                else:
                    system_status = "N/A"
                    instance_status = "N/A"
            else:
                system_status = "N/A"
                instance_status = "N/A"

            status_color = '#009900' if instance_state == 'running' else '#cc0000'
            status_emoji = '&#128994;' if instance_state == 'running' else '&#128308;'
            
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Instance Status</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #0066cc;
            border-bottom: 2px solid #0066cc;
            padding-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .info {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }}
        .status {{
            font-weight: bold;
            color: {status_color};
            font-size: 18px;
        }}
        .logout {{
            background: #dc3545;
            color: white;
            padding: 8px 15px;
            text-decoration: none;
            border-radius: 5px;
            font-size: 12px;
            transition: background 0.3s;
        }}
        .logout:hover {{
            background: #c82333;
        }}
        .actions {{
            margin-top: 20px;
            text-align: center;
        }}
        .btn {{
            display: inline-block;
            padding: 10px 20px;
            margin: 0 10px;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            transition: all 0.3s;
        }}
        .btn-start {{
            background: #28a745;
            color: white;
        }}
        .btn-stop {{
            background: #dc3545;
            color: white;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>
            EC2 Instance Status
            <a href="/logout" class="logout">Logout</a>
        </h1>
        <div class="info">
            <p><strong>Instance ID:</strong> {instance_id}</p>
            <p><strong>Instance State:</strong> <span class="status">{status_emoji} {instance_state.upper()}</span></p>
            <p><strong>System Status:</strong> {system_status}</p>
            <p><strong>Instance Status:</strong> {instance_status}</p>
        </div>
        <div class="actions">
            <a href="/start" class="btn btn-start">Start Instance</a>
            <a href="/stop" class="btn btn-stop">Stop Instance</a>
        </div>
    </div>
</body>
</html>"""
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'text/html; charset=utf-8'
                },
                'body': html_content
            }

        elif path == '/logout':
            return {
                'statusCode': 302,
                'headers': {
                    'Location': '/',
                    'Set-Cookie': 'session=; Path=/; HttpOnly; Secure; Max-Age=0',
                    'Content-Type': 'text/html'
                },
                'body': ''
            }

        else:
            action_message = "Invalid path. Please use /start, /stop, or /status."

        # Response for /start or /stop
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Instance Action</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }}
        h1 {{
            color: #0066cc;
            border-bottom: 2px solid #0066cc;
            padding-bottom: 10px;
        }}
        .message {{
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            font-size: 18px;
        }}
        .back-btn {{
            background: #0066cc;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
            display: inline-block;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>EC2 Instance Action</h1>
        <div class="message">
            <p>{action_message}</p>
        </div>
        <a href="/status" class="back-btn">View Status</a>
    </div>
</body>
</html>"""
        
    except Exception as e:
        print(f"Error: {e}")
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EC2 Instance Error</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #cc0000;
            border-bottom: 2px solid #cc0000;
            padding-bottom: 10px;
        }}
        .error {{
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
            color: #721c24;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>EC2 Instance Error</h1>
        <div class="error">
            <p><strong>Error retrieving status for EC2 instance {instance_id}:</strong></p>
            <p>{str(e)}</p>
        </div>
    </div>
</body>
</html>"""

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        },
        'body': html_content
    }