# Codex stdio MCP proxy environment

Codex can filter environment variables when starting a stdio MCP server. A child `codex app-server` may initialize normally but time out on `account/rateLimits/read` if the network requires proxy variables that were not forwarded.

In a controlled comparison with the same MCP process environment and account, the rate-limit request timed out without the proxy and succeeded when the host's `http_proxy` and `https_proxy` variables were added. Configure `mcp_servers.<name>.env_vars` to forward the required variable names, then start a new session. If the host process does not have the proxy values, configure them explicitly in the server's `env` table. Avoid recording credentials or raw account responses. Network access and authentication must also be available in the server environment.
