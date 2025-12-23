"""
Stock trading demo MCP server implemented with the Python FastMCP helper.

The server exposes widget-backed tools that render stock-related UI widgets.
Each handler returns an HTML shell via an MCP resource and echoes structured
stock data (symbol, price, and price change) so the ChatGPT client can hydrate
the widget. The module also wires the handlers into an HTTP/SSE stack so you can
run the server with uvicorn on port 8000.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import random
import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------------------
# Widget definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StockWidget:
    identifier: str
    title: str
    template_uri: str
    invoking: str
    invoked: str
    html: str
    response_text: str


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


@lru_cache(maxsize=None)
def _load_widget_html(component_name: str) -> str:
    html_path = ASSETS_DIR / f"{component_name}.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf8")

    fallback_candidates = sorted(ASSETS_DIR.glob(f"{component_name}-*.html"))
    if fallback_candidates:
        return fallback_candidates[-1].read_text(encoding="utf8")

    raise FileNotFoundError(
        f'Widget HTML for "{component_name}" not found in {ASSETS_DIR}. '
        "Run `pnpm run build` to generate the assets before starting the server."
    )


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

widgets: List[StockWidget] = [
    StockWidget(
        identifier="stock-quote",
        title="Show Stock Quote",
        template_uri="ui://widget/stock-quote.html",
        invoking="Fetching stock price",
        invoked="Stock price loaded",
        html=_load_widget_html("stock-quote"),
        response_text="Rendered stock quote!",
    ),
    StockWidget(
        identifier="stock-chart",
        title="Show Stock Chart",
        template_uri="ui://widget/stock-chart.html",
        invoking="Loading stock chart",
        invoked="Stock chart loaded",
        html=_load_widget_html("stock-chart"),
        response_text="Rendered stock chart!",
    ),
    StockWidget(
        identifier="portfolio-view",
        title="View Portfolio",
        template_uri="ui://widget/portfolio",
        invoking="Opening portfolio",
        invoked="Portfolio displayed",
        html=_load_widget_html("portfolio"),
        response_text="Rendered portfolio view!",
    ),
]


MIME_TYPE = "text/html+skybridge"


WIDGETS_BY_ID: Dict[str, StockWidget] = {
    widget.identifier: widget for widget in widgets
}
WIDGETS_BY_URI: Dict[str, StockWidget] = {
    widget.template_uri: widget for widget in widgets
}


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class StockInput(BaseModel):
    """Schema for stock tools."""

    symbol: str = Field(
        ...,
        description="Stock ticker symbol (e.g. AAPL, TSLA, MSFT).",
    )

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="stock-trading-python",
    stateless_http=True,
)


TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Stock ticker symbol (e.g. AAPL, TSLA).",
        }
    },
    "required": ["symbol"],
    "additionalProperties": False,
}


def _resource_description(widget: StockWidget) -> str:
    return f"{widget.title} widget markup"


def _tool_meta(widget: StockWidget) -> Dict[str, Any]:
    return {
        "openai/outputTemplate": widget.template_uri,
        "openai/toolInvocation/invoking": widget.invoking,
        "openai/toolInvocation/invoked": widget.invoked,
        "openai/widgetAccessible": True,
    }


def _tool_invocation_meta(widget: StockWidget) -> Dict[str, Any]:
    return {
        "openai/toolInvocation/invoking": widget.invoking,
        "openai/toolInvocation/invoked": widget.invoked,
    }


# ---------------------------------------------------------------------------
# Tool & resource listing
# ---------------------------------------------------------------------------

@mcp._mcp_server.list_tools()
async def _list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name=widget.identifier,
            title=widget.title,
            description=widget.title,
            inputSchema=deepcopy(TOOL_INPUT_SCHEMA),
            _meta=_tool_meta(widget),
            annotations={
                "destructiveHint": False,
                "openWorldHint": False,
                "readOnlyHint": True,
            },
        )
        for widget in widgets
    ]


@mcp._mcp_server.list_resources()
async def _list_resources() -> List[types.Resource]:
    return [
        types.Resource(
            name=widget.title,
            title=widget.title,
            uri=widget.template_uri,
            description=_resource_description(widget),
            mimeType=MIME_TYPE,
            _meta=_tool_meta(widget),
        )
        for widget in widgets
    ]


@mcp._mcp_server.list_resource_templates()
async def _list_resource_templates() -> List[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(
            name=widget.title,
            title=widget.title,
            uriTemplate=widget.template_uri,
            description=_resource_description(widget),
            mimeType=MIME_TYPE,
            _meta=_tool_meta(widget),
        )
        for widget in widgets
    ]


# ---------------------------------------------------------------------------
# Resource handling
# ---------------------------------------------------------------------------

async def _handle_read_resource(req: types.ReadResourceRequest) -> types.ServerResult:
    widget = WIDGETS_BY_URI.get(str(req.params.uri))
    if widget is None:
        return types.ServerResult(
            types.ReadResourceResult(
                contents=[],
                _meta={"error": f"Unknown resource: {req.params.uri}"},
            )
        )

    contents = [
        types.TextResourceContents(
            uri=widget.template_uri,
            mimeType=MIME_TYPE,
            text=widget.html,
            _meta=_tool_meta(widget),
        )
    ]

    return types.ServerResult(types.ReadResourceResult(contents=contents))


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _mock_stock_price(symbol: str) -> Dict[str, float]:
    """Mock stock pricing logic (replace with real API later)."""
    price = round(random.uniform(50, 500), 2)
    change = round(random.uniform(-5, 5), 2)
    return {"price": price, "change": change}


async def _call_tool_request(req: types.CallToolRequest) -> types.ServerResult:
    widget = WIDGETS_BY_ID.get(req.params.name)
    if widget is None:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Unknown tool: {req.params.name}",
                    )
                ],
                isError=True,
            )
        )

    arguments = req.params.arguments or {}
    try:
        payload = StockInput.model_validate(arguments)
    except ValidationError as exc:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Input validation error: {exc.errors()}",
                    )
                ],
                isError=True,
            )
        )

    stock_data = _mock_stock_price(payload.symbol)
    meta = _tool_invocation_meta(widget)

    return types.ServerResult(
        types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=widget.response_text,
                )
            ],
            structuredContent={
                "symbol": payload.symbol,
                "price": stock_data["price"],
                "change": stock_data["change"],
            },
            _meta=meta,
        )
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

mcp._mcp_server.request_handlers[types.CallToolRequest] = _call_tool_request
mcp._mcp_server.request_handlers[types.ReadResourceRequest] = _handle_read_resource


app = mcp.streamable_http_app()


try:
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
except Exception:
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)
