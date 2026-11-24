"""A scripted ChatClient: replays a fixed list of steps so the real agent loop,
tools, guard, DB roles and tracing can be tested without an LLM."""

import json


class ScriptedClient:
    model = "scripted"

    def __init__(self, steps):
        # steps: list of ("tool", name, args_dict) or ("answer", text) or a callable(messages) -> step
        self.steps = list(steps)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append(messages[-1])
        step = self.steps.pop(0)
        if callable(step):
            step = step(messages)
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        if step[0] == "answer":
            return {"content": step[1], "tool_calls": [], "usage": usage}
        _, name, args = step
        return {"content": "", "tool_calls": [{"id": f"call_{len(self.seen)}", "name": name,
                                               "arguments": json.dumps(args)}], "usage": usage}
