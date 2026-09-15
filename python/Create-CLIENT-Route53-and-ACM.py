from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore

logger = logging.getLogger("route53_acm")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DOMAIN_REGEX = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
DEFAULT_VALIDATION_TIMEOUT_SECONDS: int = 60
DEFAULT_POLL_INTERVAL_SECONDS: float = 3.0


def get_clients(regional_acm_region: Optional[str] = None) -> Tuple[Any, Any, Any]:
    """Initialize and return Route53 and ACM clients (regional and us-east-1)."""
    if boto3 is None:
        raise RuntimeError("boto3 library is required to interact with AWS services")
    route53_client = boto3.client("route53")
    acm_client = boto3.client("acm", region_name=regional_acm_region)
    acm_east_client = boto3.client("acm", region_name="us-east-1")
    return route53_client, acm_client, acm_east_client


def validate_inputs(
    domain_name: str, base_sub_domain: str, ip_address: str
) -> Tuple[str, str, str]:
    """Validate domain, subdomain, and IP address formats."""
    cleaned_domain = domain_name.strip().rstrip(".").lower()
    cleaned_sub = base_sub_domain.strip().lower()
    cleaned_ip = ip_address.strip()

    if not DOMAIN_REGEX.match(cleaned_domain):
        raise ValueError(f"Invalid DOMAIN_NAME: {domain_name!r}")
    if not SUBDOMAIN_REGEX.match(cleaned_sub):
        raise ValueError(f"Invalid BASE_SUB_DOMAIN: {base_sub_domain!r}")
    try:
        ipaddress.ip_address(cleaned_ip)
    except ValueError:
        raise ValueError(f"Invalid IP_ADDRESS: {ip_address!r}")

    return cleaned_domain, cleaned_sub, cleaned_ip


def get_or_create_hosted_zone(route53_client: Any, domain_name: str) -> str:
    """Find existing public hosted zone matching domain exactly, or create a new one."""
    target_zone = f"{domain_name}."
    response = route53_client.list_hosted_zones_by_name(DNSName=domain_name)

    for zone in response.get("HostedZones", []):
        if zone.get("Name") == target_zone and not zone.get("Config", {}).get("PrivateZone"):
            zone_id = zone["Id"].split("/")[-1]
            logger.info("Found existing hosted zone %s for %s", zone_id, domain_name)
            return zone_id

    caller_ref = f"hz-{hashlib.sha256(domain_name.encode('utf-8')).hexdigest()[:24]}"
    logger.info("Creating new public hosted zone for %s", domain_name)
    created = route53_client.create_hosted_zone(
        Name=domain_name,
        CallerReference=caller_ref,
    )
    return created["HostedZone"]["Id"].split("/")[-1]


def upsert_dns_records(
    route53_client: Any, hosted_zone_id: str, dns_names: List[str], ip_address: str
) -> None:
    """Upsert A records in Route 53 in a single atomic batch."""
    changes = [
        {
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": name,
                "Type": "A",
                "TTL": 300,
                "ResourceRecords": [{"Value": ip_address}],
            },
        }
        for name in dns_names
    ]
    logger.info("Upserting %d DNS A-records in zone %s", len(changes), hosted_zone_id)
    route53_client.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={"Changes": changes},
    )


def get_or_request_certificate(acm_client: Any, domain_names: List[str]) -> str:
    """Return existing active/pending certificate or request a new one."""
    primary_domain = domain_names[0]
    response = acm_client.list_certificates(
        CertificateStatuses=["PENDING_VALIDATION", "ISSUED"]
    )
    for cert in response.get("CertificateSummaryList", []):
        if cert.get("DomainName") == primary_domain:
            arn = cert["CertificateArn"]
            logger.info("Reusing existing ACM certificate %s for %s", arn, primary_domain)
            return arn

    logger.info("Requesting new ACM certificate for %s", primary_domain)
    res = acm_client.request_certificate(
        DomainName=primary_domain,
        SubjectAlternativeNames=domain_names[1:],
        ValidationMethod="DNS",
    )
    return res["CertificateArn"]


def wait_for_validation_records(
    acm_client: Any,
    certificate_arn: str,
    timeout_seconds: int = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> List[Dict[str, str]]:
    """Poll ACM describe_certificate until validation DNS records are available."""
    start_time = time.monotonic()
    while (time.monotonic() - start_time) < timeout_seconds:
        desc = acm_client.describe_certificate(CertificateArn=certificate_arn)
        options = desc.get("Certificate", {}).get("DomainValidationOptions", [])
        records = [
            opt["ResourceRecord"]
            for opt in options
            if opt.get("ResourceRecord") and "Name" in opt["ResourceRecord"]
        ]
        if options and len(records) == len(options):
            return records
        time.sleep(poll_interval)

    logger.warning("Timeout waiting for ACM validation records for %s", certificate_arn)
    return []


def upsert_validation_dns_records(
    route53_client: Any, hosted_zone_id: str, records: List[Dict[str, str]]
) -> None:
    """Upsert certificate validation CNAME records into Route 53."""
    seen = set()
    changes = []
    for rec in records:
        key = (rec["Name"], rec["Type"], rec["Value"])
        if key not in seen:
            seen.add(key)
            changes.append(
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": rec["Name"],
                        "Type": rec["Type"],
                        "TTL": 300,
                        "ResourceRecords": [{"Value": rec["Value"]}],
                    },
                }
            )
    if changes:
        logger.info("Upserting %d certificate validation records", len(changes))
        route53_client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={"Changes": changes},
        )


def provision_dns_and_certificates(
    domain_name: str, base_sub: str, ip_address: str
) -> Dict[str, Any]:
    """Orchestrate Route 53 zone creation, DNS records, and dual ACM certificates."""
    dns_names = [
        f"{base_sub}.{domain_name}",
        f"{base_sub}-api.{domain_name}",
        f"ecoaas-api-{base_sub}.{domain_name}",
    ]
    route53_client, acm_client, acm_east = get_clients(
        regional_acm_region=os.getenv("AWS_REGION")
    )
    hosted_zone_id = get_or_create_hosted_zone(route53_client, domain_name)
    upsert_dns_records(route53_client, hosted_zone_id, dns_names, ip_address)

    cert_arn = get_or_request_certificate(acm_client, dns_names)
    cert_arn_east = get_or_request_certificate(acm_east, dns_names)

    records_reg = wait_for_validation_records(acm_client, cert_arn)
    records_east = wait_for_validation_records(acm_east, cert_arn_east)
    upsert_validation_dns_records(
        route53_client, hosted_zone_id, records_reg + records_east
    )

    return {
        "hostedZoneId": hosted_zone_id,
        "dnsNames": dns_names,
        "certificateArn": cert_arn,
        "certificateArnEast": cert_arn_east,
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entrypoint for DNS records and ACM certificate orchestration."""
    raw_domain = os.getenv("DOMAIN_NAME") or event.get("DOMAIN_NAME", "")
    raw_sub = os.getenv("BASE_SUB_DOMAIN") or event.get("BASE_SUB_DOMAIN", "")
    raw_ip = os.getenv("IP_ADDRESS") or event.get("IP_ADDRESS", "")

    if not raw_domain or not raw_sub or not raw_ip:
        msg = "Missing required configuration: DOMAIN_NAME, BASE_SUB_DOMAIN, or IP_ADDRESS."
        logger.error(msg)
        return {"statusCode": 400, "status": "CONFIG_ERROR", "message": msg}

    try:
        domain_name, base_sub, ip_address = validate_inputs(raw_domain, raw_sub, raw_ip)
        data = provision_dns_and_certificates(domain_name, base_sub, ip_address)
        return {
            "statusCode": 200,
            "status": "SUCCESS",
            "message": f"Certificates and DNS records configured for {domain_name}.",
            "data": data,
        }
    except ValueError as exc:
        logger.error("Input validation failed: %s", exc)
        return {"statusCode": 400, "status": "CONFIG_ERROR", "message": str(exc)}
    except Exception as exc:
        logger.error("Failed to provision DNS and ACM: %s", exc)
        return {"statusCode": 500, "status": "ERROR", "message": f"Provisioning error: {exc}"}
