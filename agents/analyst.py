"""
Manager Analyst Agent — conversational data analyst for the manager dashboard.
Answers natural language questions about sales, trends, anomalies, and signals.
Does NOT approve POs, does NOT set prices, does NOT modify data.
"""
import json
from typing import Any

import google.generativeai as genai
import config
from agents import mcp_client
from gs_api import sse

SYSTEM_PROMPT = """You are a retail data analyst agent for Groundswell.
You help store managers understand their sales data by answering questions in plain English.

Your capabilities:
- Explain why specific products are selling more or less than usual
- Compare performance across categories, SKUs, and stores
- Detect sales anomalies and explain likely causes
- Cross-reference social media signals with actual sales movements
- Identify which stores are over/under performing and why
- Surface actionable insights the manager can act on

Your constraints:
- You NEVER approve purchase orders — that requires explicit manager action
- You NEVER set or change prices
- You NEVER modify any data — you are read-only
- Always cite the data behind your explanation (show the numbers)
- When you don't know something, say so — don't fabricate trends

Tone: concise, direct, business-focused. Explain the "why" behind numbers.
When a product is underperforming, suggest a possible cause and one actionable next step.
"""


def _build_tool_definitions() -> list[dict]:
    return [
        {
            "name": "get_sales_summary",
            "description": "Get total units sold and revenue for a SKU, category, or store over N days",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Product SKU (optional)"},
                    "category": {"type": "string", "description": "Product category (optional)"},
                    "store_id": {"type": "string", "description": "Store ID (optional)"},
                    "days": {"type": "integer", "description": "Lookback period in days", "default": 30},
                },
            },
        },
        {
            "name": "get_sales_trend",
            "description": "Day-by-day sales trend for a SKU — shows if sales are rising, falling, or stable",
            "parameters": {
                "type": "object",
                "required": ["sku"],
                "properties": {
                    "sku": {"type": "string"},
                    "days": {"type": "integer", "default": 30},
                },
            },
        },
        {
            "name": "get_category_performance",
            "description": "Rank all product categories by revenue and compare to prior period",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 30},
                },
            },
        },
        {
            "name": "get_sales_anomalies",
            "description": "Detect SKUs with unusually high or low sales vs their 90-day baseline (z-score > 1.5)",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 14},
                },
            },
        },
        {
            "name": "get_store_comparison",
            "description": "Compare sales performance across all stores, optionally filtered by SKU",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "days": {"type": "integer", "default": 30},
                },
            },
        },
        {
            "name": "get_correlation_signal_sales",
            "description": "Cross-reference social media post volume with actual sales — shows if buzz is translating to revenue",
            "parameters": {
                "type": "object",
                "required": ["sku"],
                "properties": {
                    "sku": {"type": "string"},
                    "days": {"type": "integer", "default": 14},
                },
            },
        },
        {
            "name": "get_social_signals",
            "description": "Fetch recent social media posts mentioning a SKU or general retail signals",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "hours": {"type": "integer", "default": 48},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "get_fused_forecast",
            "description": "Get the fused (ARIMA + social signal) demand forecast for a SKU",
            "parameters": {
                "type": "object",
                "required": ["sku"],
                "properties": {
                    "sku": {"type": "string"},
                },
            },
        },
    ]


def _call_tool(tool_name: str, tool_args: dict, session_id: str) -> Any:
    agent_name = "analyst_agent"
    if tool_name == "get_sales_summary":
        return mcp_client.get_sales_summary(session_id, agent_name, **tool_args)
    elif tool_name == "get_sales_trend":
        return mcp_client.get_sales_trend(tool_args["sku"], session_id, agent_name, tool_args.get("days", 30))
    elif tool_name == "get_category_performance":
        return mcp_client.get_category_performance(session_id, agent_name, tool_args.get("days", 30))
    elif tool_name == "get_sales_anomalies":
        return mcp_client.get_sales_anomalies(session_id, agent_name, tool_args.get("days", 14))
    elif tool_name == "get_store_comparison":
        return mcp_client.get_store_comparison(session_id, agent_name,
                                               tool_args.get("sku"), tool_args.get("days", 30))
    elif tool_name == "get_correlation_signal_sales":
        return mcp_client.get_correlation_signal_sales(tool_args["sku"], session_id, agent_name,
                                                        tool_args.get("days", 14))
    elif tool_name == "get_social_signals":
        return mcp_client.get_social_signals(session_id, agent_name,
                                              tool_args.get("sku"), tool_args.get("hours", 48),
                                              tool_args.get("limit", 20))
    elif tool_name == "get_fused_forecast":
        from gs_mcp.tools.signals import get_fused_forecast
        return get_fused_forecast(tool_args["sku"])
    raise ValueError(f"Unknown tool: {tool_name}")


def run(question: str, session_id: str) -> str:
    """
    Run the analyst agent on a manager question.
    Agentic loop: Gemini calls tools, we execute them, repeat until a final answer.
    Emits SSE events throughout so the trace panel shows all tool calls live.
    """
    genai.configure(api_key=None)  # uses ADC
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        tools=[{"function_declarations": _build_tool_definitions()}],
    )

    sse.emit_delegation(session_id, "orchestrator", "analyst_agent", f"Manager question: {question[:80]}")

    messages = [{"role": "user", "parts": [{"text": question}]}]

    for _ in range(6):  # max 6 rounds to prevent runaway loops
        response = model.generate_content(messages)
        candidate = response.candidates[0]

        tool_calls = [
            p.function_call
            for p in candidate.content.parts
            if hasattr(p, "function_call") and p.function_call.name
        ]

        if not tool_calls:
            # Final answer
            final_text = "".join(
                p.text for p in candidate.content.parts if hasattr(p, "text")
            )
            sse.emit_decision(session_id, "analyst_agent", "answered", question[:60], 0.9)
            return final_text

        # Execute tool calls and feed results back
        tool_results = []
        for fc in tool_calls:
            tool_name = fc.name
            tool_args = dict(fc.args)
            import time
            t0 = time.time()
            try:
                result = _call_tool(tool_name, tool_args, session_id)
                latency = (time.time() - t0) * 1000
                summary = _summarize_result(tool_name, result)
                sse.emit_tool_call(session_id, "analyst_agent", tool_name, tool_args, summary, latency)
                tool_results.append({
                    "function_response": {
                        "name": tool_name,
                        "response": {"result": result},
                    }
                })
            except Exception as e:
                tool_results.append({
                    "function_response": {
                        "name": tool_name,
                        "response": {"error": str(e)},
                    }
                })

        messages.append({"role": "model", "parts": [{"function_call": {"name": fc.name, "args": dict(fc.args)}} for fc in tool_calls]})
        messages.append({"role": "user", "parts": tool_results})

    return "I was unable to fully answer your question. Please try rephrasing or ask something more specific."


def _summarize_result(tool_name: str, result: Any) -> str:
    if tool_name == "get_sales_summary":
        rows = result.get("rows", [])
        if rows:
            top = rows[0]
            return f"Top: {top.get('name','')} {top.get('total_units',0)} units ${top.get('total_revenue',0):.0f}"
        return "no data"
    if tool_name == "get_sales_trend":
        return f"trend={result.get('trend')} pct_change={result.get('pct_change_first_vs_second_half',0):.1f}%"
    if tool_name == "get_category_performance":
        cats = result.get("categories", [])
        return f"{len(cats)} categories; top={cats[0].get('category','') if cats else 'none'}"
    if tool_name == "get_sales_anomalies":
        return f"over={len(result.get('over_performers',[]))} under={len(result.get('under_performers',[]))}"
    if tool_name == "get_store_comparison":
        stores = result.get("stores", [])
        return f"{len(stores)} stores; top={stores[0].get('store_name','') if stores else 'none'}"
    if tool_name == "get_correlation_signal_sales":
        days = result.get("correlation_data", [])
        return f"{len(days)} days of signal/sales correlation"
    return str(result)[:120]
