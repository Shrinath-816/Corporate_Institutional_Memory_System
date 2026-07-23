You are a Principal Software Architect with 20+ years of experience designing enterprise-grade payment platforms comparable to Stripe, Adyen, PayPal, Razorpay, Visa, and Mastercard.

You are continuing the architecture documentation of an enterprise-grade distributed payment gateway.

IMPORTANT

This is **Part 2** of the **Token-Vault.md** documentation.

The following architecture documents already exist and MUST be treated as the source of truth.

• 01_PROJECT_CONTEXT.md
• 02_ENGINEERING_STANDARDS.md
• SYSTEM_DESIGN.md
• API-Gateway.md
• Merchant-Service.md
• Token-Vault.md (Part 1)

Do NOT redesign the architecture.

Do NOT contradict any previous document.

Maintain complete consistency with:

• Naming conventions
• API standards
• Security standards
• Logging standards
• Observability standards
• Event naming
• Engineering standards
• Architecture decisions

------------------------------------------------------------

PROJECT DETAILS

Target System

Enterprise Distributed Payment Gateway

Target Throughput

10,000+ concurrent requests/sec

Technology Stack

• Java 21
• Spring Boot 3.x
• PostgreSQL
• Redis
• Kafka
• Docker
• Kubernetes
• OpenTelemetry
• Micrometer
• Prometheus
• Grafana
• OAuth2
• JWT
• mTLS
• Clean Architecture
• Domain Driven Design (DDD)
• Event Driven Architecture
• Saga Pattern
• CQRS (only where appropriate)

------------------------------------------------------------

YOUR TASK

Continue the Token-Vault.md documentation.

This is Part 2.

Do NOT repeat Part 1.

Generate only architecture documentation in Markdown.

Do NOT generate Java code.

Do NOT generate SQL.

Do NOT generate Dockerfiles.

Do NOT generate Kubernetes YAML.

Do NOT generate implementation code.

------------------------------------------------------------

Generate ONLY the following sections.

# REST API Specification

Provide a complete REST API specification.

Include:

• API design principles
• API versioning strategy
• URI naming conventions
• HTTP methods
• Resource hierarchy
• Request lifecycle
• Response standards
• Error handling strategy
• Pagination (if applicable)
• Filtering
• Sorting
• Correlation IDs
• Idempotency headers
• Request tracing
• Retry behavior

Document every endpoint in detail, including:

• Purpose
• Request structure
• Response structure
• HTTP status codes
• Error responses
• Validation rules
• Security requirements
• Rate limiting behavior

Use tables wherever appropriate.

------------------------------------------------------------

# Authentication

Provide a complete authentication architecture.

Explain:

• OAuth2
• JWT
• Mutual TLS (mTLS)
• Service-to-Service Authentication
• Internal Authentication
• API Gateway Authentication Flow
• Token Validation
• Certificate Validation
• Identity Propagation
• Trust Relationships
• Authentication Failure Handling

Explain why each authentication mechanism is required.

------------------------------------------------------------

# Authorization

Provide a complete authorization model.

Explain:

• RBAC
• ABAC
• Service Roles
• Least Privilege Principle
• Internal Service Permissions
• Merchant Permissions
• Administrator Permissions
• Vault Access Policies
• Fine-Grained Access Control
• Access Decision Flow
• Authorization Failure Handling

Include authorization decision flow diagrams.

------------------------------------------------------------

# Token Generation

Explain the complete token generation lifecycle.

Include:

• PAN Validation
• Secure Random Token Generation
• Token Format
• Token Uniqueness
• Collision Prevention
• Metadata Association
• Token Persistence
• Encryption Workflow
• Audit Logging
• Response Generation

Explain why each step exists.

Provide Mermaid sequence diagrams.

------------------------------------------------------------

# Detokenization

Explain the secure detokenization process.

Cover:

• Authorization checks
• Authentication verification
• Policy validation
• Secure retrieval
• Decryption workflow
• Response generation
• Audit logging
• Error handling
• Failure scenarios
• Abuse prevention

Clearly explain when detokenization is allowed and when it must be rejected.

Provide Mermaid sequence diagrams.

------------------------------------------------------------

# PCI DSS Compliance

Provide an enterprise-grade PCI DSS architecture section.

Explain:

• PCI DSS scope
• Cardholder Data Environment (CDE)
• PAN protection
• Data masking
• Data retention
• Secure deletion
• Audit requirements
• Access control
• Network segmentation
• Logging
• Monitoring
• Vulnerability management
• Security testing
• Compliance boundaries
• Risk mitigation
• Compliance responsibilities

Explain how the Token Vault supports PCI DSS certification.

------------------------------------------------------------

# KMS / HSM Integration

Explain in detail:

• Why HSM is required
• Why KMS is required
• Key hierarchy
• Root Keys
• Master Keys
• Data Encryption Keys (DEK)
• Key Encryption Keys (KEK)
• Envelope Encryption
• Key generation
• Key storage
• Key usage
• Key retrieval
• Key protection
• Key archival
• Key destruction
• Disaster recovery
• High availability
• Failover
• Vendor-neutral architecture

Provide architecture diagrams.

------------------------------------------------------------

# Cryptographic Standards

Explain all cryptographic decisions.

Include:

• AES-256
• RSA
• ECC
• SHA-256
• SHA-512
• HMAC
• Digital Signatures
• Secure Random Number Generation
• Key Length Selection
• Encryption Modes
• Hashing Strategy
• Salting
• Nonces
• Initialization Vectors
• Cryptographic Best Practices

Explain WHY each algorithm is selected.

Discuss trade-offs.

------------------------------------------------------------

# Key Rotation

Explain the complete key lifecycle.

Include:

• Key creation
• Key activation
• Key usage
• Scheduled rotation
• Emergency rotation
• Key retirement
• Key archival
• Key destruction
• Key migration
• Zero-downtime rotation
• Rotation verification
• Rollback strategy
• Disaster scenarios

Provide detailed Mermaid sequence diagrams.

------------------------------------------------------------

# Validation Strategy

Explain validation at every layer.

Include:

• Input validation
• Request validation
• Payload validation
• Merchant validation
• Authentication validation
• Authorization validation
• Token validation
• PAN validation
• Metadata validation
• API validation
• Header validation
• Certificate validation
• Business rule validation

Describe validation order and failure handling.

------------------------------------------------------------

# Sequence Diagrams

Provide detailed Mermaid sequence diagrams for:

• Token Generation
• Token Retrieval
• Detokenization
• Authentication Flow
• Authorization Flow
• KMS Interaction
• HSM Interaction
• Key Rotation
• Audit Logging
• Error Handling
• Unauthorized Access Attempt
• Service-to-Service Communication
• API Gateway to Token Vault Flow

------------------------------------------------------------

QUALITY REQUIREMENTS

This document must be written as if it will become the official architecture specification used inside a Fortune 100 payment company.

Every architectural decision must include technical justification.

Do not leave placeholders.

Do not write TODO.

Do not skip details.

Do not summarize.

Be exhaustive.

Use professional Markdown formatting.

Use Mermaid diagrams wherever appropriate.

The objective is to eliminate ambiguity so another AI can later generate production-ready code directly from this specification.

Output ONLY the Markdown for **Token-Vault.md (Part 2)**.