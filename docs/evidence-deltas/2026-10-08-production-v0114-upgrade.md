# Production WebUI v0.11.4 upgrade ? 8 October 2026

DEPLOYED AND VERIFIED at 23:19 Europe/London.

Katie explicitly authorized the production version upgrade at 23:06. The official standard image is pinned by digest in the existing Compose configuration. No persistent-chat draft overlays were installed.

A full cold-volume archive plus private configuration/inspection backups were retained on the server. The latest archive restored into an isolated volume, passed SQLite integrity, and reproduced all checked core table fingerprints; the restored application was not started.

Production verification: Docker healthy, authenticated account/tool/model/function/task endpoints returned JSON HTTP 200, authenticated saved history matched, all 110 existing chat records were preserved, tool/function/model/account/auth/prompt/knowledge/file/folder records were preserved, existing configuration values and Compose environment were preserved, and the database migration head stayed unchanged. All four application files match the official v0.11.4 source hashes. Cloudflared is active; Docker and Cloudflared are enabled at boot.

Three active schedules were present in the cold snapshot: US OPEN, US CLOSE, and US MIDDAY. Their configuration and run state were preserved. The earlier two-schedule report was historical; the upgrade did not create the additional schedule.

Recovery checks restarted v0.11.3 when initial verification assertions failed. The assertions were corrected after confirming seven upstream default configuration additions, a newer third schedule, and the correct model-list endpoint without a trailing slash. All 345 original configuration values were preserved.

PR #7 remains draft. Its persistent-chat fixes have not been deployed. This upgrade does not establish real-provider, tool-execution, broker, or trading acceptance; no validation orders or paid model completion calls were submitted.

The accompanying sanitized receipt records the final image and verification results. Private data, secrets, environment values, and backup contents are not committed.
