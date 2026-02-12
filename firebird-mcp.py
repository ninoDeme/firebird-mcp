import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from firebird.driver import Connection, connect, driver_config
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Configure logging to stderr so it doesn't interfere with stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("firebird-mcp")

load_dotenv()

class ColInfo(BaseModel):
    """Information about a table column."""
    name: str = Field(description="Column name")
    data_type: str = Field(description="Data type")
    length: int = Field(description="Field length")
    precision: Optional[int] = Field(None, description="Numeric precision")
    scale: Optional[int] = Field(None, description="Numeric scale")
    constraint_type: Optional[str] = Field(None, description="Constraint type (e.g., PRIMARY KEY)")
    constraint_name: Optional[str] = Field(None, description="Constraint name")
    nullable: bool = Field(description="Whether the column can be null")
    default_value: Optional[str] = Field(None, description="Default value source")

# Initialize FastMCP server
mcp = FastMCP(
    "firebird-mcp",
    instructions="""
    MCP server for interacting with Firebird databases
    """,
)

# Global connection object
_con: Optional[Connection] = None

def get_connection() -> Connection:
    """Get the active database connection."""
    global _con
    if _con is None:
        raise RuntimeError("Database connection not initialized. Please ensure the server is started correctly.")
    return _con

@mcp.tool()
def list_tables() -> List[str]:
    """List all user-defined tables in the Firebird database."""
    con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute("""
                SELECT TRIM(rdb$relation_name)
                FROM rdb$relations
                WHERE rdb$view_blr IS NULL
                  AND (rdb$system_flag IS NULL OR rdb$system_flag = 0)
                ORDER BY 1
            """)
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        raise

@mcp.tool()
def describe_table(table_name: str) -> List[ColInfo]:
    """Get detailed column information for a specific table."""
    con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute("""
                SELECT TRIM(r.RDB$FIELD_NAME) AS FIELD_NAME,
                         CASE f.RDB$FIELD_TYPE
                           WHEN 261 THEN 'BLOB'
                           WHEN 14  THEN 'CHAR'
                           WHEN 40  THEN 'CSTRING'
                           WHEN 11  THEN 'D_FLOAT'
                           WHEN 27  THEN 'DOUBLE'
                           WHEN 10  THEN 'FLOAT'
                           WHEN 16  THEN 'INT64'
                           WHEN 8   THEN 'INTEGER'
                           WHEN 9   THEN 'QUAD'
                           WHEN 7   THEN 'SMALLINT'
                           WHEN 12  THEN 'DATE'
                           WHEN 13  THEN 'TIME'
                           WHEN 35  THEN 'TIMESTAMP'
                           WHEN 37  THEN 'VARCHAR'
                           ELSE 'UNKNOWN'
                         END AS FIELD_TYPE,
                            f.RDB$FIELD_LENGTH AS FIELD_LENGTH,
                            f.RDB$FIELD_PRECISION AS FIELD_PRECISION,
                            f.RDB$FIELD_SCALE AS FIELD_SCALE,
                            TRIM(MIN(rc.RDB$CONSTRAINT_TYPE)) AS CONSTRAINT_TYPE,
                            TRIM(MIN(i.RDB$INDEX_NAME)) AS INDEX_NAME,
                            CASE WHEN r.RDB$NULL_FLAG = 1 THEN 0 ELSE 1 END AS NULLABLE,
                            CAST(r.RDB$DEFAULT_SOURCE AS VARCHAR(100) CHARACTER SET UTF8) AS DFLT_VALUE
                       FROM RDB$RELATION_FIELDS r
                  LEFT JOIN RDB$FIELDS f ON r.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME
                  LEFT JOIN RDB$INDEX_SEGMENTS s ON s.RDB$FIELD_NAME=r.RDB$FIELD_NAME
                  LEFT JOIN RDB$INDICES i ON i.RDB$INDEX_NAME = s.RDB$INDEX_NAME 
                        AND i.RDB$RELATION_NAME=r.RDB$RELATION_NAME
                  LEFT JOIN RDB$RELATION_CONSTRAINTS rc ON rc.RDB$INDEX_NAME = s.RDB$INDEX_NAME
                        AND rc.RDB$INDEX_NAME = i.RDB$INDEX_NAME
                        AND rc.RDB$RELATION_NAME = i.RDB$RELATION_NAME
                      WHERE (r.rdb$system_flag is null or r.rdb$system_flag = 0) 
                        AND r.RDB$RELATION_NAME = ?
                   GROUP BY FIELD_NAME, FIELD_TYPE, FIELD_LENGTH, FIELD_PRECISION, FIELD_SCALE, NULLABLE, DFLT_VALUE, r.RDB$FIELD_POSITION 
                   ORDER BY r.RDB$FIELD_POSITION
            """, [table_name.upper()])
            
            res = []
            for row in cur:
                res.append(ColInfo(
                    name=str(row[0] or "").strip(),
                    data_type=str(row[1] or "").strip(),
                    length=int(row[2] or 0),
                    precision=row[3],
                    scale=row[4],
                    constraint_type=str(row[5] or "").strip() if row[5] else None,
                    constraint_name=str(row[6] or "").strip() if row[6] else None,
                    nullable=bool(row[7]),
                    default_value=str(row[8] or "").strip() if row[8] else None,
                ))
            return res
    except Exception as e:
        logger.error(f"Error describing table {table_name}: {e}")
        raise

@mcp.tool()
def execute_query(sql: str) -> List[Dict[str, Any]]:
    """Execute a SQL query and return the results as a list of dictionaries."""
    con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute(sql)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
            else:
                con.commit()
                return [{"status": "Success", "rows_affected": cur.rowcount}]
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return [{"error": str(e)}]

@mcp.resource("table://{table_name}")
def get_table_schema(table_name: str) -> List[ColInfo]:
    """Get the schema for a specific table."""
    return describe_table(table_name)

def main():
    global _con
    parser = argparse.ArgumentParser(description="Firebird MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport type (stdio or http, default: stdio). Can be set via MCP_TRANSPORT env var.",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host to bind to (for http transport, default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8131,
        help="Port to listen on (for http transport, default: 8131)",
    )
    parser.add_argument(
        "--fb-host",
        default=os.getenv("FIREBIRD_HOST", "localhost"),
        help="Firebird server host (default: localhost). Can be set via FIREBIRD_HOST env var.",
    )
    parser.add_argument(
        "--fb-user",
        default=os.getenv("FIREBIRD_USER", "sysdba"),
        help="Firebird user (default: sysdba). Can be set via FIREBIRD_USER env var.",
    )
    parser.add_argument(
        "--fb-password",
        default=os.getenv("FIREBIRD_PASSWD", "masterkey"),
        help="Firebird password. Can be set via FIREBIRD_PASSWD env var.",
    )
    parser.add_argument(
        "--fb-port",
        default=os.getenv("FIREBIRD_PORT", "3050"),
        help="Firebird port (default: 3050). Can be set via FIREBIRD_PORT env var.",
    )
    parser.add_argument(
        "--fb-database",
        default=os.getenv("FIREBIRD_BASE"),
        help="Firebird database path. Can be set via FIREBIRD_BASE env var.",
    )

    args = parser.parse_args()

    if not args.fb_database:
        logger.error("Firebird database path must be provided via --fb-database or FIREBIRD_BASE environment variable.")
        sys.exit(1)

    # Register Firebird server
    srv_cfg = f"""[local]
    host = {args.fb_host}
    user = {args.fb_user}
    password = {args.fb_password}
    port = {args.fb_port}
    """
    driver_config.register_server('local', srv_cfg)

    # Register database
    db_cfg = f"""[db]
    server = local
    database = {args.fb_database}
    """
    driver_config.register_database('db', db_cfg)

    try:
        _con = connect("db")
        logger.info(f"Connected to database: {args.fb_database}")
    except Exception as e:
        logger.error(f"Failed to connect to Firebird: {e}")
        sys.exit(1)

    try:
        tables = list_tables()
        for table in tables:
            def make_handler(t):
                return lambda: describe_table(t)
            mcp.resource(uri=f"table://{table}", name=f"Table: {table}")(make_handler(table))

    except Exception as e:
        logger.warning(f"Could not register dynamic resources: {e}")

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
