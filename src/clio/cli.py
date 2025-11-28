"""CLI entry point."""
import sys
import os
import click
from pathlib import Path

# Capture the working directory IMMEDIATELY at entry point
# before any imports or operations that might change it
_LAUNCH_CWD = os.getcwd()


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """Claude Clone - Self-hosted AI coding assistant."""
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


if __name__ == "__main__":
    main()
