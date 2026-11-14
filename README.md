# Codex usage MCP server

A dependency-free stdio MCP server exposing `get_codex_usage`, which returns the current account rate limits and usage windows reported by `codex app-server` as JSON. Each call starts and stops its own app server and uses the Codex CLI's existing authentication.

## Requirements

- Python 3.8 or later
- The Codex CLI installed and authenticated in the environment running the server

Add this to your MCP client's configuration, replacing the path with the absolute path to this repository:

```toml
[mcp_servers.codex_usage]
command = "python3"
args = ["/absolute/path/to/mcp-tools/codex-usage.py"]
# Forward proxy settings from the Codex host when your network needs them.
env_vars = ["http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]
```

The server finds `codex` on `PATH`. To specify an executable, set `CODEX_CLI` in the MCP server's environment, for example:

```toml
[mcp_servers.codex_usage.env]
CODEX_CLI = "/absolute/path/to/codex"
```

Restart the MCP client after changing its configuration. Ask it to call `get_codex_usage`; the result is the app server's rate-limit response. Errors, including missing authentication or an unavailable CLI, are returned as tool errors. The server writes MCP messages to stdout and Codex diagnostics to stderr.

## Troubleshooting

The Codex app server must be able to reach the service to read usage. Codex may filter environment variables when starting an MCP server, so if your network requires a proxy, use the `env_vars` setting above and start a new Codex session. These variables must also be present in the environment of the process hosting Codex; if they are not, configure the appropriate values in `[mcp_servers.codex_usage.env]` instead. Do not commit proxy credentials.

If a call reports a timeout during the account rate-limit request, check the proxy, network access, and whether the Codex host inherited the expected environment. If initialization fails, check the Codex executable, its configuration and authentication, filesystem permissions, and stderr. Restrictions in remote or sandboxed environments can also prevent access.

The response contains account-specific data. Treat it as private and avoid sharing the raw response unnecessarily.

## Tests

Run `python3 -m unittest discover -s tests` to exercise the MCP protocol and subprocess behavior with a fake Codex CLI.
