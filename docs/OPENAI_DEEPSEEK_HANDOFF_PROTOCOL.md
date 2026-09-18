# OpenAI -> DeepSeek Workhorse Handoff Protocol

Transfer only what the task needs.

Include:
- objective
- bounded inputs
- allowed sources/files
- required output
- operational constraints
- deadline/priority
- acceptance test

Exclude by default:
- GSC360 confidential material
- NSTR/RT proprietary IP
- legal/private records
- credentials/secrets
- unrelated project history

DeepSeek returns:
1. completed work product
2. assumptions
3. blockers/gaps
4. evidence/sources
5. next action
6. anything that should be escalated back to OpenAI
