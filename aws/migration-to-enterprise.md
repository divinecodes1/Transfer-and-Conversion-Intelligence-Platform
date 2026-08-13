# Migration to an enterprise AWS environment

The Free Plan deployment already has private RDS, private API/refresh Lambda
subnets, HTTPS identity ingress and automated SSM rollout. Enterprise work is
therefore about resilience, governance and scale rather than closing basic
internet-exposure gaps.

| Concern | Free Plan deployment | Enterprise target |
|---|---|---|
| Egress | Keycloak EC2 doubles as one NAT instance | NAT Gateway per AZ or controlled egress proxies/endpoints |
| Identity | one Keycloak EC2 behind CloudFront | two or more instances, shared cache, health-aware load balancer/WAF |
| Database | private micro, single-AZ, one-day backups | Multi-AZ, 35-day backup, PITR and cross-region copy |
| Terraform state | two local states | encrypted S3 backend with lockfile, versioning and restricted CI role |
| Images | mutable tags, three retained | immutable digest promotion, signing and continuous scanning |
| Compute | Function URLs | API Gateway/ALB where throttling, private integration or WAF policy requires it |
| Observability | 14-day logs | central logs, traces, alarms, security findings and incident retention |
| Email | external SMTP secret in SSM | approved SES/domain, DKIM/SPF/DMARC and delivery monitoring |
| AI | capped external provider/mock | approved Bedrock/provider gateway, evaluation and usage attribution |

The main availability gap is the combined Keycloak/NAT instance: its loss stops
identity and private Lambda internet egress. Separate those responsibilities
first. Add VPC endpoints for AWS services, then redundant outbound internet only
where external model/API calls require it.

Keep the governed metric layer, row-level entitlement model, closed assistant
tool list, PostgreSQL/DuckDB reconciliation gates and console API contract. Those
are application controls and do not need to change with the hosting tier.
