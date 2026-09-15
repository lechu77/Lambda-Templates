from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parent.parent / "python" / "Create-CLIENT-Route53-and-ACM.py"
spec = importlib.util.spec_from_file_location("create_route53_acm", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load module from {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestCreateRoute53AndACM(unittest.TestCase):
    def setUp(self) -> None:
        self.domain_name = "example.com"
        self.base_sub = "client1"
        self.ip_address = "1.2.3.4"
        self.base_env = {
            "DOMAIN_NAME": self.domain_name,
            "BASE_SUB_DOMAIN": self.base_sub,
            "IP_ADDRESS": self.ip_address,
        }

    def test_validate_inputs_with_valid_data(self) -> None:
        d, s, ip = mod.validate_inputs("example.com", "client1", "1.2.3.4")
        self.assertEqual(d, "example.com")
        self.assertEqual(s, "client1")
        self.assertEqual(ip, "1.2.3.4")

    def test_validate_inputs_strips_trailing_dots_and_whitespace(self) -> None:
        d, s, ip = mod.validate_inputs("  my-domain.co.uk.  ", "  portal  ", "  10.0.0.1  ")
        self.assertEqual(d, "my-domain.co.uk")
        self.assertEqual(s, "portal")
        self.assertEqual(ip, "10.0.0.1")

    def test_validate_inputs_with_invalid_domain_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            mod.validate_inputs("invalid_domain", "portal", "1.2.3.4")

        with self.assertRaises(ValueError):
            mod.validate_inputs("http://example.com", "portal", "1.2.3.4")

    def test_validate_inputs_with_invalid_subdomain_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            mod.validate_inputs("example.com", "client@portal!", "1.2.3.4")

    def test_validate_inputs_with_invalid_ip_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            mod.validate_inputs("example.com", "client1", "999.999.999.999")

        with self.assertRaises(ValueError):
            mod.validate_inputs("example.com", "client1", "not-an-ip")

    def test_get_or_create_hosted_zone_returns_existing_public_zone(self) -> None:
        mock_r53 = MagicMock()
        mock_r53.list_hosted_zones_by_name.return_value = {
            "HostedZones": [
                {
                    "Id": "/hostedzone/Z123EXISTING",
                    "Name": "example.com.",
                    "Config": {"PrivateZone": False},
                }
            ]
        }
        zone_id = mod.get_or_create_hosted_zone(mock_r53, self.domain_name)
        self.assertEqual(zone_id, "Z123EXISTING")
        mock_r53.create_hosted_zone.assert_not_called()

    def test_get_or_create_hosted_zone_ignores_unrelated_or_private_zones(self) -> None:
        mock_r53 = MagicMock()
        mock_r53.list_hosted_zones_by_name.return_value = {
            "HostedZones": [
                {
                    "Id": "/hostedzone/ZPRIVATE",
                    "Name": "example.com.",
                    "Config": {"PrivateZone": True},
                },
                {
                    "Id": "/hostedzone/ZUNRELATED",
                    "Name": "example.org.",
                    "Config": {"PrivateZone": False},
                },
            ]
        }
        mock_r53.create_hosted_zone.return_value = {
            "HostedZone": {"Id": "/hostedzone/ZNEWCREATED"}
        }

        zone_id = mod.get_or_create_hosted_zone(mock_r53, self.domain_name)
        self.assertEqual(zone_id, "ZNEWCREATED")
        mock_r53.create_hosted_zone.assert_called_once()
        caller_ref = mock_r53.create_hosted_zone.call_args.kwargs["CallerReference"]
        self.assertTrue(caller_ref.startswith("hz-"))

    def test_upsert_dns_records_creates_batched_a_records(self) -> None:
        mock_r53 = MagicMock()
        dns_names = ["app.example.com", "api.example.com"]
        mod.upsert_dns_records(mock_r53, "Z123", dns_names, "1.2.3.4")

        mock_r53.change_resource_record_sets.assert_called_once()
        batch = mock_r53.change_resource_record_sets.call_args.kwargs["ChangeBatch"]
        self.assertEqual(len(batch["Changes"]), 2)
        self.assertEqual(batch["Changes"][0]["Action"], "UPSERT")
        self.assertEqual(batch["Changes"][0]["ResourceRecordSet"]["Type"], "A")
        self.assertEqual(
            batch["Changes"][0]["ResourceRecordSet"]["ResourceRecords"],
            [{"Value": "1.2.3.4"}],
        )

    def test_get_or_request_certificate_reuses_existing_certificate(self) -> None:
        mock_acm = MagicMock()
        mock_acm.list_certificates.return_value = {
            "CertificateSummaryList": [
                {
                    "CertificateArn": "arn:aws:acm:us-east-1:123456789:certificate/existing-cert",
                    "DomainName": "client1.example.com",
                }
            ]
        }
        arn = mod.get_or_request_certificate(mock_acm, ["client1.example.com", "api.example.com"])
        self.assertEqual(arn, "arn:aws:acm:us-east-1:123456789:certificate/existing-cert")
        mock_acm.request_certificate.assert_not_called()

    def test_get_or_request_certificate_requests_new_when_not_found(self) -> None:
        mock_acm = MagicMock()
        mock_acm.list_certificates.return_value = {"CertificateSummaryList": []}
        mock_acm.request_certificate.return_value = {
            "CertificateArn": "arn:aws:acm:us-east-1:123456789:certificate/new-cert"
        }
        arn = mod.get_or_request_certificate(mock_acm, ["client1.example.com", "api.example.com"])
        self.assertEqual(arn, "arn:aws:acm:us-east-1:123456789:certificate/new-cert")
        mock_acm.request_certificate.assert_called_once_with(
            DomainName="client1.example.com",
            SubjectAlternativeNames=["api.example.com"],
            ValidationMethod="DNS",
        )

    def test_wait_for_validation_records_returns_when_ready(self) -> None:
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {
            "Certificate": {
                "DomainValidationOptions": [
                    {
                        "DomainName": "client1.example.com",
                        "ResourceRecord": {
                            "Name": "_abc.client1.example.com.",
                            "Type": "CNAME",
                            "Value": "_xyz.acm-validations.aws.",
                        },
                    }
                ]
            }
        }
        records = mod.wait_for_validation_records(
            mock_acm, "arn:cert", timeout_seconds=5, poll_interval=0.01
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["Name"], "_abc.client1.example.com.")

    def test_wait_for_validation_records_returns_empty_on_timeout(self) -> None:
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {
            "Certificate": {
                "DomainValidationOptions": [
                    {"DomainName": "client1.example.com"}  # Missing ResourceRecord
                ]
            }
        }
        with patch("time.sleep", return_value=None), \
             patch("time.monotonic", side_effect=[0.0, 10.0, 25.0, 70.0]):
            records = mod.wait_for_validation_records(
                mock_acm, "arn:cert", timeout_seconds=60, poll_interval=0.1
            )
        self.assertEqual(records, [])

    def test_upsert_validation_dns_records_deduplicates_and_batches(self) -> None:
        mock_r53 = MagicMock()
        records = [
            {"Name": "_cname1.", "Type": "CNAME", "Value": "_val1."},
            {"Name": "_cname1.", "Type": "CNAME", "Value": "_val1."},  # duplicate
            {"Name": "_cname2.", "Type": "CNAME", "Value": "_val2."},
        ]
        mod.upsert_validation_dns_records(mock_r53, "Z123", records)
        mock_r53.change_resource_record_sets.assert_called_once()
        batch = mock_r53.change_resource_record_sets.call_args.kwargs["ChangeBatch"]
        self.assertEqual(len(batch["Changes"]), 2)

    def test_lambda_handler_missing_config_returns_config_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            res = mod.lambda_handler({}, None)
            self.assertEqual(res["statusCode"], 400)
            self.assertEqual(res["status"], "CONFIG_ERROR")

    def test_lambda_handler_invalid_ip_returns_config_error(self) -> None:
        env = {**self.base_env, "IP_ADDRESS": "invalid-ip"}
        with patch.dict("os.environ", env, clear=True):
            res = mod.lambda_handler({}, None)
            self.assertEqual(res["statusCode"], 400)
            self.assertEqual(res["status"], "CONFIG_ERROR")

    @patch.object(mod, "get_clients")
    def test_lambda_handler_e2e_successful_provisioning(self, mock_get_clients: MagicMock) -> None:
        mock_r53 = MagicMock()
        mock_acm = MagicMock()
        mock_acm_east = MagicMock()
        mock_get_clients.return_value = (mock_r53, mock_acm, mock_acm_east)

        mock_r53.list_hosted_zones_by_name.return_value = {
            "HostedZones": [
                {
                    "Id": "/hostedzone/ZTEST123",
                    "Name": "example.com.",
                    "Config": {"PrivateZone": False},
                }
            ]
        }
        mock_acm.list_certificates.return_value = {
            "CertificateSummaryList": [
                {
                    "CertificateArn": "arn:aws:acm:eu-west-1:123:cert/reg",
                    "DomainName": "client1.example.com",
                }
            ]
        }
        mock_acm_east.list_certificates.return_value = {
            "CertificateSummaryList": [
                {
                    "CertificateArn": "arn:aws:acm:us-east-1:123:cert/east",
                    "DomainName": "client1.example.com",
                }
            ]
        }
        mock_acm.describe_certificate.return_value = {
            "Certificate": {
                "DomainValidationOptions": [
                    {
                        "DomainName": "client1.example.com",
                        "ResourceRecord": {
                            "Name": "_val.client1.example.com.",
                            "Type": "CNAME",
                            "Value": "_dest.acm.",
                        },
                    }
                ]
            }
        }
        mock_acm_east.describe_certificate.return_value = {
            "Certificate": {
                "DomainValidationOptions": [
                    {
                        "DomainName": "client1.example.com",
                        "ResourceRecord": {
                            "Name": "_val.client1.example.com.",
                            "Type": "CNAME",
                            "Value": "_dest.acm.",
                        },
                    }
                ]
            }
        }

        with patch.dict("os.environ", self.base_env, clear=True):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["data"]["hostedZoneId"], "ZTEST123")
        self.assertEqual(res["data"]["certificateArn"], "arn:aws:acm:eu-west-1:123:cert/reg")
        self.assertEqual(res["data"]["certificateArnEast"], "arn:aws:acm:us-east-1:123:cert/east")

    @patch.object(mod, "get_clients")
    def test_lambda_handler_aws_error_returns_500(self, mock_get_clients: MagicMock) -> None:
        mock_r53 = MagicMock()
        mock_r53.list_hosted_zones_by_name.side_effect = RuntimeError("Route53 RateLimit")
        mock_get_clients.return_value = (mock_r53, MagicMock(), MagicMock())

        with patch.dict("os.environ", self.base_env, clear=True):
            res = mod.lambda_handler({}, None)

        self.assertEqual(res["statusCode"], 500)
        self.assertEqual(res["status"], "ERROR")
        self.assertIn("Route53 RateLimit", res["message"])


if __name__ == "__main__":
    unittest.main()
