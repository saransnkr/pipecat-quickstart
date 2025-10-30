# Google Calendar MCP Server

This repository hosts an implementation of a Model Context Protocol (MCP) server that exposes a set of Google Calendar tools over the SSE transport. It listens on port **9079** by default and uses the OAuth client credentials stored in `google_secret.json`.

## Prerequisites

- Python 3.12+
- A Google Cloud OAuth credential file saved as `google_secret.json` in this directory (already provided).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Authorize Google Calendar access

The server requires a user token with the Calendar scope. Run the interactive helper once:

```bash
python -m calendar_mcp authorize
```

A browser window will open asking you to sign in and grant access. After completion a `google_token.json` file will be created next to the credentials file.

## Run the MCP server (port 9079)

```bash
python -m calendar_mcp serve --host 127.0.0.1 --port 9079
```

The process starts an SSE server that MCP-compatible clients can connect to at `http://127.0.0.1:9079/sse`. The following tools are available:

- `list_calendars`
- `list_events`
- `create_event`
- `update_event`
- `delete_event`

All tools return structured responses that include event identifiers, times, and related metadata. If a tool reports that authorization is required, re-run the `authorize` helper to refresh the token.

## Development notes

- Default OAuth scope: `https://www.googleapis.com/auth/calendar`
- Tokens are stored in `google_token.json`; delete this file to force re-authorization.
- The OAuth helper listens on `http://localhost:8080/`. Add this exact URI to the OAuth client’s **Authorized redirect URIs** in Google Cloud Console (or change the port via `MCP_GOOGLE_CAL_AUTH_PORT`).
- You can override the host and port via the `--host` / `--port` flags or the environment variables `MCP_GOOGLE_CAL_HOST` and `MCP_GOOGLE_CAL_PORT`.
