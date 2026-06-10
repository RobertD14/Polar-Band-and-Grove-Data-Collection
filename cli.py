"""CLI tools for selecting and configuring scripts."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from prompt_toolkit import HTML, PromptSession, print_formatted_text
from prompt_toolkit.application import get_app
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.validation import Validator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document


class SuggestDefaultArg(AutoSuggest):
    """Suggest the default argument when the buffer is empty."""

    @override
    def __init__(self, default: str | None) -> None:
        super().__init__()
        self.default = default if isinstance(default, str) else ''

    @override
    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        if buffer.text == '':
            return Suggestion(self.default)
        return None


class Session:
    """Custom prompt session with autosuggestion and default support."""

    def __init__(self, default: str = '') -> None:
        """Initialize the option parser with a script module and prompt session."""
        self.session = PromptSession[str](
            auto_suggest=SuggestDefaultArg(default),
            validate_while_typing=False,
            mouse_support=True,
        )
        self.default = default

    def _prime_autosuggest(self) -> None:
        """Prime the prompt-toolkit suggester."""
        get_app().create_background_task(self.session.default_buffer._async_suggester())

    @staticmethod
    def _overwrite(text: str) -> None:
        """Print formatted HTML to the console, overwriting the current line."""
        print('\033[F\033[K', end='', flush=True)  # noqa
        print_formatted_text(HTML(text))

    def prompt(self, text: str) -> str:
        """Prompt the user for input with `text` as guidance."""
        value = self.session.prompt(
            HTML(f'  <ansicyan>{text}: </ansicyan>'),
            pre_run=self._prime_autosuggest,
            validator=Validator.from_callable(lambda x: bool(x.strip()), 'This input cannot be blank'),
        )
        if value == self.default:
            self._overwrite(f'  <ansicyan>{text}: </ansicyan>{value}<magenta> (default)</magenta>')
        return value


class AutoComplete(Session):
    """CLI tool to perform autocompletion."""

    @override
    def __init__(self, default: str = '', options: Sequence[str] = ['']) -> None:
        super().__init__(default)
        self.options = options

    @override
    def prompt(self, text: str) -> str:
        value = self.session.prompt(
            HTML(f'  <ansicyan>{text}: </ansicyan>'),
            pre_run=self._prime_autocomplete,
            completer=WordCompleter(self.options, match_middle=True, sentence=True, ignore_case=True),
            validator=Validator.from_callable(lambda x: x in self.options or not x, 'INVALID OPTION'),
        )
        if (value := value or self.default) == self.default:
            self._overwrite(f'  <ansicyan>{text}: </ansicyan>{value}<magenta> (default)</magenta>')
        return value

    def _prime_autocomplete(self) -> None:
        """Prime the prompt-toolkit autocompleter."""
        self._prime_autosuggest()
        b = get_app().current_buffer
        if b.complete_state:
            b.complete_next()
        else:
            b.start_completion(select_first=False)
