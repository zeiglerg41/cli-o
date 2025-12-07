"""VSCode extension mode - communicate via JSON over stdio."""
import asyncio
from pathlib import Path
from .vscode_protocol import VSCodeProtocol
from .config.manager import ConfigManager
from .agent.core import Agent
from .context.manager import ContextManager


async def run_vscode_mode(working_dir: str):
    """Run clio in VSCode extension mode."""
    # Initialize protocol
    protocol = VSCodeProtocol()

    # Initialize config and agent
    config_manager = ConfigManager()
    context_manager = ContextManager(working_dir=working_dir)

    # Create agent with VSCode protocol
    agent = Agent(
        config_manager=config_manager,
        tool_callback=lambda tool, args, result: asyncio.create_task(
            on_tool_executed(protocol, tool, args, result)
        )
    )

    # Pass protocol to tools
    agent.tools.vscode_protocol = protocol

    # Handle incoming messages
    async def handle_message(message: dict):
        """Handle message from VS Code extension."""
        try:
            if "content" in message:
                # User message
                user_content = message["content"]

                # Add file context if working in a directory
                context = context_manager.get_context()
                if context:
                    user_content = f"{context}\n\n{user_content}"

                # Send status
                protocol.send_status("Processing request...")

                # Process with agent
                response = await agent.process_message(user_content)

                # Send response
                protocol.send_response(response)

                # Send status
                protocol.send_status("Ready")

        except Exception as e:
            protocol.send_error(f"Error processing message: {str(e)}")

    protocol.message_callback = handle_message

    # Send initial ready status
    protocol.send_status("Ready")

    # Start reading messages from stdin
    await protocol.read_messages()


async def on_tool_executed(protocol: VSCodeProtocol, tool_name: str, arguments: dict, result: str):
    """Handle tool execution notification."""
    protocol.send_tool_execution(tool_name, arguments, result)
