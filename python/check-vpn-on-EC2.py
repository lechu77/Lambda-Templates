from __future__ import annotations

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

logger = logging.getLogger("vpn_monitor")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

# Polling and execution defaults
DEFAULT_TIMEOUT_SECONDS: int = 30
DEFAULT_POLL_INTERVAL: float = 2.0
HOSTNAME_REGEX = re.compile(r"^[a-zA-Z0-9.-]+$")
IN_PROGRESS_STATUSES = ("Pending", "InProgress", "Delayed")


def get_clients(
    region_name: Optional[str] = None,
) -> Tuple[Any, Any]:
    """Return initialized boto3 SSM and EC2 clients."""
    if boto3 is None:
        raise RuntimeError("boto3 library is required to interact with AWS services")
    ssm_client = boto3.client("ssm", region_name=region_name)
    ec2_client = boto3.client("ec2", region_name=region_name)
    return ssm_client, ec2_client


def validate_target(target: str, port_str: str) -> Tuple[str, int]:
    """Validate target IP or hostname and numeric port range."""
    cleaned_target = target.strip()
    try:
        ipaddress.ip_address(cleaned_target)
    except ValueError:
        if not HOSTNAME_REGEX.match(cleaned_target):
            raise ValueError(f"Invalid target IP address or hostname: {target!r}")

    try:
        port = int(port_str.strip())
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        raise ValueError(f"Port must be an integer between 1 and 65535. Received: {port_str!r}")

    return cleaned_target, port


def run_command_on_instance(
    ssm_client: Any,
    instance_id: str,
    commands: List[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> Tuple[str, Dict[str, Any]]:
    """Execute shell commands on an EC2 instance via SSM with bounded polling."""
    response = ssm_client.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
    )
    command_id = response["Command"]["CommandId"]

    start_time = time.monotonic()
    status = "Pending"
    output: Dict[str, Any] = {}

    while status in IN_PROGRESS_STATUSES:
        if (time.monotonic() - start_time) > timeout_seconds:
            logger.error("SSM command %s timed out after %ds", command_id, timeout_seconds)
            return "TimedOut", {"StandardOutputContent": "", "StandardErrorContent": "Timeout"}

        time.sleep(poll_interval)
        output = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id,
        )
        status = output.get("Status", "Failed")

    return status, output


def terminate_instance(ec2_client: Any, instance_id: str, enable_terminate: bool) -> bool:
    """Terminate instance if explicitly permitted by configuration."""
    if not enable_terminate:
        logger.warning(
            "Auto-terminate is disabled. Skipping termination for instance %s", instance_id
        )
        return False

    try:
        ec2_client.terminate_instances(InstanceIds=[instance_id])
        logger.info("Instance %s termination initiated.", instance_id)
        return True
    except Exception as exc:
        logger.error("Failed to terminate instance %s: %s", instance_id, exc)
        return False


def execute_recovery_flow(
    ssm_client: Any,
    ec2_client: Any,
    instance_id: str,
    test_command: str,
    restart_command: str,
    enable_terminate: bool,
) -> Dict[str, Any]:
    """Execute VPN restart and re-verification upon initial test failure."""
    logger.warning("VPN test failed. Attempting restart with: %s", restart_command)
    restart_status, restart_out = run_command_on_instance(
        ssm_client, instance_id, [restart_command]
    )

    if restart_status == "Success":
        logger.info("VPN service restarted. Retrying connectivity check...")
        retry_status, retry_out = run_command_on_instance(
            ssm_client, instance_id, [test_command]
        )
        if retry_status == "Success":
            logger.info("VPN connection restored successfully after service restart.")
            return {
                "statusCode": 200,
                "status": "RECOVERED",
                "message": "VPN connection recovered after service restart.",
            }
        logger.error("VPN test failed again after restart. Status: %s", retry_status)
    else:
        logger.error("VPN restart command failed. Status: %s", restart_status)

    terminated = terminate_instance(ec2_client, instance_id, enable_terminate)
    result_status = "TERMINATED" if terminated else "UNHEALTHY"
    return {
        "statusCode": 500,
        "status": result_status,
        "message": f"VPN check failed. Instance state: {result_status.lower()}.",
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entrypoint for VPN monitoring and recovery."""
    instance_id = os.getenv("EC2_INSTANCE_ID", "").strip()
    raw_target = os.getenv("TARGET_IP", "").strip()
    raw_port = os.getenv("PORT", "").strip()
    test_base = os.getenv("VPN_TEST_COMM", "nc -w3 -zvvv").strip()
    restart_comm = os.getenv("VPN_RESTART_COMM", "sudo systemctl restart strongswan").strip()
    enable_terminate = os.getenv("ENABLE_AUTO_TERMINATE", "false").lower() in ("true", "1", "yes")

    if not instance_id or not raw_target or not raw_port:
        msg = "Missing required environment variables: EC2_INSTANCE_ID, TARGET_IP, or PORT."
        logger.error(msg)
        return {"statusCode": 400, "status": "CONFIG_ERROR", "message": msg}

    try:
        target_ip, port = validate_target(raw_target, raw_port)
    except ValueError as exc:
        logger.error("Target validation error: %s", exc)
        return {"statusCode": 400, "status": "CONFIG_ERROR", "message": str(exc)}

    test_command = f"{test_base} {target_ip} {port}"

    try:
        ssm_client, ec2_client = get_clients(region_name=os.getenv("AWS_REGION"))
        status, output = run_command_on_instance(ssm_client, instance_id, [test_command])

        if status == "Success":
            logger.info("VPN test command executed successfully on instance %s", instance_id)
            return {
                "statusCode": 200,
                "status": "HEALTHY",
                "message": "VPN connection is healthy.",
            }

        return execute_recovery_flow(
            ssm_client, ec2_client, instance_id, test_command, restart_comm, enable_terminate
        )

    except Exception as exc:
        logger.error("Unexpected error during VPN health check: %s", exc)
        return {
            "statusCode": 500,
            "status": "ERROR",
            "message": f"Execution error: {exc}",
        }
