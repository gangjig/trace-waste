"""A tiny built-in sample trace, shared by the demo command and the
examples directory. It contains one instance of each waste category:
an unused context segment, a duplicated reasoning block, a repeated
tool call with an identical result, and a tool result nobody uses.
"""

SAMPLE_TRACE = """\
{"type": "context", "id": "ctx-rules", "text": "Always answer in English. Be concise. Cite sources when you browse."}
{"type": "context", "id": "ctx-legacy", "text": "Legacy formatting rules from 2019: wrap every answer in XML tags and add a fax header line."}
{"type": "reasoning", "text": "The user wants the weather in Arlington today. I should call the weather tool for Arlington VA and then summarize the result briefly."}
{"type": "tool_call", "id": "call-1", "tool": "get_weather", "args": {"city": "Arlington, VA"}}
{"type": "tool_result", "call_id": "call-1", "result": "Sunny, high 58F, NW wind 13 mph, gusts 25 mph, no rain."}
{"type": "reasoning", "text": "The user wants the weather in Arlington today. I should call the weather tool for Arlington VA and then summarize the result briefly."}
{"type": "tool_call", "id": "call-2", "tool": "get_weather", "args": {"city": "Arlington, VA"}}
{"type": "tool_result", "call_id": "call-2", "result": "Sunny, high 58F, NW wind 13 mph, gusts 25 mph, no rain."}
{"type": "tool_call", "id": "call-3", "tool": "get_news", "args": {"topic": "local sports"}}
{"type": "tool_result", "call_id": "call-3", "result": "High school football scores from Friday night across the county and the regional rankings."}
{"type": "text", "text": "Today in Arlington: Sunny, high 58F, NW wind 13 mph, gusts 25 mph, no rain.", "refs": ["call-1", "ctx-rules"]}
"""
