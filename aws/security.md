# Security posture — AWS Free Plan

- All browser entry points use HTTPS. CloudFront supplies its default certificate;
  no domain is required.
- The console and documents buckets block public access. Only the console
  CloudFront distribution can read console objects.
- RDS has `publicly_accessible = false`; PostgreSQL accepts only the Lambda and
  Keycloak security groups and forces TLS.
- Keycloak origin port 8080 accepts only the AWS-managed CloudFront origin-facing
  prefix list. SSH is closed; administration uses Session Manager.
- EC2 metadata requires IMDSv2. EBS and RDS storage are encrypted.
- API token validation checks signature, expiry, issuer and audience. Issuer is
  the public HTTPS CloudFront URL; JWKS is fetched privately from Keycloak.
- The assistant has no DSN and no VPC attachment. It uses the caller's bearer
  token to reach the governed API; the API replaces any claimed audit identity
  with the verified token identity.
- Generated passwords and SMTP/model secrets are SSM SecureStrings. EC2 reads
  only its deployment prefix. Secrets are not embedded in EC2 user data.
- GitHub deploys through repository-scoped OIDC. It can push the two ECR repos,
  roll three Lambda functions, publish the console and invoke only the fixed
  Keycloak SSM document.

The EC2 host doubles as a NAT instance to avoid a NAT Gateway charge. Its failure
interrupts Keycloak and private Lambda egress, so this is a cost-controlled demo
posture rather than high availability.
