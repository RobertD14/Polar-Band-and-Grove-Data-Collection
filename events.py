"""Keyboard listener for event logging."""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
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

TIMER_BARS = 20


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
        self.timer_flag = Event()

    def log_event(self, key: str) -> None:
        """Log a key event."""
        if self.events and (latest := self.events[-1]).event_type == 'Start':
            self.stop_event()
            if latest.key == key:
                return

        self.events.append(event := KeyEvent(key, 'Start'))
        logger.success(f'Starting {event.label} test...')

    def stop_event(self) -> None:
        """Stop any active event."""
        if self.events and (latest := self.events[-1]).event_type == 'Start':
            self.events.append(event := KeyEvent(latest.key, 'Stop'))
            logger.success(f'Stopping {event.label} test...')

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
        logger.success(f'Saved {len(self.events)} events to {self.outfile.name}')

    def timer(self, duration: int) -> None:
        """Run a decrementing timer for a specified duration."""
        start = time.time()
        self.timer_flag.set()
        logger.info(f'Starting timer for {duration} seconds...\n')

        bars = ''
        while (elapsed := time.time() - start) < duration and self.timer_flag.is_set():
            bars = '|' * round((elapsed / duration) * TIMER_BARS)
            logger.info(f'[{bars: <20}] {elapsed:.1f} / {duration} seconds', overwrite=True)
            time.sleep(0.1)

        if self.timer_flag.is_set():
            logger.success(f'[{bars: <20}] Timer completed.', overwrite=True)
        else:
            logger.warning(f'[{bars: <20}] Timer interrupted.', overwrite=True)

    def on_press(self, key: str) -> None:
        """Handle key press events."""
        self.timer_flag.clear()
        time.sleep(0.2)  # Allow log to flush before processing events

        if key in self.listen:
            self.log_event(key)
        elif key.isdigit():
            self.stop_event()
            Thread(target=self.timer, args=(int(key) * 60,), daemon=True).start()
