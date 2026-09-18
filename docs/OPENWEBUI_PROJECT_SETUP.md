# Open WebUI Project Setup — Initial Workhorse Structure

Create only these four project folders initially:
1. Trading Operations
2. You Heal Content Production
3. Books & Publishing
4. Apps / Plugins / Bots

Do not mirror the entire OpenAI project estate.

## Open WebUI structure
Folders/Projects can carry a project-specific system prompt and knowledge base.
Workspace Models can wrap a base model with instructions, tools and knowledge.

## Recommended base model
Use the proven DeepSeek Fast/OpenRouter route as the normal interactive base.
Use the proven DeepSeek Batch Pipe for high-volume asynchronous work.

## Trading Operations
System prompt:
openwebui/project/TRADING_OPERATIONS_SYSTEM_PROMPT.md

Attach/bind:
- T212 DEMO gateway Function/tool when available in the workspace model;
- agent briefs under openwebui/agents/;
- only trading-specific, non-sensitive knowledge.

## You Heal
System prompt:
openwebui/project/YOU_HEAL_CONTENT_SYSTEM_PROMPT.md

## Books
System prompt:
openwebui/project/BOOKS_PUBLISHING_SYSTEM_PROMPT.md

## Apps / Plugins / Bots
System prompt:
openwebui/project/APPS_PLUGINS_BOTS_SYSTEM_PROMPT.md

## Data boundary
OpenAI remains the master/sensitive layer.
Only bounded task briefs and approved files move into DeepSeek/Open WebUI.
