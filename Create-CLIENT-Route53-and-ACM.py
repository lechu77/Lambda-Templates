import os
import time
import boto3
import json

def lambda_handler(event, context):
    domain_name = os.environ['DOMAIN_NAME']
    base_sub_domain = os.environ['BASE_SUB_DOMAIN']
    ip_address = os.environ['IP_ADDRESS']
    
    # Initialize Boto3 clients
    route53 = boto3.client('route53')
    acm = boto3.client('acm')
    acm_east = boto3.client('acm', region_name='us-east-1')
    
    # Check if hosted zone exists
    hosted_zones = route53.list_hosted_zones_by_name(DNSName=domain_name)
    if hosted_zones['HostedZones']:
        hosted_zone_id = hosted_zones['HostedZones'][0]['Id'].split('/')[-1]
    else:
        # Create hosted zone
        hosted_zone = route53.create_hosted_zone(
            Name=domain_name,
            CallerReference=str(hash(domain_name))
        )
        hosted_zone_id = hosted_zone['HostedZone']['Id'].split('/')[-1]
    
    # Create or Update DNS records
    dns_names = [
        f"{base_sub_domain}.{domain_name}",
        f"{base_sub_domain}-api.{domain_name}",
        f"ecoaas-api-{base_sub_domain}.{domain_name}"
    ]
    
    for dns_name in dns_names:
        route53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Changes': [
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': dns_name,
                            'Type': 'A',
                            'TTL': 300,
                            'ResourceRecords': [{'Value': ip_address}]
                        }
                    }
                ]
            }
        )
    
    # Function to request ACM certificates
    def request_acm_certificate(acm_client, domain_names):
        response = acm_client.request_certificate(
            DomainName=domain_names[0],  # Using the first subdomain as the primary
            SubjectAlternativeNames=domain_names[1:],  # Rest as SANs
            ValidationMethod='DNS'
        )
        return response['CertificateArn']
    
    # Request ACM certificates
    certificate_arn = request_acm_certificate(acm, dns_names)
    certificate_arn_east = request_acm_certificate(acm_east, dns_names)
    
    # Introduce delay to allow ACM time to populate DNS validation options
    time.sleep(10)
    
    # Function to add DNS records for certificate validation
    def add_cert_validation_dns(acm_client, certificate_arn):
        cert_details = acm_client.describe_certificate(CertificateArn=certificate_arn)
        for validation in cert_details['Certificate']['DomainValidationOptions']:
            if 'ResourceRecord' in validation:
                route53.change_resource_record_sets(
                    HostedZoneId=hosted_zone_id,
                    ChangeBatch={
                        'Changes': [
                            {
                                'Action': 'UPSERT',
                                'ResourceRecordSet': {
                                    'Name': validation['ResourceRecord']['Name'],
                                    'Type': validation['ResourceRecord']['Type'],
                                    'TTL': 300,
                                    'ResourceRecords': [{'Value': validation['ResourceRecord']['Value']}]
                                }
                            }
                        ]
                    }
                )
    
    # Add DNS records for certificate validation
    add_cert_validation_dns(acm, certificate_arn)
    add_cert_validation_dns(acm_east, certificate_arn_east)
    
    return {
        'statusCode': 200,
        'body': json.dumps(f'Certificates and DNS records successfully created/updated for {domain_name}.')
    }
