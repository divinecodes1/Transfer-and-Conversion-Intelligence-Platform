# AWS architecture — Free Plan

```text
Browser
  ├─ HTTPS CloudFront → private S3 console
  ├─ HTTPS Lambda Function URL → API Lambda ─┐
  ├─ HTTPS Lambda Function URL → Assistant  │
  └─ HTTPS CloudFront → Keycloak EC2        │
                                      VPC    │
                    public subnet           │
                      Keycloak + NAT ───────┤
                    private subnets         │
                      API + refresh Lambda ─┤
                      private RDS PostgreSQL┘
```

ECR is a separate Terraform bootstrap state because repositories and images must
exist before Lambda creation. The application state consumes the repositories
as data sources.

Keycloak uses CloudFront's default HTTPS hostname and certificate, avoiding a
domain, Route53 zone, ACM setup and an Application Load Balancer. Its port 8080
security-group rule accepts only CloudFront's AWS-managed origin prefix list.

RDS is private. API and refresh Lambda functions use private subnets and obtain
internet egress through the Keycloak EC2 NAT instance. This removes the NAT
Gateway standing charge but creates an intentional single-instance dependency.
An enterprise migration should use redundant NAT or endpoints and redundant
identity instances.

The assistant is deployed as a third Lambda Function URL using the same tested
container image with a different command. It is outside the VPC and receives no
database credentials. Every data request and audit write goes through the
authenticated governed API.

Deployment updates Keycloak with a constrained custom SSM document. Warehouse
loading uses a second fixed document inside the VPC, so neither PostgreSQL nor
SSH is exposed to the operator's machine.
