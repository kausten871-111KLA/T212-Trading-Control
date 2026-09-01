# Integration & Capability Register

Owner: Executive Orchestration Layer
Status: ACTIVE
Purpose: Maintain a governed register of external/open-source capabilities evaluated for use across project workstreams.

## Operating rule
A candidate is not integrated merely because it is useful or popular. Before integration it must pass security, provenance, maintenance, licensing, dependency, permissions, secrets-handling, privacy and least-privilege checks. Prefer official/first-party implementations. Test in isolated/read-only/demo environments before consequential write access.

## Risk classes
1. OFFICIAL / FIRST-PARTY — preferred.
2. ESTABLISHED OPEN SOURCE — permitted only after review.
3. EXPERIMENTAL — isolated evaluation only; no production credentials or consequential write access.

## Mandatory gates
- Traceable/reputable maintainer and repository provenance
- Active maintenance and sensible release/commit history
- Appropriate licence
- Review dependencies, install scripts, workflows and network behaviour
- No embedded secrets, credential harvesting or unsafe token handling
- Least privilege and scoped credentials
- Sandbox/demo/read-only validation first
- No automatic expansion to financial, healthcare, email, production or other consequential write permissions
- Record capability, intended workstreams, risk class, review evidence, permissions and rollback method

## Current discovery baseline
- modelcontextprotocol/servers — official MCP server examples/reference ecosystem; candidate discovery baseline, not blanket-approved.
- modelcontextprotocol/registry — official MCP registry infrastructure; candidate discovery/verification baseline.
- modelcontextprotocol/inspector — official MCP inspection/testing tooling; suitable for pre-integration inspection/testing subject to environment review.
- modelcontextprotocol/python-sdk — official Python MCP SDK; development candidate.
- modelcontextprotocol/typescript-sdk — official TypeScript MCP SDK; development candidate.

## Capability domains to scout
- Agent orchestration and delegation
- MCP/connectors and interoperable tools
- Research/evidence collection
- Documents/reports and knowledge retrieval
- Media/video/content production
- Workflow/project automation
- Finance/data analysis
- Security/QA/testing
- Persistent knowledge/retrieval

## Agent capability broadcast
All project agents should treat only entries explicitly marked INTEGRATED as available shared capabilities. DISCOVERED, REVIEWING and TESTING entries are not production capabilities. Agents should route capability gaps to the executive orchestration layer for assessment rather than installing unreviewed software.

## Register
| Item | Function | Source class | Status | Access boundary | Notes |
|---|---|---|---|---|---|
| MCP Servers repository | Reference implementations and server discovery | Official | DISCOVERED | None | Individual servers require separate review |
| MCP Registry | Registry/discovery infrastructure | Official | DISCOVERED | None | Use as a provenance/discovery input, not an automatic trust signal |
| MCP Inspector | Inspect/test MCP integrations | Official | REVIEW CANDIDATE | Local/test only initially | Intended as part of safety validation |
| MCP Python SDK | Build/test MCP integrations in Python | Official | REVIEW CANDIDATE | Development only initially | No production credentials during evaluation |
| MCP TypeScript SDK | Build/test MCP integrations in TypeScript | Official | REVIEW CANDIDATE | Development only initially | No production credentials during evaluation |

## Reporting format
For every item promoted to INTEGRATED, report to the user: item name, core functions, workstreams/agents that can use it, permissions granted, safety controls, integration/test result, and any limitations or user action required.
