# 🐍 Lambda Templates by Lechu

Welcome to my collection of AWS Lambda functions! ⚡ This repository contains Python scripts designed for various automation tasks in AWS environments.

⚠️ **Disclaimer**: Regardless that I use these scripts in production environments, these scripts are provided as-is for educational and experimental purposes. Use at your own risk and thoroughly test in your own environment before any deployment. The author is not responsible for any damages or issues that may arise from using these scripts.

## 📋 Table of Contents

- [🔧 Infrastructure Automation](#-infrastructure-automation)
- [🖥️ EC2 Management](#️-ec2-management)
- [🌐 Network & VPN Monitoring](#-network--vpn-monitoring)
- [🚀 Quick Start](#-quick-start)
- [📖 Deployment Guide](#-deployment-guide)
- [🔒 Security Best Practices](#-security-best-practices)
- [🤝 Contributing](#-contributing)

## 🔧 Infrastructure Automation

### Route53 & ACM Certificate Manager
**File:** `python/Create-CLIENT-Route53-and-ACM.py`

Automates DNS setup and SSL certificate provisioning for new clients or applications.

**Features:**
- 🌐 **Hosted Zone Management**: Creates or uses existing Route53 hosted zones
- 📝 **DNS Record Creation**: Automatically creates A records for:
  - `{client}.{domain.com}`
  - `{client}-api.{domain.com}`
  - `ecoaas-api-{client}.{domain.com}`
- 🔐 **SSL Certificate Provisioning**: Requests ACM certificates for HTTPS
- ⚡ **Multi-region Support**: Works with both regional and us-east-1 ACM

**Environment Variables:**
```bash
DOMAIN_NAME=example.com
BASE_SUB_DOMAIN=client1
IP_ADDRESS=1.2.3.4
```

**IAM Permissions Required:**
- `route53:CreateHostedZone`
- `route53:ListHostedZonesByName`
- `route53:ChangeResourceRecordSets`
- `acm:RequestCertificate`
- `acm:DescribeCertificate`
- `acm:ListCertificates`

**Use Case:** Perfect for SaaS platforms needing to quickly provision DNS and certificates for new clients.

## 🖥️ EC2 Management

### EC2 Start/Stop Web Interface
**File:** `python/EC2-StartStopStatus-Simple-Auth.py`

Provides a secure web interface for controlling EC2 instances with simple authentication.

**Features:**
- 🔐 **Simple Authentication**: Username/password with SHA256 hashing
- 🍪 **Session Management**: Secure session tokens with expiration
- 🎛️ **Instance Control**: Start, stop, and check status of EC2 instances
- 🌐 **Web Interface**: Clean HTML interface for easy management
- 📱 **API Gateway Compatible**: Works with API Gateway or ALB

**Environment Variables:**
```bash
INSTANCE_ID=i-1234567890abcdef0
AWS_ALT_REGION=us-west-2
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=sha256_hash_of_password
SESSION_SECRET=random_32_byte_hex_string
```

**IAM Permissions Required:**
- `ec2:StartInstances`
- `ec2:StopInstances`
- `ec2:DescribeInstances`

**Security Features:**
- 🔒 Password hashing with SHA256
- 🎫 Secure session tokens
- ⏰ Session expiration (24 hours)
- 🛡️ HMAC-based token verification

**Use Case:** Ideal for providing controlled access to EC2 instances for non-technical users or temporary access scenarios.

## 🌐 Network & VPN Monitoring

### VPN Health Check & Auto-Recovery
**File:** `python/check-vpn-on-EC2.py`

Monitors VPN connections on EC2 instances and performs automatic recovery actions.

**Features:**
- 🔍 **Connectivity Testing**: Configurable network connectivity tests
- 🔄 **Auto-Recovery**: Automatic VPN service restart on failure
- 💰 **Cost Optimization**: Terminates non-functional instances to save costs
- 📊 **Detailed Logging**: Comprehensive logging for troubleshooting
- ⚙️ **SSM Integration**: Uses Systems Manager for remote command execution

**Environment Variables:**
```bash
EC2_INSTANCE_ID=i-1234567890abcdef0
VPN_TEST_COMM=nc -w3 -zvvv
VPN_RESTART_COMM=sudo systemctl restart strongswan
TARGET_IP=10.0.1.100
PORT=22
```

**IAM Permissions Required:**
- `ssm:SendCommand`
- `ssm:GetCommandInvocation`
- `ec2:TerminateInstances`

**Prerequisites:**
- EC2 instance with SSM Agent installed
- Instance role with `AmazonSSMManagedInstanceCore` policy

**Recovery Logic:**
1. 🧪 **Test Connection**: Execute connectivity test command
2. ✅ **Success**: Log success and exit
3. ❌ **Failure**: Attempt VPN service restart
4. 🔄 **Retry**: Test connection again after restart
5. 💀 **Terminate**: If still failing, terminate instance to prevent costs

**Use Case:** Essential for hybrid cloud environments with VPN connections that need high availability and cost control.

## 🚀 Quick Start

### Prerequisites
- AWS CLI configured with appropriate permissions
- Python 3.8+ runtime for Lambda
- Basic understanding of AWS Lambda and IAM

### Deployment Steps

1. **Clone the repository:**
```bash
git clone https://github.com/Lechu77/Lambda-Templates.git
cd Lambda-Templates
```

2. **Choose your function and configure environment variables**

3. **Deploy using AWS CLI:**
```bash
# Create deployment package
zip -r function.zip python/your-function.py

# Create Lambda function
aws lambda create-function \
  --function-name your-function-name \
  --runtime python3.9 \
  --role arn:aws:iam::account:role/lambda-execution-role \
  --handler your-function.lambda_handler \
  --zip-file fileb://function.zip \
  --environment Variables='{
    "ENV_VAR1":"value1",
    "ENV_VAR2":"value2"
  }'
```

## 📖 Deployment Guide

### Route53 & ACM Function
```bash
# Set environment variables
aws lambda update-function-configuration \
  --function-name route53-acm-setup \
  --environment Variables='{
    "DOMAIN_NAME":"example.com",
    "BASE_SUB_DOMAIN":"client1",
    "IP_ADDRESS":"1.2.3.4"
  }'

# Test the function
aws lambda invoke \
  --function-name route53-acm-setup \
  --payload '{}' \
  response.json
```

### EC2 Control Interface
```bash
# Generate password hash
echo -n "your_password" | shasum -a 256

# Generate session secret
openssl rand -hex 32

# Deploy with API Gateway
aws lambda update-function-configuration \
  --function-name ec2-control \
  --environment Variables='{
    "INSTANCE_ID":"i-1234567890abcdef0",
    "AWS_ALT_REGION":"us-west-2",
    "AUTH_USERNAME":"admin",
    "AUTH_PASSWORD_HASH":"your_sha256_hash",
    "SESSION_SECRET":"your_32_byte_hex"
  }'
```

### VPN Monitor Setup
```bash
# Configure monitoring
aws lambda update-function-configuration \
  --function-name vpn-monitor \
  --environment Variables='{
    "EC2_INSTANCE_ID":"i-1234567890abcdef0",
    "VPN_TEST_COMM":"nc -w3 -zvvv",
    "VPN_RESTART_COMM":"sudo systemctl restart strongswan",
    "TARGET_IP":"10.0.1.100",
    "PORT":"22"
  }'

# Schedule with EventBridge
aws events put-rule \
  --name vpn-monitor-schedule \
  --schedule-expression "rate(5 minutes)"
```

## 🔒 Security Best Practices

### IAM Roles
- 🎯 **Principle of Least Privilege**: Grant only necessary permissions
- 🏷️ **Resource-Specific Policies**: Limit access to specific resources when possible
- 📝 **Regular Audits**: Review and update permissions regularly

### Environment Variables
- 🔐 **Sensitive Data**: Use AWS Secrets Manager for passwords and keys
- 🔄 **Rotation**: Implement regular rotation of secrets
- 📊 **Monitoring**: Log access to sensitive environment variables

### Network Security
- 🌐 **VPC Configuration**: Deploy Lambda functions in private subnets when needed
- 🛡️ **Security Groups**: Configure appropriate security group rules
- 🔍 **Monitoring**: Enable CloudTrail and CloudWatch for audit trails

## 🏗️ Function Categories

| Category | Functions | Purpose |
|----------|-----------|---------|
| **Infrastructure** 🔧 | Route53 & ACM | DNS and certificate automation |
| **Compute** 🖥️ | EC2 Control | Instance management interface |
| **Monitoring** 🌐 | VPN Health Check | Network connectivity monitoring |

## 🎯 Best Practices

- 📝 **Error Handling**: Implement comprehensive error handling and logging
- ⏰ **Timeouts**: Set appropriate timeout values for your functions
- 💾 **Memory Optimization**: Right-size memory allocation for performance
- 🔄 **Retry Logic**: Implement exponential backoff for external API calls
- 📊 **Monitoring**: Use CloudWatch metrics and alarms
- 🧪 **Testing**: Test functions thoroughly in development environments

## 🤝 Contributing

Contributions are welcome! Please:

1. 🍴 Fork the repository
2. 🌿 Create a feature branch
3. ✅ Test your functions thoroughly
4. 📝 Update documentation
5. 🔄 Submit a pull request

### Code Standards
- Follow PEP 8 Python style guidelines
- Include comprehensive error handling
- Add detailed docstrings and comments
- Test with multiple AWS regions when applicable

## 📞 Support

For questions or issues:
- 🐛 Open an issue in this repository
- 📧 Contact: [Your contact information]

## 📄 License

This project is licensed under the terms included in the `LICENSE` file.

---

**⭐ If you find these Lambda functions useful, please give this repository a star!**

*Made with ❤️ by Lechu*
