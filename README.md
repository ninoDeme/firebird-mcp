# Firebird MCP Server

An MCP server for interacting with Firebird databases.

## Features

- **List Tables**: List all user-defined tables in the database.
- **Describe Table**: Get detailed schema information for a specific table.
- **Execute Query**: Run arbitrary SQL queries (SELECT/INSERT/UPDATE/DELETE).
- **Resources**: Each table is exposed as a resource for easy discovery.

## Installation

### Prerequisites

- Python 3.11 or higher
- `uv` (recommended) or `pip`
- Firebird database server access

### Install Dependencies

```bash
uv sync
```

## Usage

### Environment Variables

You can configure the server using a `.env` file or environment variables:

- `FIREBIRD_BASE`: Path to the Firebird database file (e.g., `C:\db\MYDB.FDB` or `/var/lib/firebird/data/mydb.fdb`).
- `FIREBIRD_HOST`: Firebird server host (default: `localhost`).
- `FIREBIRD_PORT`: Firebird server port (default: `3050`).
- `FIREBIRD_USER`: Firebird username (default: `sysdba`).
- `FIREBIRD_PASSWD`: Firebird password (default: `masterkey`).
- `MCP_TRANSPORT`: Transport type, `stdio` or `http` (default: `stdio`).

### Running the Server

Using `uv`:

```bash
uv run firebird-mcp.py --fb-database /path/to/your/db.fdb
```

Using standard Python:

```bash
python firebird-mcp.py --fb-database /path/to/your/db.fdb
```

### CLI Arguments

- `--fb-database`: (Required) Path to the Firebird database.
- `--fb-host`: Firebird host.
- `--fb-user`: Firebird user.
- `--fb-password`: Firebird password.
- `--fb-port`: Firebird port.
- `--transport`: `stdio` or `http`.
- `--host`: Host to bind to for HTTP transport.
- `--port`: Port to listen on for HTTP transport.

## Build

To create a standalone executable:

```bash
./build.sh
```

This uses `PyInstaller` to create a single-file executable in the `dist` directory.

## Tools

### `list_tables`
Returns a list of all user-defined tables in the database.

### `describe_table(table_name)`
Returns detailed information about columns in the specified table, including data types, lengths, nullability, and constraints.

### `execute_query(sql)`
Executes the provided SQL query and returns the results. For `SELECT` queries, it returns a list of dictionaries. For other queries, it returns the success status and rows affected.

## Resources

### `firebird://table/{table_name}`
Exposes the schema of a specific table as a JSON resource.
