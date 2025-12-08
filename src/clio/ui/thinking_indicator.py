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

    def on_mount(self) -> None:
        """Start animation when mounted."""
        self.set_interval(0.15, self.animate_dots)

    def animate_dots(self) -> None:
        """Cycle through animation frames."""
        self.update(f"[dim]{self.animation_frames[self.frame_index]}[/dim]")
        self.frame_index = (self.frame_index + 1) % len(self.animation_frames)
