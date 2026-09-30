# WebUI Operating System Roadmap — 30 Sep 2026

## North star

Build Open WebUI into Katie's persistent executive operating system: a specialist, multi-model, multimodal, automation-first environment that can run substantial work across trading, apps/plugins/bots, You Heal content, books/publishing, science/R&D, websites, business operations, and Newport News continuity.

The goal is not to beat every general-purpose frontier model at every task. The goal is to make the system materially better for Katie's own work by combining:
- specialised models;
- durable project memory/state;
- tools and connectors;
- deterministic workers;
- multimodal routing;
- automation;
- QA/evaluation;
- cost-aware model routing;
- human approval at the right points.

## 1. Control plane

Create one Executive Orchestra control layer with:
- project registry;
- agent registry;
- work queue;
- status/health dashboard;
- approval queue;
- shared event log;
- morning/evening handoff;
- per-project ownership and escalation;
- retry / failure / pause-and-inform behaviour.

Every agent reports into this layer rather than operating as an isolated chat.

## 2. Project workspaces

Create durable workspaces for:
1. Trading Operations / T212
2. Apps / Plugins / Bots / WebUI Engineering
3. You Heal Content Production
4. Books & Publishing
5. NSTR / RT Science & Research
6. GSC360 / Newport News
7. You Heal Website / Digital Products
8. Executive / Business Continuity

Each workspace needs:
- canonical brief;
- files/knowledge;
- agents;
- prompts;
- automations;
- decisions log;
- task register;
- latest handoff;
- archive/versioning.

## 3. Model router

Do not force DeepSeek to do every job.

Use task-based routing:
- DeepSeek: reasoning, drafting, planning, code review, structured analysis.
- Vision-capable model: screenshots, diagrams, scanned pages, UI, photos, charts.
- Fast/cheap model: classification, tagging, extraction, summaries, repetitive transforms.
- Higher-capability model: difficult science, legal/business reasoning, architecture, final QA.
- Local/small model where sensible: lightweight background classification.

Routing rules should be explicit, logged, testable and cost-aware.

## 4. Multimodal layer

Images must become first-class inputs.

Add:
- image upload detection;
- automatic routing to a vision model when the base model lacks vision;
- screenshot/UI analysis;
- OCR only as fallback;
- chart/table extraction;
- image metadata and captions saved back into project context;
- document page-image inspection for PDFs/scans.

Never rely on a fake 'vision=true' flag when the underlying model cannot see images.

## 5. GitHub integration

GitHub becomes the system's durable engineering backbone.

Required capabilities:
- repo discovery and project mapping;
- branch-per-change;
- tests before merge;
- pull-request workflow;
- release notes;
- prompt/tool/agent source control;
- plugin code;
- deployment manifests;
- rollback bundles;
- issue/task creation from failed runs;
- CI for syntax, unit tests and smoke tests.

WebUI tools should be installable from approved repositories, not hand-copied ad hoc.

## 6. Plugins / connectors / tools

Create a plugin catalogue with:
- purpose;
- permissions;
- secrets required;
- owning workspace;
- health status;
- rate limits;
- cost;
- fallback;
- approval level.

Priority connectors:
- GitHub;
- Gmail;
- Google Calendar;
- file/library storage;
- web/search;
- image/vision;
- website/CMS;
- trading market-data/broker DEMO;
- optional Canva/Descript/video tools;
- business systems as they become needed.

## 7. Automation engine

Move repetitive work out of LLM chats.

Use deterministic workers for:
- scheduled scans;
- file watching;
- cache refresh;
- data ingestion;
- backups;
- status checks;
- reports;
- publishing queues;
- content scheduling;
- website checks;
- task extraction;
- reminders;
- project handoffs.

LLMs should be invoked only when judgement, synthesis or generation is needed.

## 8. Trading stack

Trading 212 remains DEMO-only; LIVE disabled.

Architecture:
market discovery -> deterministic filters -> catalyst verification -> T212 tradability -> decision -> DEMO execution -> broker verification -> monitoring -> exit -> audit -> missed-opportunity learning.

Must-have:
- session-aware market-data freshness;
- T212 instrument cache;
- 20-day volume baseline;
- spread/liquidity gates;
- structural junk filtering;
- persistent movement tiers;
- catalyst queue;
- broker reconciliation;
- retry controls;
- worker timers;
- EOD missed-green audit;
- single canonical workspace/status.

## 9. Books & publishing pipeline

Build a book factory:
idea/draft -> chapter map -> source/research queue -> rewrite -> continuity check -> factual QA -> edit -> style pass -> references -> layout/export -> publishing assets.

Maintain:
- chapter state;
- unresolved research questions;
- source ledger;
- version history;
- continuity/duplication checks;
- audience/tone guide;
- publication checklist.

## 10. Science / NSTR / RT pipeline

Create a research-to-delivery system:
concept -> hypothesis -> evidence map -> literature review -> protocol -> measurement -> risk/ethics -> practitioner material -> white paper -> training -> software/AI specification -> publication/update cycle.

Separate:
- public claims;
- practitioner hypotheses;
- experimental observations;
- validated evidence;
- contraindications/uncertainty.

Add citation tracking and claim-evidence mapping.

## 11. You Heal content factory

Pipeline:
topic bank -> script -> clinical/scientific check -> brand/tone check -> recording -> transcript -> clips -> captions -> thumbnails -> schedule -> publish -> performance review -> reuse.

Agents:
- Content Director
- Senior Film Director
- Script Editor
- Science/Claims Reviewer
- Distribution/Scheduling Agent
- Analytics/Learning Agent

## 12. Website operations

Create a website operations agent for:
- page briefs;
- copy updates;
- SEO metadata;
- broken-link checks;
- analytics summaries;
- conversion experiments;
- landing pages;
- product/booking updates;
- release checklist.

Use GitHub/CMS integration where possible. Human approval before publishing major changes.

## 13. Newport News / business continuity

Build an executive continuity workspace with:
- canonical programme brief;
- workstreams;
- meetings;
- decisions;
- risks;
- investor outputs;
- university/partner tracking;
- financial/phase models;
- document generation;
- delegation register;
- morning/evening status.

The system should be able to maintain operations while Katie is travelling, with explicit owner/escalation rules.

## 14. Persistent memory and state

Do not rely on chat history.

Store structured state for:
- projects;
- decisions;
- tasks;
- agent outputs;
- approvals;
- current version;
- blockers;
- deadlines;
- source references;
- automation runs.

Use project-specific retrieval rather than one giant undifferentiated memory pool.

## 15. Observability

Every automated workflow needs:
- run ID;
- start/end;
- input source;
- model/tool used;
- token/credit cost;
- status;
- error;
- retries;
- output location;
- approvals;
- next action.

Create one health dashboard for:
- WebUI;
- model providers;
- plugins;
- workers;
- automations;
- queues;
- storage;
- backups;
- token spend.

## 16. Quality / evaluation

Create eval suites for each major capability.

Examples:
- T212: discovery recall, false positives, missed-greens, execution verification.
- Books: continuity, factuality, duplication, style.
- Science: claim/source match, evidence quality, uncertainty.
- Content: tone, scientific safety, publish readiness.
- Website: factual correctness, links, CTA/SEO checks.

No major agent should be trusted because it 'sounds good'; it should have measurable tests.

## 17. Cost / 2–4B monthly credit strategy

At very high monthly volume, cost control is architecture, not prompt wording.

Use:
- deterministic preprocessing;
- caching;
- deduplication;
- batching;
- small models for routine work;
- expensive models only on escalated tasks;
- project context trimming;
- retrieval instead of replaying giant prompts;
- reusable structured summaries;
- hard per-agent/per-workflow budgets;
- daily and monthly spend dashboards;
- anomaly alerts.

A 2–4B-credit/month system should have explicit cost per workflow and cost per useful output.

## 18. Security / resilience

Required:
- server-side secrets;
- no secrets in prompts/repos;
- least-privilege tools;
- separate DEMO/LIVE trading credentials;
- regular SQLite/config backups;
- automated restart;
- health checks;
- audit log;
- rollback;
- Cloudflare Access;
- disaster-recovery runbook;
- exportable canonical state.

## 19. Dashboard

WebUI home should become an operational dashboard, not just a chat list.

Panels:
- Executive status
- Today's tasks
- Waiting approvals
- Failed/blocked automations
- Trading status
- Content pipeline
- Books progress
- Science/R&D progress
- Website releases
- Newport News workstreams
- System health
- Credits/cost
- Recent outputs

## 20. Delivery order

### Phase 1 — Stabilise / control
- backups / rollback
- persistent worker framework
- workspace structure
- Executive Orchestra control plane
- system health/status
- model routing rules
- GitHub source control

### Phase 2 — Multimodal / integrations
- vision routing
- file/document ingestion
- GitHub install/update flow
- plugin catalogue
- email/calendar/files
- CMS/content connectors

### Phase 3 — Workstream factories
- trading
- books
- science
- content
- website
- executive continuity

### Phase 4 — Scale
- autonomous queues
- evals
- cost router
- dashboards
- 24/7 worker pool
- failure recovery
- high-volume throughput tuning

## Immediate build queue

1. Finish T212 Gateway v0.3 controlled installation.
2. Finish 5-minute persistent discovery worker.
3. Add 20-day relative-volume join and cached T212 tradability.
4. Build Executive Orchestra project/status schema.
5. Build workspace registry for the 8 major workspaces.
6. Add model-router specification, including mandatory vision routing.
7. Build plugin/connector registry.
8. Build automation-run ledger + health status.
9. Build a canonical morning/evening handoff format.
10. Add GitHub-backed prompt/tool/agent release workflow.
11. Build Books pipeline state schema.
12. Build Science/R&D evidence/claim ledger.
13. Build You Heal content pipeline state schema.
14. Build Website release workflow.
15. Build Newport News continuity/task/decision register.
16. Add system-wide credit/cost tracking.
17. Add eval framework and regression suites.
18. Build dashboard API/data contract.
19. Add backup/recovery runbook.
20. Create a 30-day implementation backlog with owners and dependencies.
