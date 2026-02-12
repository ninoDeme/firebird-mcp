from mcp.server.fastmcp import FastMCP
from mcp import types
from firebird.driver import connect, driver_config, Connection
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import argparse

load_dotenv()

class ColInfo(BaseModel):
    """Table Column Info"""
    name: str
    data_type: str
    length: str
    precision: str
    constraint_type: str
    constraint_name: str
    nullable: bool


# Initialize FastMCP server
mcp = FastMCP("firebird-mcp")

con: Connection | None = None

@mcp.tool()
def get_tables() -> list[str]:
    """Get tables from database"""
    with con.cursor() as cur:
        cur.execute("""
            SELECT rdb$relation_name table_name
             FROM rdb$relations
            WHERE rdb$view_blr IS NULL
              AND (rdb$system_flag IS NULL OR rdb$system_flag = 0)
            ORDER BY 1
        """)
        return [i[0].strip() for i in cur.fetchall()]

@mcp.resource("firebird://table/{tableName}", mime_type="application/json")
@mcp.tool()
def get_table_columns(tableName: str) -> list[ColInfo]:
    """Get table columns"""
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
                        MIN(rc.RDB$CONSTRAINT_TYPE) AS CONSTRAINT_TYPE,
                        MIN(i.RDB$INDEX_NAME) AS INDEX_NAME,
                        CASE WHEN r.RDB$NULL_FLAG = 1 THEN 1 ELSE 0 END AS NOT_NULL,
                        cast(r.RDB$DEFAULT_SOURCE as varchar(100) character set utf8) AS DFLT_VALUE,
                        r.RDB$FIELD_POSITION AS FIELD_POSITION 
                   FROM RDB$RELATION_FIELDS r
              LEFT JOIN RDB$FIELDS f ON r.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME
              LEFT JOIN RDB$INDEX_SEGMENTS s ON s.RDB$FIELD_NAME=r.RDB$FIELD_NAME
              LEFT JOIN RDB$INDICES i ON i.RDB$INDEX_NAME = s.RDB$INDEX_NAME 
                    AND i.RDB$RELATION_NAME=r.RDB$RELATION_NAME
              LEFT JOIN RDB$RELATION_CONSTRAINTS rc ON rc.RDB$INDEX_NAME = s.RDB$INDEX_NAME
                    AND rc.RDB$INDEX_NAME = i.RDB$INDEX_NAME
                    AND rc.RDB$RELATION_NAME = i.RDB$RELATION_NAME
              LEFT JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME
                  WHERE (r.rdb$system_flag is null or r.rdb$system_flag = 0) AND r.RDB$RELATION_NAME = ?
               GROUP BY FIELD_NAME, FIELD_TYPE, FIELD_LENGTH, FIELD_PRECISION, FIELD_SCALE, NOT_NULL, DFLT_VALUE, FIELD_POSITION 
               ORDER BY FIELD_POSITION
        """, [tableName])
        res = []
        for row in cur:
            res.append(ColInfo(
                name=str(row[0] or "").strip(),
                data_type=str(row[1] or "").strip(),
                length=str(row[2]),
                precision=str(row[3]),
                constraint_type=str(row[5]),
                constraint_name=str(row[6] or "").strip(),
                nullable= row[7] == 1,
            ))
        return res

if __name__ == "__main__":
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
        print("Error: Firebird database path must be provided via --fb-database or FIREBIRD_BASE environment variable.")
        exit(1)

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
    con = connect("db")

    for table in get_tables():
        @mcp.resource(uri=f"firebird://table/{table}", name=table, mime_type="application/json")
        def get_table_columns_t() -> list[ColInfo]:
            """Get table columns info"""
            return get_table_columns(table)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
