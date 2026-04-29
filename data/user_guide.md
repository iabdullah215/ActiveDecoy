# ActiveDecoy User Guide

## Overview

ActiveDecoy provides a lab-focused ITDR workflow for authenticated testing,
directory visibility, deception planning, and monitored response.

## Workflow

1. Authenticate with the development credentials.
2. Establish the directory bridge from the Connection page.
3. Review graph data in the Visualization page.
4. Deploy honey-object plans from the Deception page.
5. Track telemetry in the Monitoring page.

## Safety Notes

- Use only on systems you own or are explicitly authorized to test.
- Keep the management UI and directory access inside a controlled network segment.
- Review generated Cypher before applying it to Neo4j in production-like labs.
