from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parent.parent / "python" / "check-vpn-on-EC2.py"
spec = importlib.util.spec_from_file_location("check_vpn_ec2", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load module from {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestCheckVpnEC2(unittest.TestCase):
    def setUp(self) -> None:
        self.instance_id = "i-0123456789abcdef0"
        self.target_ip = "10.0.1.100"
        self.port = "22"
        self.base_env = {
            "EC2_INSTANCE_ID": self.instance_id,
            "TARGET_IP": self.target_ip,
            "PORT": self.port,
            "VPN_TEST_COMM": "nc -w3 -zvvv",
            "VPN_RESTART_COMM": "sudo systemctl restart strongswan",
            "ENABLE_AUTO_TERMINATE": "false",
        }

    def test_validate_target_with_valid_ipv4(self) -> None:
        ip, port = mod.validate_target("192.168.1.1", "443")
        self.assertEqual(ip, "192.168.1.1")
        self.assertEqual(port, 443)

    def test_validate_target_with_valid_ipv6(self) -> None:
        ip, port = mod.validate_target("2001:db8::1", "8080")
        self.assertEqual(ip, "2001:db8::1")
        self.assertEqual(port, 8080)

    def test_validate_target_with_valid_hostname(self) -> None:
        host, port = mod.validate_target("vpn-gateway.corp.internal", "1194")
        self.assertEqual(host, "vpn-gateway.corp.internal")
        self.assertEqual(port, 1194)

    def test_validate_target_with_command_injection_attempt_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            mod.validate_target("10.0.0.1; rm -rf /", "22")

        with self.assertRaises(ValueError):
            mod.validate_target("10.0.0.1 | bash", "22")

        with self.assertRaises(ValueError):
            mod.validate_target("`whoami`.evil.com", "22")

    def test_validate_target_with_invalid_port_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            mod.validate_target("10.0.0.1", "0")

        with self.assertRaises(ValueError):
            mod.validate_target("10.0.0.1", "65536")

        with self.assertRaises(ValueError):
            mod.validate_target("10.0.0.1", "invalid_port")

    def test_terminate_instance_when_disabled_skips_call_and_returns_false(self) -> None:
        mock_ec2 = MagicMock()
        result = mod.terminate_instance(mock_ec2, self.instance_id, enable_terminate=False)
        self.assertFalse(result)
        mock_ec2.terminate_instances.assert_not_called()

    def test_terminate_instance_when_enabled_invokes_ec2_and_returns_true(self) -> None:
        mock_ec2 = MagicMock()
        result = mod.terminate_instance(mock_ec2, self.instance_id, enable_terminate=True)
        self.assertTrue(result)
        mock_ec2.terminate_instances.assert_called_once_with(InstanceIds=[self.instance_id])

    def test_terminate_instance_handles_exception_without_crashing(self) -> None:
        mock_ec2 = MagicMock()
        mock_ec2.terminate_instances.side_effect = RuntimeError("AccessDenied")
        result = mod.terminate_instance(mock_ec2, self.instance_id, enable_terminate=True)
        self.assertFalse(result)

    def test_run_command_on_instance_polls_pending_and_returns_success(self) -> None:
        mock_ssm = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.side_effect = [
            {"Status": "Pending"},
            {"Status": "InProgress"},
            {"Status": "Success", "StandardOutputContent": "Connection succeeded"},
        ]

        with patch("time.sleep", return_value=None):
            status, output = mod.run_command_on_instance(
                mock_ssm, self.instance_id, ["test-command"], timeout_seconds=10, poll_interval=0.1
            )

        self.assertEqual(status, "Success")
        self.assertEqual(output["StandardOutputContent"], "Connection succeeded")
        self.assertEqual(mock_ssm.get_command_invocation.call_count, 3)

    def test_run_command_on_instance_times_out_when_exceeding_duration(self) -> None:
        mock_ssm = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {"Status": "InProgress"}

        with patch("time.sleep", return_value=None), \
             patch("time.monotonic", side_effect=[0.0, 5.0, 15.0, 35.0]):
            status, output = mod.run_command_on_instance(
                mock_ssm, self.instance_id, ["test-command"], timeout_seconds=10, poll_interval=0.1
            )

        self.assertEqual(status, "TimedOut")

    def test_lambda_handler_missing_env_returns_config_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            res = mod.lambda_handler({}, None)
            self.assertEqual(res["statusCode"], 400)
            self.assertEqual(res["status"], "CONFIG_ERROR")
            self.assertIn("Missing required environment variables", res["message"])

    def test_lambda_handler_invalid_port_returns_config_error(self) -> None:
        env = {**self.base_env, "PORT": "99999"}
        with patch.dict("os.environ", env, clear=True):
            res = mod.lambda_handler({}, None)
            self.assertEqual(res["statusCode"], 400)
            self.assertEqual(res["status"], "CONFIG_ERROR")

    @patch.object(mod, "get_clients")
    def test_lambda_handler_initial_check_healthy(self, mock_get_clients: MagicMock) -> None:
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_get_clients.return_value = (mock_ssm, mock_ec2)

        with patch.dict("os.environ", self.base_env, clear=True), \
             patch.object(mod, "run_command_on_instance", return_value=("Success", {})):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(res["status"], "HEALTHY")
        mock_ec2.terminate_instances.assert_not_called()

    @patch.object(mod, "get_clients")
    def test_lambda_handler_recovers_after_service_restart(self, mock_get_clients: MagicMock) -> None:
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_get_clients.return_value = (mock_ssm, mock_ec2)

        # Sequence: Initial test fails -> Restart succeeds -> Retry test succeeds
        side_effects = [
            ("Failed", {}),
            ("Success", {}),
            ("Success", {}),
        ]
        with patch.dict("os.environ", self.base_env, clear=True), \
             patch.object(mod, "run_command_on_instance", side_effect=side_effects):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(res["status"], "RECOVERED")
        mock_ec2.terminate_instances.assert_not_called()

    @patch.object(mod, "get_clients")
    def test_lambda_handler_failed_restart_without_auto_terminate(self, mock_get_clients: MagicMock) -> None:
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_get_clients.return_value = (mock_ssm, mock_ec2)

        # Initial test fails -> Restart fails
        side_effects = [
            ("Failed", {}),
            ("Failed", {}),
        ]
        with patch.dict("os.environ", self.base_env, clear=True), \
             patch.object(mod, "run_command_on_instance", side_effect=side_effects):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 500)
        self.assertEqual(res["status"], "UNHEALTHY")
        mock_ec2.terminate_instances.assert_not_called()

    @patch.object(mod, "get_clients")
    def test_lambda_handler_failed_restart_with_auto_terminate_enabled(self, mock_get_clients: MagicMock) -> None:
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_get_clients.return_value = (mock_ssm, mock_ec2)

        env = {**self.base_env, "ENABLE_AUTO_TERMINATE": "true"}
        side_effects = [
            ("Failed", {}),
            ("Failed", {}),
        ]
        with patch.dict("os.environ", env, clear=True), \
             patch.object(mod, "run_command_on_instance", side_effect=side_effects):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 500)
        self.assertEqual(res["status"], "TERMINATED")
        mock_ec2.terminate_instances.assert_called_once_with(InstanceIds=[self.instance_id])

    @patch.object(mod, "get_clients")
    def test_lambda_handler_aws_exception_does_not_terminate_instance(self, mock_get_clients: MagicMock) -> None:
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_get_clients.return_value = (mock_ssm, mock_ec2)

        env = {**self.base_env, "ENABLE_AUTO_TERMINATE": "true"}
        with patch.dict("os.environ", env, clear=True), \
             patch.object(mod, "run_command_on_instance", side_effect=RuntimeError("SSM Service Throttled")):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 500)
        self.assertEqual(res["status"], "ERROR")
        mock_ec2.terminate_instances.assert_not_called()


if __name__ == "__main__":
    unittest.main()
