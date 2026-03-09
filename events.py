"""Keyboard listener for event logging."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Literal

import pandas as pd
from loguru import logger
from sshkeyboard import listen_keyboard, stop_listening

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
        self.listener = Thread(target=listen_keyboard, kwargs={'on_press': self.on_press})
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
        logger.info('Stopping key listener and saving events...')
        if self.listener.is_alive():
            stop_listening()

        if self.events:
            latest = self.events[-1]
            if latest.event_type == 'Start':
                self.log_event(latest.key)

        events = pd.DataFrame(self.events)
        events.to_csv(self.outfile, index=False)
        logger.success(f'Saved {len(self.events)} to {self.outfile.name}')

    def on_press(self, key: str) -> None:
        """Handle key press events."""
        if key in self.listen:
            self.log_event(key)
