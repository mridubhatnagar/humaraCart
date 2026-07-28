"""ConsoleMessenger tests: send/broadcast are inspectable, no network."""

from __future__ import annotations

from app.whatsapp.console_messenger import ConsoleMessenger


def test_send_records_the_message():
    m = ConsoleMessenger()
    m.send("+91111", "hello")
    assert m.sent == [("+91111", "hello")]


def test_broadcast_sends_to_every_recipient():
    m = ConsoleMessenger()
    m.broadcast(["+91111", "+91222"], "update")
    assert m.sent == [("+91111", "update"), ("+91222", "update")]


def test_send_logs_the_message(caplog):
    """This is the class's whole reason to exist — a stand-in chat window
    visible in the terminal during local rehearsal (no Twilio spend)."""
    with caplog.at_level("INFO", logger="app.whatsapp.console_messenger"):
        ConsoleMessenger().send("+91111", "hello")

    assert "[WhatsApp -> +91111] hello" in caplog.text
