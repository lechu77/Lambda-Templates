from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parent.parent / "python" / "EC2-StartStopStatus-Simple-Auth.py"
spec = importlib.util.spec_from_file_location("ec2_simple_auth", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load module from {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestEC2SimpleAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "test-secret-key-32-chars-long-abc"
        self.username = "testuser"
        self.test_password = "CorrectHorseBatteryStaple123!"
        self.password_hash = hashlib.sha256(self.test_password.encode("utf-8")).hexdigest()

        # Patch module-level auth configurations for testing
        mod.AUTH_USERNAME = self.username
        mod.AUTH_PASSWORD_HASH = self.password_hash
        mod.SESSION_SECRET = self.secret

    def test_create_session_token_generates_valid_signed_token(self) -> None:
        token = mod.create_session_token(self.username, secret=self.secret)
        self.assertIn(".", token)
        verified = mod.verify_session_token(token, secret=self.secret)
        self.assertEqual(verified, self.username)

    def test_verify_session_token_with_expired_token_returns_none(self) -> None:
        # Generate token with negative TTL
        token = mod.create_session_token(self.username, secret=self.secret, ttl_hours=-1)
        self.assertIsNone(mod.verify_session_token(token, secret=self.secret))

    def test_verify_session_token_with_tampered_payload_returns_none(self) -> None:
        token = mod.create_session_token(self.username, secret=self.secret)
        payload, sig = token.split(".", 1)
        tampered_token = f"{payload}extra.{sig}"
        self.assertIsNone(mod.verify_session_token(tampered_token, secret=self.secret))

    def test_verify_session_token_with_wrong_secret_returns_none(self) -> None:
        token = mod.create_session_token(self.username, secret=self.secret)
        self.assertIsNone(mod.verify_session_token(token, secret="different-secret-key-12345"))

    def test_verify_session_token_with_malformed_token_returns_none(self) -> None:
        self.assertIsNone(mod.verify_session_token("", secret=self.secret))
        self.assertIsNone(mod.verify_session_token("not-a-valid-token", secret=self.secret))
        self.assertIsNone(mod.verify_session_token(None, secret=self.secret))

    def test_get_cookie_with_lowercase_header_returns_value(self) -> None:
        headers = {"cookie": "session=abc123token; other=xyz"}
        self.assertEqual(mod.get_cookie(headers, "session"), "abc123token")

    def test_get_cookie_with_capitalized_header_returns_value(self) -> None:
        headers = {"Cookie": "theme=dark; session=capitalizedtoken"}
        self.assertEqual(mod.get_cookie(headers, "session"), "capitalizedtoken")

    def test_get_cookie_with_missing_cookie_returns_none(self) -> None:
        headers = {"cookie": "other=xyz"}
        self.assertIsNone(mod.get_cookie(headers, "session"))
        self.assertIsNone(mod.get_cookie({}, "session"))

    def test_verify_credentials_with_matching_password_returns_true(self) -> None:
        self.assertTrue(mod.verify_credentials(self.username, self.test_password))

    def test_verify_credentials_with_incorrect_password_returns_false(self) -> None:
        self.assertFalse(mod.verify_credentials(self.username, "WrongPassword!"))

    def test_verify_credentials_with_incorrect_username_returns_false(self) -> None:
        self.assertFalse(mod.verify_credentials("imposter", self.test_password))

    def test_verify_credentials_with_empty_hash_config_returns_false(self) -> None:
        mod.AUTH_PASSWORD_HASH = ""
        self.assertFalse(mod.verify_credentials(self.username, self.test_password))

    def test_parse_form_body_with_special_characters_url_decodes_correctly(self) -> None:
        # Form encoding containing symbols: user@test.com and p@ss&word=123
        encoded = "username=user%40test.com&password=p%40ss%26word%3D123"
        result = mod.parse_form_body(encoded)
        self.assertEqual(result.get("username"), "user@test.com")
        self.assertEqual(result.get("password"), "p@ss&word=123")

    def test_parse_form_body_with_base64_decodes_and_parses(self) -> None:
        plain = "username=alice&password=secretpassword"
        b64_str = base64.b64encode(plain.encode("utf-8")).decode("ascii")
        result = mod.parse_form_body(b64_str, is_base64=True)
        self.assertEqual(result.get("username"), "alice")
        self.assertEqual(result.get("password"), "secretpassword")

    def test_parse_form_body_with_empty_body_returns_empty_dict(self) -> None:
        self.assertEqual(mod.parse_form_body(""), {})

    def test_build_headers_includes_security_headers(self) -> None:
        headers = mod.build_headers()
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("Cache-Control", headers)

    def test_render_status_page_escapes_xss_and_renders_state(self) -> None:
        page = mod.render_status_page(
            instance_id="i-0123456789<script>",
            instance_state="running",
            system_status="ok",
            instance_status="ok",
        )
        self.assertEqual(page["statusCode"], 200)
        self.assertNotIn("<script>", page["body"])
        self.assertIn("i-0123456789&lt;script&gt;", page["body"])
        self.assertIn('action="/start"', page["body"])
        self.assertIn('action="/stop"', page["body"])
        self.assertIn('method="POST"', page["body"])

    def test_lambda_handler_login_post_valid_credentials_redirects_and_sets_cookie(self) -> None:
        event = {
            "rawPath": "/login",
            "requestContext": {"http": {"method": "POST"}},
            "body": f"username={self.username}&password={self.test_password}",
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], "/status")
        self.assertIn("session=", response["headers"]["Set-Cookie"])
        self.assertIn("HttpOnly", response["headers"]["Set-Cookie"])
        self.assertIn("SameSite=Strict", response["headers"]["Set-Cookie"])

    def test_lambda_handler_login_post_invalid_credentials_returns_login_error(self) -> None:
        event = {
            "rawPath": "/login",
            "requestContext": {"http": {"method": "POST"}},
            "body": f"username={self.username}&password=wrongpassword",
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Invalid username or password", response["body"])

    def test_lambda_handler_unauthenticated_protected_route_renders_login_page(self) -> None:
        event = {
            "rawPath": "/status",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("EC2 Control Panel", response["body"])
        self.assertIn('action="/login"', response["body"])

    @patch.dict("os.environ", {"INSTANCE_ID": "i-1234567890abcdef0"})
    @patch.object(mod, "get_ec2_client")
    def test_lambda_handler_authenticated_status_invokes_ec2_describe(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1234567890abcdef0",
                            "State": {"Name": "running"},
                        }
                    ]
                }
            ]
        }
        mock_client.describe_instance_status.return_value = {
            "InstanceStatuses": [
                {
                    "SystemStatus": {"Status": "ok"},
                    "InstanceStatus": {"Status": "ok"},
                }
            ]
        }
        mock_get_client.return_value = mock_client

        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/status",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("i-1234567890abcdef0", response["body"])
        self.assertIn("RUNNING", response["body"])
        mock_client.describe_instances.assert_called_once_with(InstanceIds=["i-1234567890abcdef0"])

    @patch.dict("os.environ", {"INSTANCE_ID": "i-1234567890abcdef0"})
    def test_lambda_handler_get_on_action_route_returns_405_method_not_allowed(self) -> None:
        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/start",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 405)
        self.assertEqual(response["headers"].get("Allow"), "POST")
        self.assertIn("Action requires POST", response["body"])

    @patch.dict("os.environ", {"INSTANCE_ID": "i-1234567890abcdef0"})
    @patch.object(mod, "get_ec2_client")
    def test_lambda_handler_post_on_start_invokes_ec2_start(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/start",
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Instance i-1234567890abcdef0 is starting", response["body"])
        mock_client.start_instances.assert_called_once_with(InstanceIds=["i-1234567890abcdef0"])

    @patch.dict("os.environ", {"INSTANCE_ID": "i-1234567890abcdef0"})
    @patch.object(mod, "get_ec2_client")
    def test_lambda_handler_post_on_stop_invokes_ec2_stop(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/stop",
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Instance i-1234567890abcdef0 is stopping", response["body"])
        mock_client.stop_instances.assert_called_once_with(InstanceIds=["i-1234567890abcdef0"])

    def test_lambda_handler_root_path_redirects_to_status(self) -> None:
        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], "/status")

    @patch.dict("os.environ", {"INSTANCE_ID": "i-1234567890abcdef0"})
    @patch.object(mod, "get_ec2_client")
    def test_lambda_handler_transitional_instance_state(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1234567890abcdef0",
                            "State": {"Name": "stopping"},
                        }
                    ]
                }
            ]
        }
        mock_get_client.return_value = mock_client

        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/status",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("STOPPING", response["body"])
        self.assertIn("#dd6b20", response["body"])

    @patch.dict("os.environ", {"INSTANCE_ID": "i-nonexistent"})
    @patch.object(mod, "get_ec2_client")
    def test_lambda_handler_instance_not_found_returns_error_page(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {"Reservations": []}
        mock_get_client.return_value = mock_client

        token = mod.create_session_token(self.username)
        event = {
            "rawPath": "/status",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"cookie": f"session={token}"},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("An error occurred while managing the EC2 instance", response["body"])

    def test_lambda_handler_logout_clears_cookie_and_redirects(self) -> None:
        event = {
            "rawPath": "/logout",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {},
        }
        response = mod.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], "/login")
        self.assertIn("Max-Age=0", response["headers"]["Set-Cookie"])

    def test_lambda_handler_missing_instance_id_returns_error_page(self) -> None:
        token = mod.create_session_token(self.username)
        with patch.dict("os.environ", {"INSTANCE_ID": ""}):
            event = {
                "rawPath": "/status",
                "requestContext": {"http": {"method": "GET"}},
                "headers": {"cookie": f"session={token}"},
            }
            response = mod.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 400)
            self.assertIn("INSTANCE_ID environment variable is not configured", response["body"])


if __name__ == "__main__":
    unittest.main()
