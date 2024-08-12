import requests
import urllib3
import json
from requests.auth import HTTPBasicAuth
from getpass import getpass
from jinja2 import Environment, FileSystemLoader
from os import path
from pprint import pprint

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_token(bigip, url, creds):
    payload = {}
    payload['username'] = creds[0]
    payload['password'] = creds[1]
    payload['loginProviderName'] = 'tmos'

    token = bigip.post(url, json.dumps(payload), verify=False).json()['token']['token']
    return token

def bigip_get(bigip, url):
    response = bigip.get(url, verify=False)
    json_data = json.loads(response.content)
    return response, json_data
    
def bigip_post(bigip, url, payload):
    response = bigip.post(url, payload, verify=False)
    json_data = json.loads(response.content)
    return response, json_data

def get_bigip_gtm_vs(bigip, url_base, gtm_server):
    # List Existing Virtual Servers
    url_gtm_vs = f'{url_base}/tm/gtm/server/~Common~{gtm_server}/virtual-servers'
    response, vs_data = bigip_get(bigip, url_gtm_vs)
    existing_vs = []
    for item in vs_data['items']:
        existing_vs.append(item['name'])
    # print(f'\nExisting Virtual Server Names: {existing_vs}')
    return existing_vs

def main():
    # Get BIG-IP Login Information
    mgmt_ip_address = input('BIG IP Management IP Address: ')
    username = input('username: ')
    password = getpass(prompt='password: ')
    
    # Login to BIG-IP
    url_base = f'https://{mgmt_ip_address}/mgmt'
    url_auth = f'{url_base}/shared/authn/login'

    b = requests.session()
    b.headers.update({'Content-Type':'application/json'})
    b.auth = (username, password)
    b.verify = False

    token = get_token(b, url_auth, (username, password))

    print(f'\n\nToken: {token}')

    b.auth = None
    b.headers.update({'X-F5-Auth-Token': token})
  
    # Check if a New VS Needs to be created
    print('\n\n')
    create_vs = input('Do You Want to Create a New GTM Virtual Server (y/n)? ')
    if create_vs.lower() == 'y':
        # Get GTM Server Name
        print('\n\n')
        server_name = input('Existing GTM Server Name: ')

        # Check if GTM Server Exists
        url_gtm_server = f'{url_base}/tm/gtm/server/{server_name}'
        response, server_data = bigip_get(b, url_gtm_server)
        if response.status_code == 200:
            pprint(f'\n\nGTM Server Data: {server_data}')
        else:
            print(f'\n\nGTM Server: {server_name} Not Found')
            quit()

        # List Existing Virtual Servers
        existing_vs = get_bigip_gtm_vs(b, url_base, server_name)
        print(f'\nExisting Virtual Server Names: {existing_vs}')
        
        # Create GTM Virtual Server
        url_gtm_vs = f'{url_base}/tm/gtm/server/~Common~{server_name}/virtual-servers'
        print('\n\n')
        vs_name = input('New Virtual Server Name to Add to Existing GTM Server: ')
    
        if vs_name in existing_vs:
            print(f'\n\nA Virtual Server Named {vs_name} Already Exists')
            quit()
        else:
            print('\n\n')
            vs_destination = input('Virtual Server IP Address and Port (Example: 10.1.1.1:443): ')
            jinja_env = Environment(loader=FileSystemLoader("templates/"))
            vs_template = jinja_env.get_template("virtualserver.j2")
            vs_payload = vs_template.render(vs_name=vs_name, vs_destination=vs_destination)
            output_path = path.join(path.dirname(__file__),f'outputs/{vs_name}.json')
            with open(output_path, 'w') as output_file:
                output_file.write(vs_payload)
            response,vs_create_data = bigip_post(b, url_gtm_vs, vs_payload)
            if response.status_code == 200:
                print(f'\n\nVirtual Server {vs_name} Successfully Added to GTM Server {server_name}')
            else:
                print(f'\n\nError: {response.content}')
    
    # Check if a new wide IP needs to be created using AS3
    print('\n\n')
    create_wip = input('Do You Want to Create a New Wide IP using AS3 (y/n)? ')
    if create_wip.lower() == 'y':
        # Check AS3 Version
        url_as3_ver = f'{url_base}/shared/appsvcs/info'
        response, as3_ver = bigip_get(b, url_as3_ver)
        if response.status_code == 200:
            print(f'\n\nAS3 Version: {as3_ver['version']}')
        else:
            print('\n\nAS3 Not installed.  Please install AS3 before proceeding')
            quit()

        # Get Inputs for AS3 Declaration
        print('\n\n')
        job_name = input('Job Name: ')
        print('\n')
        tenant_name = input('Tenant Name: ')
        print('\n')
        domain_name = input('Fully Qualified Domain Name for Wide IP: ')
        print('\n')
        pool_name = input('Pool Name for Wide IP Pool: ')
        
        # Test if GTM Server name has been defined
        try:
            server_name
        except NameError:
            print('\n')
            server_name = input('Existing GTM Server Name: ')

        # Test if VS name has been defined
        try:
            vs_name
        except NameError:
            print('\n')
            existing_vs = get_bigip_gtm_vs(b, url_base, server_name)
            print(f'\nExisting Virtual Server Names: {existing_vs}')
            print('\n')
            vs_name = input('GTM Virtual Server Name: ')

        # Ask to Perform a Dry Run
        dry_run = input('Perform Dry Run (y/n)? ')
        if dry_run.lower() == 'y':
            dry_run = True
        # Render the Jinja Template
        jinja_env = Environment(loader=FileSystemLoader("templates/"))
        wip_as3_template = jinja_env.get_template("wip_as3.j2")
        wip_as3_payload = wip_as3_template.render(job_name=job_name, tenant_name=tenant_name, domain_name=domain_name, pool_name=pool_name, server_name=server_name, vs_name=vs_name, dry_run=dry_run)
        output_path = path.join(path.dirname(__file__),f'outputs/{job_name}.json')
        with open(output_path, 'w') as output_file:
            output_file.write(wip_as3_payload)
        
        # Post the Jinja Template
        url_as3_declare = f'{url_base}/shared/appsvcs/declare'
        response,wip_create_data = bigip_post(b, url_as3_declare, wip_as3_payload)
        if response.status_code == 200:
            print(f'\n\nWide IP {domain_name} Successfully Created')
            if dry_run == True:
                pprint(f'\nDry Run Details:\n{wip_create_data}')
        else:
            print(f'\n\nError: {response.content}')
    
    # Check if a new wide IP needs to be created using FAST
    print('\n\n')
    create_wip_fast = input('Do You Want to Create a New Wide IP using FAST (y/n)? ')
    if create_wip_fast.lower() == 'y':
        # Check AS3 Version
        url_as3_ver = f'{url_base}/shared/appsvcs/info'
        response, as3_ver = bigip_get(b, url_as3_ver)
        if response.status_code == 200:
            print(f'\n\nAS3 Version: {as3_ver['version']}')
        else:
            print('\n\nAS3 Not installed.  Please install AS3 before proceeding')
            quit()
        # Check FAST Version
        url_fast_ver = f'{url_base}/shared/fast/info'
        response, fast_ver = bigip_get(b, url_fast_ver)
        if response.status_code == 200:
            print(f'\n\nFAST Version: {fast_ver['version']}')
        else:
            print('\n\nFAST Not installed.  Please install FAST before proceeding')
            quit()

        # Get Inputs for FAST
        print('\n\n')
        job_name = input('Job Name: ')
        print('\n')
        tenant_name = input('Tenant Name: ')
        print('\n')
        domain_name = input('Fully Qualified Domain Name for Wide IP: ')
        print('\n')
        pool_name = input('Pool Name for Wide IP Pool: ')
        
        # Test if GTM Server name has been defined
        try:
            server_name
        except NameError:
            print('\n')
            server_name = input('Existing GTM Server Name: ')

        # Test if VS name has been defined
        try:
            vs_name
        except NameError:
            print('\n')
            existing_vs = get_bigip_gtm_vs(b, url_base, server_name)
            print(f'\nExisting Virtual Server Names: {existing_vs}')
            print('\n')
            vs_name = input('GTM Virtual Server Name: ')
        
        # Render the Jinja Template
        jinja_env = Environment(loader=FileSystemLoader("templates/"))
        wip_fast_template = jinja_env.get_template("wip_fast.j2")
        wip_fast_payload = wip_fast_template.render(tenant_name=tenant_name, domain_name=domain_name, pool_name=pool_name, server_name=server_name, vs_name=vs_name)
        output_path = path.join(path.dirname(__file__),f'outputs/{job_name}.json')
        with open(output_path, 'w') as output_file:
            output_file.write(wip_fast_payload)
        
        # Post the Jinja Template
        url_fast_declare = f'{url_base}/shared/fast/applications'
        response,wip_create_data = bigip_post(b, url_fast_declare, wip_fast_payload)
        if response.status_code == 202:
            print(f'\n\nWide IP {domain_name} Successfully Created')
        else:
            print(f'\n\nError: {response.content}')

    return


if __name__ == '__main__':
    main()