"""A stand-in for `ChatOpenAI` that returns pre-written responses in order.

A real LLM is non-deterministic, so a test asserting "the graph loops back
after a tool result" would pass today and fail tomorrow for reasons that have
nothing to do with our wiring. This makes the model's side of the conversation
fixed, so what's left under test is the graph itself.

Same idea as `MockInstamartClient`: the real code runs, one collaborator is a
double.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def reply(text: str) -> AIMessage:
    return AIMessage(content=text)


class ScriptedChatModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.received: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.received.append(list(messages))
        if not self._responses:
            raise AssertionError("ScriptedChatModel ran out of responses")
        return self._responses.pop(0)
