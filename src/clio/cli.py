"""CLI entry point."""
import sys
import os
import click
from pathlib import Path

# Capture the working directory IMMEDIATELY at entry point
# before any imports or operations that might change it
_LAUNCH_CWD = os.getcwd()


@click.group(invoke_without_command=True)
@click.option('--history', 'show_history', is_flag=True, help='List recent conversations')
@click.option('--cleanup', 'do_cleanup', is_flag=True, help='Delete old conversations')
@click.option('--continue', 'continue_id', type=int, help='Continue a conversation by ID')
@click.pass_context
def main(ctx, show_history, do_cleanup, continue_id):
    """Claude Clone - Self-hosted AI coding assistant."""
    from .history.database import HistoryDatabase
    from datetime import datetime

    # Handle --history flag
    if show_history:
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=20)

        if not conversations:
            click.echo("No conversation history found.")
            db.close()
            return

        click.echo("\n📜 Recent Conversations (20 most recent):\n")

        for conv in conversations:
            conv_id = conv['id']
            start_time = datetime.fromisoformat(conv['start_time']).strftime('%Y-%m-%d %H:%M:%S')
            model = conv['model']
            msg_count = conv['message_count']
            title = conv['title'] or f"Conversation in {Path(conv['working_dir']).name}"
            starred = "⭐ " if conv['starred'] else ""

            click.echo(f"  [{conv_id}] {starred}{title}")
            click.echo(f"      {start_time} | {model} | {msg_count} messages")
            click.echo()

        click.echo("\nTo continue a conversation, run:")
        click.echo("  clio --continue <id>")
        db.close()
        return

    # Handle --cleanup flag
    if do_cleanup:
        db = HistoryDatabase()
        click.echo("🧹 Cleaning up old conversations...")
        deleted = db.cleanup_old_conversations(keep_recent=20)

        if deleted:
            click.echo(f"✓ Deleted {deleted} old conversation(s)")
        else:
            click.echo("✓ No old conversations to delete")

        db.close()
        return

    # Handle --continue flag
    if continue_id is not None:
        from .ui.app import ChatApp
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=100)
        conv_ids = [c['id'] for c in conversations]
        db.close()

        if continue_id not in conv_ids:
            click.echo(f"❌ Conversation {continue_id} not found.")
            return

        # Start app with conversation ID
        app = ChatApp(launch_dir=_LAUNCH_CWD, conversation_id=continue_id)
        app.run()
        return

    if ctx.invoked_subcommand is None:
        # Run interactive mode
        from .ui.app import ChatApp
        app = ChatApp(launch_dir=_LAUNCH_CWD)
        app.run()


@main.command()
def setup():
    """Run initial setup wizard."""
    from .config.manager import ConfigManager
    
    config_manager = ConfigManager()
    config = config_manager.load()
    
    click.echo("🚀 CLIO Setup")
    click.echo(f"\nConfiguration file: {config_manager.config_path}")
    click.echo("\nCurrent configuration:")
    click.echo(f"  Provider: {config.defaults.provider}")
    click.echo(f"  Model: {config.defaults.model}")
    click.echo("\nSetup complete! Run 'clio' to start.")


@main.command()
@click.argument('provider_name')
@click.option('--url', help='Base URL for API')
@click.option('--api-key', help='API key')
@click.option('--type', default='openai-compatible', help='Provider type')
def add_provider(provider_name, url, api_key, type):
    """Add a new provider."""
    from .config.manager import ConfigManager
    from .config.schema import ProviderConfig
    
    config_manager = ConfigManager()
    
    provider = ProviderConfig(
        type=type,
        base_url=url,
        api_key=api_key,
        models=[]
    )
    
    config_manager.add_provider(provider_name, provider)
    click.echo(f"✓ Added provider: {provider_name}")


@main.command()
def version():
    """Show version."""
    click.echo("Claude Clone v0.1.0")


@main.command()
@click.option('--working-dir', default=None, help='Working directory')
def vscode(working_dir):
    """Run in VSCode extension mode (JSON protocol via stdio)."""
    import asyncio
    from .vscode_mode import run_vscode_mode

    working_dir = working_dir or _LAUNCH_CWD
    asyncio.run(run_vscode_mode(working_dir))


if __name__ == "__main__":
    main()
