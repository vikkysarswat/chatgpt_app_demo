"""
Minimal MCP widget server (Python) that renders a carousel inside ChatGPT
using the same mechanism as the Pizzaz Dev Day demo.

- FastMCP
- HTML widget (Skybridge)
- structuredContent hydration
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any
from copy import deepcopy

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict, ValidationError


# ----------------------------
# CONFIG
# ----------------------------

ASSETS_DIR = Path(__file__).parent / "assets"
MIME_TYPE = "text/html+skybridge"


# ----------------------------
# WIDGET MODEL
# ----------------------------

@dataclass(frozen=True)
class Widget:
    identifier: str
    title: str
    template_uri: str
    html: str
    invoking: str
    invoked: str
    response_text: str


def load_html(name: str) -> str:
    path = ASSETS_DIR / f"{name}.html"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing widget HTML: {path}\n"
            "Create assets/stock-carousel.html"
        )
    return path.read_text(encoding="utf-8")


# ----------------------------
# WIDGET REGISTRY
# ----------------------------

widgets: List[Widget] = [
    Widget(
        identifier="show-stock-carousel",
        title="Show Stock Carousel",
        template_uri="ui://widget/stock-carousel.html",
        html=load_html("stock-carousel"),
        invoking="Loading market carousel",
        invoked="Market carousel rendered",
        response_text="Rendered stock carousel",
    )
]

WIDGET_BY_ID: Dict[str, Widget] = {w.identifier: w for w in widgets}
WIDGET_BY_URI: Dict[str, Widget] = {w.template_uri: w for w in widgets}


# ----------------------------
# INPUT SCHEMA
# ----------------------------

class StockInput(BaseModel):
    query: str = Field(description="User query")

    model_config = ConfigDict(extra="forbid")


TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"}
    },
    "required": ["query"],
    "additionalProperties": False,
}


# ----------------------------
# MCP SERVER
# ----------------------------

mcp = FastMCP(
    name="stock-carousel-mcp",
    stateless_http=True,
)


def widget_meta(w: Widget) -> Dict[str, Any]:
    return {
        "openai/outputTemplate": w.template_uri,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": w.invoking,
        "openai/toolInvocation/invoked": w.invoked,
    }


# ----------------------------
# LIST TOOLS
# ----------------------------

@mcp._mcp_server.list_tools()
async def list_tools():
    return [
        types.Tool(
            name=w.identifier,
            title=w.title,
            description=w.title,
            inputSchema=deepcopy(TOOL_SCHEMA),
            _meta=widget_meta(w),
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        )
        for w in widgets
    ]


# ----------------------------
# LIST RESOURCES
# ----------------------------

@mcp._mcp_server.list_resources()
async def list_resources():
    return [
        types.Resource(
            name=w.title,
            title=w.title,
            uri=w.template_uri,
            mimeType=MIME_TYPE,
            description=f"{w.title} widget",
            _meta=widget_meta(w),
        )
        for w in widgets
    ]


# ----------------------------
# READ RESOURCE (HTML)
# ----------------------------

async def read_resource(req: types.ReadResourceRequest):
    widget = WIDGET_BY_URI.get(str(req.params.uri))
    if not widget:
        return types.ServerResult(
            types.ReadResourceResult(contents=[])
        )

    return types.ServerResult(
        types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=widget.template_uri,
                    mimeType=MIME_TYPE,
                    text=widget.html,
                    _meta=widget_meta(widget),
                )
            ]
        )
    )


# ----------------------------
# CALL TOOL
# ----------------------------

async def call_tool(req: types.CallToolRequest):
    widget = WIDGET_BY_ID.get(req.params.name)
    if not widget:
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text="Unknown tool")],
                isError=True,
            )
        )

    try:
        StockInput.model_validate(req.params.arguments or {})
    except ValidationError as e:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Invalid input: {e.errors()}",
                    )
                ],
                isError=True,
            )
        )

    # 👇 THIS DATA HYDRATES THE WIDGET
    structured_content = {
        "stocks": [
            {"symbol": "RELIANCE", "price": 2485, "change": "+1.2%"},
            {"symbol": "TCS", "price": 3912, "change": "-0.4%"},
            {"symbol": "HDFCBANK", "price": 1642, "change": "+0.7%"},
        ]
    }

    return types.ServerResult(
        types.CallToolResult(
            content=[
                types.TextContent(type="text", text=widget.response_text)
            ],
            structuredContent=structured_content,
            _meta={
                "openai/toolInvocation/invoking": widget.invoking,
                "openai/toolInvocation/invoked": widget.invoked,
            },
        )
    )


# ----------------------------
# WIRE HANDLERS
# ----------------------------

mcp._mcp_server.request_handlers[types.ReadResourceRequest] = read_resource
mcp._mcp_server.request_handlers[types.CallToolRequest] = call_tool


# ----------------------------
# HTTP APP
# ----------------------------

app = mcp.streamable_http_app()


# ----------------------------
# RUN
# ----------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0")
