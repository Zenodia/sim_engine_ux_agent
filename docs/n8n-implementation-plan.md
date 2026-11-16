# Plan: enterprise n8n workflow creator

Status: implementation in this repository, separate from the service-desk domain.
See [the completed validation record](n8n-validation.md) for delivered coverage and
the pending actual self-hosted engine check.

## Objective and boundaries

Build a real n8n workflow-authoring domain: users describe and revise incident
automation; the creator emits importable native workflow JSON; event fixtures
verify actual effects. Retain the first toy domain as a regression example.
Use self-hosted n8n and custom fixture APIs. No NemoClaw/OpenShell dependency.

The initial family is alert intake -> validate/minimize data -> ticket -> regional
notification -> optional acknowledgement-gated escalation. The LLM writes a typed
domain specification, not arbitrary executable JavaScript. Application-owned,
versioned code compiles that specification into n8n nodes.

## Implementation sequence

1. Typed authoring contracts, 100 synthetic creator users, two-session requirement
   changes, scoped memory conversion, rules references and optional Sonnet authoring.
2. Deterministic native n8n compiler using Webhook, Code, If and HTTP Request nodes.
   Code handles schema validation/minimization and compound incident rules; all
   network calls use HTTP Request nodes.
3. Durable isolated fixture services with ticket/message/escalation effects,
   idempotency, tenant isolation and bounded downstream fault injection.
4. Separate Python reference execution and real n8n REST/webhook execution adapters.
   The former is an offline semantic check, not proof that n8n executed a workflow.
5. Independent final-effect oracle, version/provenance artifacts, reports, and
   evidence-bound rollout stages corresponding to the original migration table.
6. Shadow comparisons in fresh namespaces; canary/replay evidence; rollback latch;
   an authoring gateway that can apply the selected creator to real incoming requests
   while saving drafts only.
7. Docker Compose for dedicated local n8n and fixtures, an explicit activation
   integration test, tests for migration boundaries, and updated documentation.

## Acceptance

- Generated drafts can be imported into a dedicated self-hosted n8n instance.
- The new creator preserves current requirements after a cross-session revision.
- Duplicate events and retry-after-commit faults do not duplicate business effects.
- Region, severity, acknowledgement, privacy and tenant boundaries are checked
  through resulting fixture state, independently from the generated plan.
- Promotion requires evidence from the preceding stage, bound to the same release,
  scope and workflow artifact. Fresh observational windows govern exposure increases.
- A failing candidate observation latches rollback; existing candidate sessions
  drain and new sessions use the baseline.
- Reference-only evidence is labeled and cannot authorize n8n-runtime progression.
- The supplied local stack changes no existing enterprise integration or workflow.

## Validation limits

Docker was not found during discovery. Native JSON/schema validation, reference
execution, Node.js compiler tests, and mocked REST boundary tests can be exercised
locally. Real n8n execution must be reported separately and requires starting the
provided dedicated stack and supplying its API key. The application will not claim
production validation from fixture or reference evidence.
