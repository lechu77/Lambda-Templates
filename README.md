# Lambda-Templates - by Lechu

This repository contains a collection of Python scripts designed to be used as AWS Lambda functions for various automation tasks.

## Python Scripts

### `check-vpn-on-EC2.py`

**Purpose:**

This Lambda function monitors the VPN connection on a specified EC2 instance. It executes a test command to verify connectivity. If the test fails, it attempts to restart the VPN service on the instance. If the connection is still not established after the restart attempt, the function will terminate the EC2 instance to prevent it from running in a misconfigured or non-functional state, thus saving costs.

**Implementation:**

1.  **Prerequisites:**
    *   An EC2 instance with the AWS Systems Manager (SSM) Agent installed and running.
    *   An IAM role attached to the EC2 instance with the `AmazonSSMManagedInstanceCore` managed policy. This allows SSM to execute commands on the instance.
    *   An IAM role for the Lambda function with the following permissions:
        *   `ssm:SendCommand`
        *   `ssm:GetCommandInvocation`
        *   `ec2:TerminateInstances`

2.  **Lambda Environment Variables:**
    *   `EC2_INSTANCE_ID`: The instance ID of the EC2 machine to be monitored.
    *   `VPN_TEST_COMM`: The shell command to execute on the instance to test the VPN connection. For example, `ping -c 1 10.0.0.1`.
    *   `VPN_RESTART_COMM`: The shell command to restart the VPN service. For example, `sudo systemctl restart openvpn`.
    *   `TARGET_IP`: The IP address that the `VPN_TEST_COMM` will use for its test.
    *   `PORT`: The port to be used in the `VPN_TEST_COMM`.

-

### `Create-CLIENT-Route53-and-ACM.py`

**Purpose:**

This Lambda function automates the setup of DNS records in AWS Route 53 and requests public SSL/TLS certificates from AWS Certificate Manager (ACM). It is useful for quickly provisioning the necessary DNS and certificate infrastructure for a new client or application.

**Implementation:**

1.  **Prerequisites:**
    *   An IAM role for the Lambda function with permissions for:
        *   `route53:CreateHostedZone`
        *   `route53:ListHostedZonesByName`
        *   `route53:ChangeResourceRecordSets`
        *   `acm:RequestCertificate`
        *   `acm:DescribeCertificate`
        *   `acm:ListCertificates`

2.  **Lambda Environment Variables:**
    *   `DOMAIN_NAME`: The root domain name (e.g., `example.com`).
    *   `BASE_SUB_DOMAIN`: The base subdomain for which to create records (e.g., `client1`). The script will create records for `client1.example.com`, `client1-api.example.com`, and `ecoaas-api-client1.example.com`.
    *   `IP_ADDRESS`: The IP address that the `A` records will point to.

-

### `EC2-StartStopStatus-Simple-Auth.py`

**Purpose:**

This Lambda function provides a simple, web-based authentication layer for controlling an EC2 instance. When placed behind an API Gateway or an Application Load Balancer, it presents a login page. After successful authentication, it allows the user to start, stop, and view the status of the EC2 instance through a basic web interface.

**Implementation:**

1.  **Prerequisites:**
    *   An EC2 instance that you want to control.
    *   An API Gateway or Application Load Balancer configured to trigger this Lambda function.
    *   An IAM role for the Lambda function with the following permissions:
        *   `ec2:StartInstances`
        *   `ec2:StopInstances`
        *   `ec2:DescribeInstances`

2.  **Lambda Environment Variables:**
    *   `INSTANCE_ID`: The instance ID of the EC2 machine to be controlled.
    *   `AWS_ALT_REGION`: The AWS region where the EC2 instance is located.
    *   `AUTH_USERNAME`: The username for authentication.
    *   `AUTH_PASSWORD_HASH`: The SHA256 hash of the password for authentication. You can generate this with a command like `echo -n "your_password" | shasum -a 256`.
    *   `SESSION_SECRET`: A long, random string used to secure session cookies. You can generate one with `openssl rand -hex 32`.