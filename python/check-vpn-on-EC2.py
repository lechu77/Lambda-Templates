import boto3
import os
import time

def lambda_handler(event, context):
    ssm_client = boto3.client('ssm')
    ec2_client = boto3.client('ec2')
    
    # Retrieve environment variables
    ec2_instance_id = os.environ['EC2_INSTANCE_ID']
    vpn_test_command_base = os.environ['VPN_TEST_COMM']
    vpn_restart_command = os.environ['VPN_RESTART_COMM']
    target_ip = os.environ['TARGET_IP']
    port = os.environ['PORT']

    def run_command_on_instance(commands):
        response = ssm_client.send_command(
            InstanceIds=[ec2_instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': commands}
        )
        command_id = response['Command']['CommandId']
        
        # Polling loop to check the command status
        status = 'InProgress'
        while status == 'InProgress':
            time.sleep(2)  # Wait for 2 seconds before checking the status again
            output = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=ec2_instance_id
            )
            status = output['Status']
        
        return status, output

    try:
        # Construct the VPN test command
        vpn_test_command = f"{vpn_test_command_base} {target_ip} {port}"
        
        # First attempt to run the VPN test command
        status, output = run_command_on_instance([vpn_test_command])
        
        # Check if the command was successful
        if status == 'Success':
            print(f"VPN test command executed successfully")
            print(f"Command output: {output['StandardOutputContent']}")
        else:
            print(f"VPN test command failed. Status: {status}")
            print(f"Command output: {output['StandardOutputContent']}")
            print(f"Command error: {output['StandardErrorContent']}")
            
            # Restart VPN and retry the VPN test command
            print("Attempting to restart VPN...")
            restart_status, restart_output = run_command_on_instance([vpn_restart_command])
            if restart_status == 'Success':
                print("VPN restart successful. Retrying VPN test command...")
                retry_status, retry_output = run_command_on_instance([vpn_test_command])
                if retry_status == 'Success':
                    print(f"VPN test command executed successfully after VPN restart")
                    print(f"Command output: {retry_output['StandardOutputContent']}")
                else:
                    print(f"VPN test command failed after VPN restart. Status: {retry_status}")
                    print(f"Command output: {retry_output['StandardOutputContent']}")
                    print(f"Command error: {retry_output['StandardErrorContent']}")
                    terminate_instance(ec2_instance_id, ec2_client)
            else:
                print(f"Failed to restart VPN. Status: {restart_status}")
                print(f"Command output: {restart_output['StandardOutputContent']}")
                print(f"Command error: {restart_output['StandardErrorContent']}")
                terminate_instance(ec2_instance_id, ec2_client)
    
    except ssm_client.exceptions.InvalidInstanceId as e:
        print(f"InvalidInstanceId error: {str(e)}")
        terminate_instance(ec2_instance_id, ec2_client)
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        terminate_instance(ec2_instance_id, ec2_client)

def terminate_instance(instance_id, ec2_client):
    try:
        response = ec2_client.terminate_instances(
            InstanceIds=[instance_id]
        )
        print(f"Instance {instance_id} termination initiated.")
    except Exception as e:
        print(f"An error occurred while terminating the instance: {str(e)}")
