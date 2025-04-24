import os
import re
import sys
import argparse
import requests
import threading
import subprocess
import platform

from rich.text import Text
from rich.panel import Panel
from rich.console import Console

from datetime import datetime
from dotenv import dotenv_values

console = Console()

def parse_arguments():
    parser = argparse.ArgumentParser(description="Run the AI SDK API and/or sample chatbot with configurable timeout.")
    parser.add_argument("mode", choices=["api", "sample_chatbot", "both"], help="Mode to run: api, sample_chatbot, or both")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout in seconds (default: 30)")
    parser.add_argument("--load-demo", action="store_true", help="Load demo data before starting (only works with 'both' mode)")
    parser.add_argument("--host", default="localhost", help="GRPC host (default: localhost)")
    parser.add_argument("--grpc-port", type=int, default=9994, help="GRPC port (default: 9994)")
    parser.add_argument("--dc-port", type=int, default=9090, help="Data Catalog port (default: 9090)")
    parser.add_argument("--server-id", type=int, default=1, help="Server ID (default: 1)")
    parser.add_argument("--dc-user", default="admin", help="Data Catalog user (default: admin)")
    parser.add_argument("--dc-password", default="admin", help="Data Catalog password (default: admin)")
    parser.add_argument("--no-logs", action="store_true", help="Output logs to console instead of files")
    parser.add_argument("--max-log-size", type=int, default=1, help="Maximum log file size in MB before rotation (default: 1)")
    parser.add_argument("--production", action="store_true", help="Run in production mode")
    return parser.parse_args()

def empty_file(file_path):
    """Create an empty file at the specified path, creating parent directories if needed."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8'):
        pass

class RotatingLogFile:
    """
    A class that handles log rotation based on file size.
    Creates a new log file when the current one reaches the max_size.
    """
    def __init__(self, base_path, max_size=1024*1024):  # Default max_size is 1MB
        self.base_path = base_path
        self.max_size = max_size
        self.current_file = None
        self.current_path = None
        self._create_new_log_file()
    
    def _create_new_log_file(self):
        """Create a new log file with timestamp in the filename."""
        if self.current_file and not self.current_file.closed:
            self.current_file.close()
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.base_path), exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(self.base_path)
        filename = os.path.basename(self.base_path)
        name, ext = os.path.splitext(filename)
        
        # Create the new path with timestamp
        self.current_path = os.path.join(base_dir, f"{name}_{timestamp}{ext}")
        
        # Create and open the new log file
        self.current_file = open(self.current_path, "w", encoding='utf-8')
        return self.current_file
    
    def write(self, data):
        """Write data to the log file, rotating if necessary."""
        self.current_file.write(data)
        self.current_file.flush()
        
        # Check if rotation is needed
        if self.current_file.tell() >= self.max_size:
            self._create_new_log_file()
    
    def flush(self):
        """Flush the current log file."""
        if self.current_file and not self.current_file.closed:
            self.current_file.flush()
    
    def close(self):
        """Close the current log file."""
        if self.current_file and not self.current_file.closed:
            self.current_file.close()
    
    def get_current_path(self):
        """Get the path of the current log file."""
        return self.current_path

def print_header():
    """Display a stylized header for the application."""
    console.print(Panel(
        Text("Denodo AI SDK", style="bold white", justify="center"),
        border_style="cyan",
        padding=(1, 2),
        width=60
    ))

def print_status(process_type, urls, version=None):
    """Display a styled status message for running services."""
    if process_type == "api":
        panel = Panel(
            Text.assemble(
                ("AI SDK ", "bold red"),
                ("is running at: ", "bold white"),
                (f"{urls[0]}\n", "green"),
                ("Swagger docs: ", "bold white"),
                (f"{urls[0]}/docs\n", "green"),
                ("AI SDK version: ", "bold white"),
                (f"{version or 'Unknown'}", "yellow")
            ),
            title="[bold]API Status",
            border_style="red",
            width=60
        )
    else:
        # Create the text content using Text.assemble instead of append
        segments = []
        for i, url in enumerate(urls):
            segments.extend([
                ("Sample Chatbot ", "bold blue"),
                ("is running at: ", "bold white"),
                (url, "green")
            ])
            if i < len(urls) - 1:
                segments.append(("\n", ""))
        
        panel = Panel(
            Text.assemble(*segments),
            title="[bold]Chatbot Status",
            border_style="blue",
            width=60
        )
    console.print(panel)

def run_process(process_type, timeout=30, no_logs=False, max_log_size=1, production=False):
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    
    # Load environment variables from the appropriate .env file
    if process_type == "api":
        if os.path.exists("api/utils/sdk_config.env"):
            sdk_vars = dotenv_values("api/utils/sdk_config.env")
            HOST = sdk_vars.get("AI_SDK_HOST", "0.0.0.0")
            PORT = sdk_vars.get("AI_SDK_PORT", "8008")
            WORKERS = sdk_vars.get("AI_SDK_WORKERS", "1")
            SSL_CERT = sdk_vars.get("AI_SDK_SSL_CERT", None)
            SSL_KEY = sdk_vars.get("AI_SDK_SSL_KEY", None)
        else:
            console.print("[yellow]Warning:[/] Environment file api/utils/sdk_config.env not found.")
    elif process_type == "sample_chatbot":
        if os.path.exists("sample_chatbot/chatbot_config.env"):
            chatbot_vars = dotenv_values("sample_chatbot/chatbot_config.env")
            HOST = chatbot_vars.get("CHATBOT_HOST", "0.0.0.0")
            PORT = chatbot_vars.get("CHATBOT_PORT", "9992")
            WORKERS = chatbot_vars.get("CHATBOT_WORKERS", "1")
            SSL_CERT = chatbot_vars.get("CHATBOT_SSL_CERT", None)
            SSL_KEY = chatbot_vars.get("CHATBOT_SSL_KEY", None)
        else:
            console.print("[yellow]Warning:[/] Environment file sample_chatbot/chatbot_config.env not found.")
        
    success_event = threading.Event()
    default_log_path = os.path.join("logs", f"{process_type}.log")

    with console.status(f"[bold blue]Starting {process_type}...", spinner="dots"):
        if production:            
            venv_path = sys.prefix
            gunicorn_path = os.path.join(venv_path, "bin", "gunicorn")
            uvicorn_path = os.path.join(venv_path, "Scripts", "uvicorn.exe")

            if platform.system() == "Windows":
                server_path = uvicorn_path
            else:
                server_path = gunicorn_path

            cmd = [server_path, f"{process_type}.main:app", "--workers", WORKERS]

            if server_path == uvicorn_path:
                cmd.extend(["--host", HOST, "--port", PORT])
            else:
                cmd.extend(["--bind", f"{HOST}:{PORT}"])

            if process_type == "api" and server_path == gunicorn_path:
                cmd.extend(["--worker-class", "uvicorn.workers.UvicornWorker"])
            
            if SSL_CERT and SSL_KEY:
                cmd.extend(["--certfile", SSL_CERT, "--keyfile", SSL_KEY])
        else:
            # Development mode using Python module directly
            cmd = [sys.executable, "-m", f"{process_type}.main"]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )

    if no_logs:
        log_thread = threading.Thread(
            target=log_output, 
            args=(process, sys.stdout, process_type, success_event, production)
        )
    else:
        # Use rotating log file instead of a simple file
        log_file = RotatingLogFile(default_log_path, max_size=max_log_size * 1024 * 1024)
        log_thread = threading.Thread(
            target=log_output, 
            args=(process, log_file, process_type, success_event, production)
        )

    log_thread.start()

    # Wait for success signal or timeout
    if not success_event.wait(timeout):
        process.kill()
        log_thread.join()
        console.print(f"[bold red]Error:[/] {process_type} failed to start within {timeout} seconds")
        raise TimeoutError(f"{process_type} failed to start within {timeout} seconds")
    
    return process, log_thread, log_file if not no_logs else None

def log_output(process, log_file, process_type, success_event, production=False):
    urls = []
    version = None
    
    try:
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
            
            if process_type == "api":
                if production and platform.system() != "Windows":
                    # Production mode patterns (Gunicorn)
                    if "AI SDK Version" in line:
                        version_match = re.search(r"Version:\s(.*)", line)
                        if version_match:
                            version = version_match.group(1)
                            if urls and not success_event.is_set():
                                print_status("api", urls, version)
                                success_event.set()
                    
                    if "Listening at:" in line:
                        match = re.search(r"Listening at: (https?://[\w.:]+)", line)
                        if match:
                            urls.append(match.group(1))
                            if version is not None:
                                print_status("api", urls, version)
                                success_event.set()
                            elif not success_event.is_set():
                                def delayed_status():
                                    if not success_event.is_set():
                                        print_status("api", urls, version)
                                        success_event.set()
                                t = threading.Timer(5.0, delayed_status)
                                t.daemon = True
                                t.start()
                else:
                    # Development mode patterns (Uvicorn)
                    if "AI SDK Version" in line:
                        version_match = re.search(r"Version:\s(.*)", line)
                        if version_match:
                            version = version_match.group(1)
                            if urls and not success_event.is_set():
                                print_status("api", urls, version)
                                success_event.set()
                    
                    if "Uvicorn running on" in line:
                        match = re.search(r"Uvicorn running on (https?://[\w.:]+)", line)
                        if match:
                            urls.append(match.group(1))
                            if version is not None:
                                print_status("api", urls, version)
                                success_event.set()
                            elif not success_event.is_set():
                                def delayed_status():
                                    if not success_event.is_set():
                                        print_status("api", urls, version)
                                        success_event.set()
                                t = threading.Timer(5.0, delayed_status)
                                t.daemon = True
                                t.start()
            
            elif process_type == "sample_chatbot":
                if production and platform.system() != "Windows":
                    # Production mode patterns (Gunicorn)
                    if "Listening at:" in line:
                        match = re.search(r"Listening at: (https?://[\w.:]+)", line)
                        if match:
                            urls.append(match.group(1))
                            if not success_event.is_set():
                                print_status("sample_chatbot", urls)
                                success_event.set()
                elif production and platform.system() == "Windows":
                    if "running on" in line:
                        match = re.search(r"running on (https?://[\w.:]+)", line)
                        if match:
                            urls.append(match.group(1))
                            if not success_event.is_set():
                                print_status("sample_chatbot", urls)
                                success_event.set()
                else:
                    # Development mode patterns
                    if "Running on" in line:
                        match = re.search(r"Running on (https?://[\w.:]+)", line)
                        if match:
                            urls.append(match.group(1))
                            if not success_event.is_set():
                                print_status("sample_chatbot", urls)
                                success_event.set()
                    
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            console.print("[yellow]Warning:[/] Log file was closed before all output was written.")
        else:
            raise

def sync_vdp(url, server_id = 1, dc_user = 'admin', dc_password = 'admin'):
    endpoint = "/denodo-data-catalog/public/api/element-management/VIEWS/synchronize"
    full_url = f"{url}{endpoint}?serverId={server_id}"
    
    payload = {
        "proceedWithConflicts": "SERVER",
    }

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(full_url, headers=headers, json=payload, auth=(dc_user, dc_password))
        response.raise_for_status()
        console.print("[bold green]✓[/] Database synchronization successful")
        return True
    except Exception as e:
        console.print(f"[bold red]Error:[/] Error synchronizing database: {e}")
        return False

def load_demo_data(host, grpc_port, catalog_port, server_id, dc_user, dc_password):
    """Load demo data with visual feedback"""
    console.print(Panel(
        "[bold blue]Demo Data Loading",
        border_style="blue",
        width=60
    ))
    
    from adbc_driver_flightsql.dbapi import connect
    console.print("[bold blue]Loading demo banking data into samples_bank VDB...")
    success = False
    try:
        with console.status("[bold blue]Loading demo data...", spinner="dots"):
            conn = connect(
                f"grpc://{host}:{grpc_port}",
                db_kwargs={
                    "username": dc_user,
                    "password": dc_password,
                    "adbc.flight.sql.rpc.call_header.database": 'admin',
                    "adbc.flight.sql.rpc.call_header.timePrecision": 'milliseconds',
                },
                autocommit=True
            )
            
            with conn.cursor() as cur:
                cur.execute("METADATA ENCRYPTION PASSWORD 'denodo';")
                cur.fetchall()
                
                with open('sample_chatbot/sample_data/structured/samples_bank.vql', 'r', encoding='utf-8') as f:
                    sql_statements = f.read().split(';')
                    for statement in sql_statements:
                        if statement.strip():
                            cur.execute(statement.strip() + ";")
                            cur.fetchall()
                            
                cur.execute("METADATA ENCRYPTION DEFAULT;")
                cur.fetchall()
            
        console.print("[bold green]✓[/] Demo data loaded successfully!")
        success = True
    except Exception as e:
        console.print(f"[bold red]Error:[/] Failed to load demo data: {str(e)}")
        return False

    if success:
        with console.status("[bold blue]Synchronizing database...", spinner="dots"):
            catalog_url = f"http://{host}:{catalog_port}"
            if not sync_vdp(catalog_url, server_id, dc_user, dc_password):
                console.print("[bold yellow]Warning:[/] Data Catalog synchronization failed.")
                return False
            console.print("[bold green]✓[/] Database synchronized successfully!")
    
    return success

if __name__ == "__main__":
    args = parse_arguments()
    processes = []
    log_threads = []
    log_files = []

    print_header()
    
    # Show production mode warning if enabled
    if args.production:
        console.print(Panel(
            "[bold yellow]Production mode uses Gunicorn ASGI server on UNIX systems and Uvicorn ASGI server on Windows.",
            border_style="yellow",
            width=60
        ))

    try:
        if args.load_demo:
            if not load_demo_data(args.host, args.grpc_port, args.dc_port, args.server_id, args.dc_user, args.dc_password):
                console.print("[bold red]ERROR:[/] Failed to load demo data. Please check the logs for more information.")
                sys.exit(1)

        if args.mode in ["api", "both"]:
            api_process, api_log_thread, api_log_file = run_process("api", args.timeout, args.no_logs, args.max_log_size, args.production)
            processes.append(("API", api_process))
            log_threads.append(api_log_thread)
            if api_log_file:
                log_files.append(api_log_file)
        
        if args.mode in ["sample_chatbot", "both"]:
            chatbot_process, chatbot_log_thread, chatbot_log_file = run_process("sample_chatbot", args.timeout, args.no_logs, args.max_log_size, args.production)
            processes.append(("Chatbot", chatbot_process))
            log_threads.append(chatbot_log_thread)
            if chatbot_log_file:
                log_files.append(chatbot_log_file)

        # Wait for processes to complete or Ctrl+C
        while any(p[1].poll() is None for p in processes):
            for name, process in processes:
                if process.poll() is not None:
                    console.print(f"[yellow]{name} process ended.[/]")
            
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Received interrupt signal. Shutting down gracefully...[/]")
        for name, process in processes:
            if process.poll() is None:
                console.print(f"[yellow]Stopping {name} process...[/]")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    console.print(f"[red]Force killing {name} process...[/]")
                    process.kill()
        
    except TimeoutError as e:
        console.print(f"[bold red]Error:[/] {str(e)}")

    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)
    
    finally:
        # Cleanup
        for thread in log_threads:
            thread.join()
        for file in log_files:
            if hasattr(file, 'close'):
                file.close()
        
        console.print("[bold green]Shutdown complete.[/]")
        sys.exit(0)