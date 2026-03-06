"""Keyboard listener for event logging."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from loguru import logger
from pynput.keyboard import Key, Listener

# Keys and labels for event logging
EVENT_LABELS: dict[str, str] = {
    'n': 'N-Back',
    's': 'Stroop',
    'r': 'Reaction',
    'z': 'Resting',
}
LISTEN = tuple(EVENT_LABELS.keys())


@dataclass
class KeyEvent:
    """Data class for key events."""

    key: str
    event_type: Literal['Start', 'Stop']
    timestamp: str = field(default_factory=lambda: datetime.now().strftime('%H:%M:%S.%f'))
    label: str = field(init=False)

    def __post_init__(self) -> None:
        """Assign label following initialization."""
        self.label = EVENT_LABELS.get(self.key, '')


class KeyEventLogger:
    """Log filtered key events with timestamps."""

    listen: tuple[str, ...] = LISTEN

    def __init__(self, outfile: Path) -> None:
        """Initialize the KeyEventLogger with a target outfile."""
        self.events: list[KeyEvent] = []
        self.outfile = outfile
        self.listener = Listener(on_press=self.on_press, suppress=True)  # type: ignore
        self.listener.start()

    def log_event(self, key: str) -> None:
        """Log a key event."""
        event = None
        if self.events:
            latest = self.events[-1]
            if latest.key == key:
                event = KeyEvent(key, 'Stop' if latest.event_type == 'Start' else 'Start')
            elif latest.event_type == 'Start':
                self.log_event(latest.key)

        event = event or KeyEvent(key, 'Start')
        self.events.append(event)
        logger.success(f'Recording `{event.event_type}` event for {event.label}')

    def save_events(self) -> None:
        """Stop running event listener and save event buffer to disk."""
        if self.listener.is_alive():
            self.listener.stop()

        if self.events:
            latest = self.events[-1]
            if latest.event_type == 'Start':
                self.log_event(latest.key)

        events = pd.DataFrame(self.events)
        events.to_csv(self.outfile, index=False)

    def on_press(self, key: Key) -> None:
        """Handle key press events."""
        try:
            if (char := getattr(key, 'char', None)) in self.listen:
                self.log_event(char)
        except AttributeError:
            pass
