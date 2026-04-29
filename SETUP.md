# ActiveDecoy Setup Guide

## Prerequisites

- Python 3.10 or newer.
- Neo4j Desktop or a reachable Neo4j instance.
- LDAP access to the target directory in an authorized lab.
- VMware, VirtualBox, or UTM integration for the lab DC host.

## 1. Python Environment

1. Create and activate a virtual environment.
2. Install `requirements.txt`.
3. Confirm the backend imports cleanly before connecting to any lab systems.

## 2. Neo4j Configuration

1. Start Neo4j Desktop or your server instance.
2. Create a database dedicated to the lab.
3. Note the bolt URI, username, and password.
4. Add the credentials to your environment or launch configuration.
5. Import the Cypher payloads from the Deception workflow after review.

Recommended environment variables:

- `NEO4J_URI=bolt://localhost:7687`
- `NEO4J_USERNAME=neo4j`
- `NEO4J_PASSWORD=<strong-password>`

## 3. Hypervisor API Setup

### VMware

1. Create an account with read and console access to the lab virtualization endpoint.
2. Record the vCenter or ESXi hostname.
3. Provide the username and password in the Connection page or environment config.
4. Verify pyVmomi connectivity before using the bridge.

### VirtualBox

1. Install the VirtualBox Extension Pack if required by your lab.
2. Confirm the Python bindings match the installed VirtualBox version.
3. Supply the target VM name for the Washu Agent or the DC host.

### UTM

1. Create a trusted local wrapper script that can report VM health.
2. Pass the wrapper path through the Connection page.
3. Keep the wrapper minimal and auditable.

## 4. Active Directory Permissions

The account used by ActiveDecoy should have only the minimum permissions required for the lab.

Required capabilities usually include:

- Read access to directory objects and attributes.
- Permission to query group, user, and computer relationships.
- Access to collect the event log sources you plan to monitor.
- Permission to create the lab honey objects you intentionally deploy.

If you are testing honey-user creation or similar workflows, ensure the account has explicit authorization to create directory objects in the chosen OU.

## 5. Washu Agent Setup

The Washu Agent is the monitoring VM used to watch honey-object interaction.

1. Provision a small, isolated VM inside the lab network.
2. Install your preferred monitoring agent or log forwarder.
3. Confirm it can reach the domain controller and Neo4j endpoint as needed.
4. Register the VM in the hypervisor integration settings.
5. Keep the agent on a separate admin path from the honeypot objects it observes.

## 6. Launching the App

1. Start the FastAPI application with Uvicorn.
2. Open the login page in your browser.
3. Sign in with the development credentials for the lab build.
4. Walk through Connection, Visualization, Deception, and Monitoring in sequence.
