"""Animated thinking indicator widget."""
from textual.app import ComposeResult
from textual.widgets import Static
from textual.reactive import reactive


class ThinkingIndicator(Static):
    """Animated 'Thinking...' indicator with wave effect."""

    dots_state = reactive(0)

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.animation_frames = [
            "Thinking.  ",
            "Thinking.. ",
            "Thinking...",
            "Thinking ..",
            "Thinking  .",
            "Thinking   ",
        ]
        self.frame_index = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def on_mount(self) -> None:
        """Start animation when mounted."""
        self.set_interval(0.15, self.animate_dots)

    def set_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Set token counts to display."""
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def reset_tokens(self) -> None:
        """Reset token counts."""
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def animate_dots(self) -> None:
        """Cycle through animation frames."""
        base_text = self.animation_frames[self.frame_index]

        # Add token info if available
        if self.prompt_tokens > 0 or self.completion_tokens > 0:
            total = self.prompt_tokens + self.completion_tokens
            token_text = f" [dim]({self.prompt_tokens:,} in, {self.completion_tokens:,} out = {total:,} tokens)[/dim]"
            self.update(f"[dim]{base_text}[/dim]{token_text}")
        else:
            self.update(f"[dim]{base_text}[/dim]")

        self.frame_index = (self.frame_index + 1) % len(self.animation_frames)
