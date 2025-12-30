import typer
import subprocess
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from .config import settings
from .core import start_watching
from .rd_client import RealDebridClient

app = typer.Typer(help="Real-Debrid Torrent Automator CLI")
console = Console()

@app.command()
def start():
    """
    Start the directory watcher.
    """
    console.print(f"[green]Starting watcher on {settings.watch_path}[/green]")
    console.print(f"[blue]Outputting .torrent files to {settings.torrent_output_path}[/blue]")
    try:
        start_watching()
    except KeyboardInterrupt:
        console.print("[yellow]Stopping...[/yellow]")

@app.command()
def status():
    """
    Show recent activity or status (Mocked for now as we don't have a DB).
    Real implementation would query local logs or RD API.
    """
    try:
        rd = RealDebridClient(token=settings.rd_api_token)
        user_info = rd.get_user_info()
        console.print(f"[bold]User:[/bold] {user_info.get('username')}")
        console.print(f"[bold]Premium:[/bold] {user_info.get('type')}")
        console.print(f"[bold]Expiration:[/bold] {user_info.get('expiration')}")
        
    except Exception as e:
        console.print(f"[red]Error fetching status: {e}[/red]")
        console.print("[yellow]Check your RD_API_TOKEN in .env[/yellow]")

@app.command()
def config():
    """
    Opens the configuration file in the default editor.
    """
    config_path = Path("config.yaml")
    if not config_path.exists():
        console.print("[red]Config file config.yaml not found![/red]")
        return
    
    console.print(f"Opening {config_path}...")
    # Cross-platform open
    if os.name == 'nt':
        os.startfile(config_path)
    elif sys.platform == 'darwin':
        subprocess.call(('open', config_path))
    else:
        subprocess.call(('xdg-open', config_path))

if __name__ == "__main__":
    app()
