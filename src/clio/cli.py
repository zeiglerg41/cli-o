"""CLI entry point."""
import sys
import os
import click
from pathlib import Path
from datetime import datetime, timedelta

# Capture the working directory IMMEDIATELY at entry point
# before any imports or operations that might change it
_LAUNCH_CWD = os.getcwd()


def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to relative time string like '2 hours ago'."""
    dt = datetime.fromisoformat(iso_timestamp)
    now = datetime.now()
    diff = now - dt

    if diff < timedelta(minutes=1):
        return "just now"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif diff < timedelta(days=30):
        weeks = diff.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif diff < timedelta(days=365):
        months = diff.days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = diff.days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"


@click.group(invoke_without_command=True)
@click.option('--history', 'show_history', is_flag=True, help='List recent conversations')
@click.option('--cleanup', 'do_cleanup', is_flag=True, help='Delete old conversations')
@click.option('--continue', 'continue_flag', is_flag=True, help='Continue a conversation (interactive selection)')
@click.pass_context
def main(ctx, show_history, do_cleanup, continue_flag):
    """Claude Clone - Self-hosted AI coding assistant."""
    from .history.database import HistoryDatabase
    from .config.manager import ConfigManager

    # Load config for preferences
    config_manager = ConfigManager()
    config = config_manager.load()
    max_recent = config.preferences.max_recent_conversations

    # Handle --history flag
    if show_history:
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=max_recent)

        if not conversations:
            click.echo("No conversation history found.")
            db.close()
            return

        click.echo(f"\nRecent Conversations ({max_recent} most recent):\n")

        for conv in conversations:
            conv_id = conv['id']
            time_ago = relative_time(conv['start_time'])
            model = conv['model']
            msg_count = conv['message_count']
            title = conv['title'] or "New conversation"
            starred = "* " if conv['starred'] else ""
            working_dir = Path(conv['working_dir']).name

            click.echo(f"  {starred}{title}")
            click.echo(f"  {time_ago} · {msg_count} messages · {working_dir}")
            click.echo()

        click.echo("\nTo continue a conversation, run:")
        click.echo("  clio --continue")
        db.close()
        return

    # Handle --cleanup flag
    if do_cleanup:
        db = HistoryDatabase()
        click.echo("Cleaning up old conversations...")
        deleted = db.cleanup_old_conversations(keep_recent=max_recent)

        if deleted:
            click.echo(f"Deleted {deleted} old conversation(s)")
        else:
            click.echo("No old conversations to delete")

        db.close()
        return

    # Handle --continue flag
    if continue_flag:
        from simple_term_menu import TerminalMenu
        from .ui.app import ChatApp
        import shutil

        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=max_recent)
        db.close()

        if not conversations:
            click.echo("No conversations found. Start a new session with 'clio'")
            return

        # Get terminal width
        terminal_width = shutil.get_terminal_size().columns

        # Build menu options - completely single line
        menu_items = []
        conv_map = {}

        for idx, conv in enumerate(conversations):
            conv_id = conv['id']
            time_ago = relative_time(conv['start_time'])
            msg_count = conv['message_count']
            title = conv['title'] or "New conversation"
            working_dir = Path(conv['working_dir']).name
            starred = "* " if conv['starred'] else ""

            # Calculate available space for title
            # Format: "> • {title}  ({time} · {N} msgs · {dir})"
            # Reserve space for: cursor (3) + bullet (2) + metadata (~35 chars) + margins (5)
            metadata = f"  ({time_ago} · {msg_count} msgs · {working_dir})"
            reserved_space = 3 + 2 + len(metadata) + 5
            if starred:
                reserved_space += 2  # for star emoji

            max_title_len = max(20, terminal_width - reserved_space)  # At least 20 chars for title

            display_title = title[:max_title_len]
            if len(title) > max_title_len:
                display_title = display_title[:max_title_len-3] + "..."

            # Completely single line format with bullet
            menu_text = f"• {starred}{display_title}{metadata}"

            menu_items.append(menu_text)
            conv_map[menu_text] = conv_id

        # Show interactive menu
        terminal_menu = TerminalMenu(
            menu_items,
            title="Resume Session (Up/Down to navigate, Enter to select, q to quit)",
            menu_cursor="> ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("fg_cyan", "bold"),
            cursor_index=0,  # Start at first item (top)
            multi_select=False,
            show_search_hint=False,
            clear_screen=False,
        )

        menu_entry_index = terminal_menu.show()

        if menu_entry_index is None:
            # User pressed 'q' or Ctrl+C
            click.echo("\nCancelled")
            return

        selected_menu_text = menu_items[menu_entry_index]
        continue_id = conv_map[selected_menu_text]

        # Start app with conversation ID
        app = ChatApp(launch_dir=_LAUNCH_CWD, conversation_id=continue_id)
        app.run()
        return

    if ctx.invoked_subcommand is None:
        # Run interactive mode
        from .ui.app import ChatApp

        # Loop to handle /history restarts
        conversation_id = None
        while True:
            app = ChatApp(launch_dir=_LAUNCH_CWD, conversation_id=conversation_id)
            app.run()

            # Check if user selected a conversation from /history
            if app.selected_conversation_id:
                conversation_id = app.selected_conversation_id
                # Restart with the selected conversation
                continue
            else:
                # Normal exit
                break


@main.command()
def setup():
    """Run initial setup wizard."""
    from .config.manager import ConfigManager
    
    config_manager = ConfigManager()
    config = config_manager.load()
    
    click.echo("CLIO Setup")
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
    click.echo(f"Added provider: {provider_name}")


@main.command()
def version():
    """Show version."""
    click.echo("Claude Clone v0.1.0")


@main.command()
@click.option('--working-dir', default=None, help='Working directory')
def vscode(working_dir):
    """Run in VSCode extension mode (JSON protocol via stdio)."""
    from asyncio import run
    from .vscode_mode import run_vscode_mode

    working_dir = working_dir or _LAUNCH_CWD
    run(run_vscode_mode(working_dir))


if __name__ == "__main__":
    main()
