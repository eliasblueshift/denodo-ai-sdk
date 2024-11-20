import sys
import subprocess
import time
import re
import threading
import argparse
import os
import requests

# Set default timeout to 180 seconds
DEFAULT_TIMEOUT = 180

def parse_arguments():
    parser = argparse.ArgumentParser(description="Run API and/or chatbot with configurable timeout.")
    parser.add_argument("mode", choices=["api", "chatbot", "both"], help="Mode to run: api, chatbot, or both")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout in seconds (default: 180)")
    parser.add_argument("--load-demo", action="store_true", help="Load demo data before starting (only works with 'both' mode)")
    parser.add_argument("--host", default="localhost", help="GRPC host (default: localhost)")
    parser.add_argument("--grpc-port", type=int, default=9994, help="GRPC port (default: 9994)")
    parser.add_argument("--dc-port", type=int, default=9090, help="Data Catalog port (default: 9090)")
    parser.add_argument("--server-id", type=int, default=1, help="Server ID (default: 1)")
    parser.add_argument("--no-logs", action="store_true", help="Output logs to console instead of files")
    return parser.parse_args()

def ensure_logs_directory():
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    return logs_dir

def empty_file(file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    open(file_path, 'w').close()

def run_api():
    log_path = os.path.join("logs", "api.log")
    with open(log_path, "w") as log_file:
        subprocess.run([sys.executable, "-m", "api.main"], stdout=log_file, stderr=subprocess.STDOUT)

def run_chatbot(log_file_path=None, no_logs=False):
    if no_logs:
        process = subprocess.Popen([sys.executable, "-m", "sample_chatbot.main"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return process, None
    else:
        if log_file_path is None:
            log_file_path = os.path.join("logs", "sample_chatbot.log")
        empty_file(log_file_path)
        process = subprocess.Popen([sys.executable, "-m", "sample_chatbot.main"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return process, log_file_path

def wait_for_chatbot(process, log_file_path, timeout=DEFAULT_TIMEOUT, no_logs=False):
    start_time = time.time()
    if no_logs:
        while time.time() - start_time < timeout:
            line = process.stdout.readline().strip()
            if line:
                print(line)
                if "Running on" in line:
                    match = re.search(r"Running on (http://[\d.:]+)", line)
                    if match:
                        print(f"Chatbot is running on: {match.group(1)}")
                        return True
    else:
        with open(log_file_path, "a") as log_file:
            while time.time() - start_time < timeout:
                line = process.stdout.readline().strip()
                if line:
                    log_file.write(line + '\n')
                    log_file.flush()
                    if "Running on" in line:
                        match = re.search(r"Running on (http://[\d.:]+)", line)
                        if match:
                            print(f"Chatbot is running on: {match.group(1)}")
                            return True
    return False

def run_api_with_output(no_logs=False):
    if no_logs:
        process = subprocess.Popen([sys.executable, "-m", "api.main"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log_thread = threading.Thread(target=log_output, args=(process, sys.stdout))
        log_thread.start()
        return process, log_thread, None
    else:
        log_file_path = os.path.join("logs", "api.log")
        empty_file(log_file_path)
        log_file = open(log_file_path, "w")
        process = subprocess.Popen([sys.executable, "-m", "api.main"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log_thread = threading.Thread(target=log_output, args=(process, log_file))
        log_thread.start()
        return process, log_thread, log_file

def log_output(process, log_file):
    try:
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
            if "Uvicorn running on" in line:
                match = re.search(r"Uvicorn running on (https?://[\d.:]+)", line)
                if match:
                    print(f"API is running on: {match.group(1)}")
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            print("Warning: Log file was closed before all output was written.")
        else:
            raise

def sync_vdp(url, server_id=1):
    endpoint = f"/denodo-data-catalog/public/api/element-management/VIEWS/synchronize"
    full_url = f"{url}{endpoint}?serverId={server_id}"
    
    payload = {
        "proceedWithConflicts": "SERVER",
    }

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(full_url, headers=headers, json=payload, auth=('admin', 'admin'))
        response.raise_for_status()
        print("Database synchronization successful")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error synchronizing database: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status code: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        print(f"Request URL: {full_url}")
        print(f"Request payload: {payload}")
        return False

def load_demo_data(host, grpc_port, catalog_port, server_id):
    from adbc_driver_flightsql.dbapi import connect
    print("Initializing demo data...")
    success = False
    try:
        conn = connect(
            f"grpc://{host}:{grpc_port}",
            db_kwargs={
                "username": 'admin',
                "password": 'admin',
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
            
        print("Demo data loaded successfully!")
        success = True
    except Exception as e:
        print(f"Error loading demo data: {str(e)}")
        return False

    if success:
        # Synchronize the database after loading
        catalog_url = f"http://{host}:{catalog_port}"
        if not sync_vdp(catalog_url, server_id):
            print("Warning: Database synchronization failed")
            return False
    
    return success

if __name__ == "__main__":
    args = parse_arguments()
    mode = args.mode.lower()
    CHATBOT_TIMEOUT = args.timeout

    # Validate --load-demo usage
    if args.load_demo and mode != "both":
        print("Error: --load-demo can only be used with 'both' mode")
        sys.exit(1)

    # Only create logs directory if we're using logs
    if not args.no_logs:
        ensure_logs_directory()

    # Handle demo data loading if requested
    if args.load_demo:
        if not load_demo_data(args.host, args.grpc_port, args.dc_port, args.server_id):
            print("Failed to load demo data. Exiting...")
            sys.exit(1)

    if mode == "api":
        api_process, log_thread, log_file = run_api_with_output(args.no_logs)
        api_process.wait()
        log_thread.join()
        if log_file:
            log_file.close()
    elif mode == "chatbot":
        print(f"Attempting to run the chatbot, timeout is {CHATBOT_TIMEOUT} seconds")
        process, log_file = run_chatbot(no_logs=args.no_logs)
        if not wait_for_chatbot(process, log_file, timeout=CHATBOT_TIMEOUT, no_logs=args.no_logs):
            print(f"Error: Chatbot failed to start within {CHATBOT_TIMEOUT} seconds.")
            process.kill()
            sys.exit(1)
        process.wait()
        if log_file:  # Only close if we're using a log file
            log_file.close()
    elif mode == "both":
        api_process, log_thread, api_log_file = run_api_with_output(args.no_logs)
        print("Waiting for API to initialize before running the chatbot...")
        time.sleep(5)
        print(f"Attempting to run the chatbot, timeout is {CHATBOT_TIMEOUT} seconds")
        chatbot_process, chatbot_log_path = run_chatbot(no_logs=args.no_logs)
        
        chatbot_started = wait_for_chatbot(chatbot_process, chatbot_log_path, timeout=CHATBOT_TIMEOUT, no_logs=args.no_logs)
        
        if not chatbot_started:
            print(f"Error: Chatbot failed to start within {CHATBOT_TIMEOUT} seconds.")
            chatbot_process.kill()
            api_process.terminate()
            log_thread.join()
        else:
            print("Chatbot started successfully. Please open the chatbot in your browser.")
            if args.no_logs:
                for line in chatbot_process.stdout:
                    print(line.strip())
            else:
                with open(chatbot_log_path, "a") as chatbot_log_file:
                    for line in chatbot_process.stdout:
                        chatbot_log_file.write(line)
                        chatbot_log_file.flush()
            chatbot_process.wait()
            print("Chatbot process finished. Terminating API...")
            api_process.terminate()
            log_thread.join()
        
        if api_log_file:  # Only close if we're using a log file
            print("Closing log files...")
            api_log_file.close()
        print("API and the sample chatbot have finished running.")
    else:
        print("Invalid mode. Use 'api', 'chatbot', or 'both'.")
        sys.exit(1)