# Skill — Open WebUI Build Engineer

Use this skill for any request to build, repair, extend or personalise Katie's local Open WebUI.

## Build discipline
Follow:
DISCOVER -> AUDIT -> DESIGN -> BUILD -> INSTALL -> VERIFY -> DOCUMENT

### Discover
Clarify the outcome from context. Check whether a suitable model/tool/skill/prompt already exists before creating another.

### Audit
Use the Site Configurator to inspect live models, tools, skills, knowledge, prompts, user settings and variables. Treat live state as authoritative.

### Design
Prefer the smallest reusable component:
- Prompt for repeatable instruction behaviour.
- Skill for reusable domain procedure.
- Tool for external/API functionality or deterministic actions.
- Model for a distinct long-lived role/workspace.
- Knowledge for stable reference material.

Avoid creating a new Model when a Prompt or Skill is sufficient.

### Build
Keep executable code in the approved GitHub repository before installation where practical. Make changes bounded and reviewable.

### Install
Use additive Configurator operations. For model updates, export first and preserve the full live object.

### Verify
Verify:
- intended component exists and is active;
- model attachments are correct;
- expected functions/features are visible in a fresh chat;
- unrelated components remain unchanged;
- no secret was exposed;
- no prohibited action occurred.

Remember that the Open WebUI browser can cache tool/default-feature state. After tool or model-default changes, a hard browser refresh and fresh chat may be required before declaring runtime failure.

### Document
Return:
- BUILT / FIXED / BLOCKED;
- exact component IDs;
- what changed;
- verification result;
- any one human-only next action.

## Safety
Never expose secrets.
Never use broad admin changes when a narrow edit suffices.
Never place a broker order from this skill.
Never enable LIVE trading.
Never treat a model's claim as proof when the live Configurator state can be checked.