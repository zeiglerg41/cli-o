"""Session-based logging for AI agent interactions."""
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional


class SessionLogger:
    """Logger that creates one log file per clio session."""

    def __init__(self, log_dir: Optional[Path] = None):
        """Initialize session logger.

        Args:
            log_dir: Directory to store log files. Defaults to ~/.clio/logs/
        """
        if log_dir is None:
            log_dir = Path.home() / ".clio" / "logs"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create session log file with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file = self.log_dir / f"session_{timestamp}.log"

        # Create logger
        self.logger = logging.getLogger(f"clio.session.{timestamp}")
        self.logger.setLevel(logging.DEBUG)

        # Remove existing handlers
        self.logger.handlers.clear()

        # Create file handler
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        # Add handler to logger
        self.logger.addHandler(file_handler)

        # Log session start
        self.logger.info("="*80)
        self.logger.info(f"CLIO SESSION STARTED")
        self.logger.info(f"Log file: {self.log_file}")
        self.logger.info("="*80)

    def log_user_message(self, message: str, context: str = ""):
        """Log a user message."""
        self.logger.info("-" * 40)
        self.logger.info("USER MESSAGE")
        if context:
            self.logger.info(f"Context: {context[:200]}..." if len(context) > 200 else f"Context: {context}")
        self.logger.info(f"Message: {message}")

    def log_llm_request(self, model: str, message_count: int, tool_count: int, total_chars: int):
        """Log LLM API request details."""
        self.logger.debug(f"LLM Request -> Model: {model}, Messages: {message_count}, Tools: {tool_count}, Chars: {total_chars}")

    def log_llm_response(self, content: Optional[str], has_tool_calls: bool, finish_reason: str):
        """Log LLM response."""
        if has_tool_calls:
            self.logger.info("LLM Response: [Tool calls requested]")
        else:
            preview = content[:200] + "..." if content and len(content) > 200 else content
            self.logger.info(f"LLM Response: {preview}")
        self.logger.debug(f"Finish reason: {finish_reason}")

    def log_tool_call(self, tool_name: str, arguments: dict):
        """Log a tool call."""
        self.logger.info(f"TOOL CALL: {tool_name}")
        self.logger.debug(f"Arguments: {arguments}")

    def log_tool_result(self, tool_name: str, result: str):
        """Log tool execution result."""
        preview = result[:300] + "..." if len(result) > 300 else result
        self.logger.info(f"TOOL RESULT ({tool_name}): {preview}")

    def log_iteration(self, iteration: int, max_iterations: int):
        """Log iteration number (for detecting loops)."""
        self.logger.debug(f"Iteration {iteration}/{max_iterations}")
        if iteration > 5:
            self.logger.warning(f"HIGH ITERATION COUNT: {iteration}/{max_iterations} - Possible loop detected!")

    def log_error(self, error: str):
        """Log an error."""
        self.logger.error(f"ERROR: {error}")

    def log_session_end(self):
        """Log session end."""
        self.logger.info("="*80)
        self.logger.info("CLIO SESSION ENDED")
        self.logger.info("="*80)

    def get_log_path(self) -> Path:
        """Get the path to the current session log file."""
        return self.log_file
