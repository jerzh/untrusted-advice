"""Placeholder for the protocol under study.

Right now it behaves exactly like `ct/null-blue-team` (every action runs unmodified),
so it only proves the plugin is wired up. Replace `on_input` / `on_output` with the real
protocol; `control_tower/protocols/trusted_monitoring.py` is the reference example.
"""

from inspect_ai.model import ChatMessage, ChatMessageAssistant

from control_tower.eval.blue import Audited, Draw, Protocol
from control_tower.eval.game_view import BlueView
from control_tower.eval.registry import protocols


@protocols.register(name="my-protocol")
class MyProtocol(Protocol):
    """TODO: the new control protocol. Currently a pass-through."""

    async def on_input(
        self, view: BlueView, conversation: list[ChatMessage]
    ) -> list[ChatMessage] | None:
        return await super().on_input(view, conversation)

    async def on_output(
        self, view: BlueView, draw: Draw
    ) -> ChatMessageAssistant | Audited:
        del view
        return (await draw(1))[0]
