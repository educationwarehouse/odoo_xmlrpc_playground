#!/usr/bin/env python3
"""
Odoo Web Search Server
=====================

A web-based interface for the Odoo text search functionality.
Provides a clean, modern web UI that works great on Windows and in browser panels.

Features:
- Modern responsive web interface
- Settings management through UI
- Search history with localStorage
- Dark/light theme toggle
- File downloads through browser
- Perfect for browser panels (Vivaldi, Firefox)

Usage:
    python web_search_server.py
    
Then open: http://localhost:8080

Author: Based on text_search.py
Date: December 2024
"""

import os
import json
import threading
import webbrowser
import subprocess
import tempfile
import uuid
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import base64
import mimetypes
import time
import warnings

# Suppress the pkg_resources deprecation warning from odoo_rpc_client globally
warnings.filterwarnings("ignore", 
                      message="pkg_resources is deprecated as an API.*",
                      category=UserWarning)

# Import ConfigManager from odoo_base
try:
    from .odoo_base import ConfigManager, OdooBase
except ImportError:
    try:
        from edwh_odoo_plugin.odoo_base import ConfigManager, OdooBase
    except ImportError:
        from odoo_base import ConfigManager, OdooBase


class WebSearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the web search interface"""
    
    # Class-level storage for active searches
    _active_searches = {}
    _search_lock = threading.Lock()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/' or path == '/index.html':
            self.serve_main_page()
        elif path == '/api/search':
            self.handle_search_api(parsed_path.query)
        elif path == '/api/search/status':
            self.handle_search_status_api(parsed_path.query)
        elif path == '/api/download':
            self.handle_download_api(parsed_path.query)
        elif path == '/api/settings':
            self.handle_settings_get()
        elif path.startswith('/static/'):
            self.serve_static_file(path)
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/api/settings':
            self.handle_settings_post()
        else:
            self.send_error(404, "Not Found")
    
    def serve_main_page(self):
        """Serve the main HTML page"""
        html_content = self.get_main_html()
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html_content.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def handle_search_api(self, query_string):
        """Handle search API requests using background processes"""
        try:
            params = parse_qs(query_string)
            
            # Extract search parameters
            search_term = params.get('q', [''])[0]
            since = params.get('since', [''])[0] or None
            search_type = params.get('type', ['all'])[0]
            include_descriptions = params.get('descriptions', ['true'])[0].lower() == 'true'
            include_logs = params.get('logs', ['true'])[0].lower() == 'true'
            include_files = params.get('files', ['true'])[0].lower() == 'true'
            file_types = params.get('file_types', [''])[0].split(',') if params.get('file_types', [''])[0] else None
            limit = int(params.get('limit', ['0'])[0]) or None
            
            if not search_term:
                self.send_json_response({'error': 'Search term is required'}, 400)
                return

            # Generate unique search ID
            search_id = str(uuid.uuid4())
            
            # Log search request to console
            print(f"🔍 Web search request [{search_id[:8]}]: '{search_term}' (type: {search_type}, since: {since})")

            # Start background search process
            search_thread = threading.Thread(
                target=self._execute_search_process,
                args=(search_id, search_term, since, search_type, include_descriptions, 
                      include_logs, include_files, file_types, limit)
            )
            search_thread.daemon = True
            search_thread.start()
            
            # Store search info
            with WebSearchHandler._search_lock:
                WebSearchHandler._active_searches[search_id] = {
                    'status': 'running',
                    'started_at': time.time(),
                    'search_term': search_term,
                    'thread': search_thread
                }
            
            # Return search ID for polling
            self.send_json_response({
                'success': True,
                'search_id': search_id,
                'status': 'started',
                'message': 'Search started in background'
            })
            
        except Exception as e:
            import traceback
            error_msg = f"Search error: {str(e)}"
            traceback_msg = traceback.format_exc()

            # Print to console
            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)
    
    def _execute_search_process(self, search_id, search_term, since, search_type, 
                               include_descriptions, include_logs, include_files, 
                               file_types, limit):
        """Execute search in a separate Python process"""
        try:
            # Create temporary files for communication
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as input_file:
                input_data = {
                    'search_term': search_term,
                    'since': since,
                    'search_type': search_type,
                    'include_descriptions': include_descriptions,
                    'include_logs': include_logs,
                    'include_files': include_files,
                    'file_types': file_types,
                    'limit': limit
                }
                json.dump(input_data, input_file)
                input_file_path = input_file.name
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as output_file:
                output_file_path = output_file.name
            
            # Execute search in separate process
            cmd = [
                sys.executable, '-c', f'''
import sys
import json
import os
import threading
import concurrent.futures
from datetime import datetime

# Add both current directory and src directory to path
sys.path.insert(0, "{os.getcwd()}")
sys.path.insert(0, os.path.join("{os.getcwd()}", "src"))

try:
    from edwh_odoo_plugin.text_search import OdooTextSearch
except ImportError:
    try:
        from src.edwh_odoo_plugin.text_search import OdooTextSearch
    except ImportError:
        from text_search import OdooTextSearch

# Read input
with open("{input_file_path}", "r") as f:
    params = json.load(f)

try:
    # Create searcher instance
    searcher = OdooTextSearch(verbose=True)
    
    # Parse time reference
    since_date = None
    if params["since"]:
        since_date = searcher._parse_time_reference(params["since"])
    
    # Build user and message caches upfront
    searcher._build_user_cache()
    searcher._build_message_cache()
    
    # Initialize results
    results = {{
        "projects": [],
        "tasks": [],
        "messages": [],
        "files": []
    }}
    
    # Define search functions for parallel execution
    def search_projects():
        try:
            if params["search_type"] in ["all", "projects"]:
                result = searcher.search_projects(
                    params["search_term"], 
                    since_date, 
                    params["include_descriptions"], 
                    params["limit"]
                )
                print(f"DEBUG: Projects search returned {{len(result)}} results")
                return result
            else:
                print(f"DEBUG: Skipping projects search (type: {{params['search_type']}})")
                return []
        except Exception as e:
            print(f"ERROR in search_projects: {{e}}")
            return []
    
    def search_tasks():
        try:
            if params["search_type"] in ["all", "tasks"]:
                result = searcher.search_tasks(
                    params["search_term"], 
                    since_date, 
                    params["include_descriptions"], 
                    None, 
                    params["limit"]
                )
                print(f"DEBUG: Tasks search returned {{len(result)}} results")
                return result
            else:
                print(f"DEBUG: Skipping tasks search (type: {{params['search_type']}})")
                return []
        except Exception as e:
            print(f"ERROR in search_tasks: {{e}}")
            return []
    
    def search_messages():
        try:
            if params["include_logs"] and params["search_type"] in ["all", "logs"]:
                model_type = "both" if params["search_type"] == "all" else params["search_type"]
                result = searcher.search_messages(
                    params["search_term"], 
                    since_date, 
                    model_type, 
                    params["limit"]
                )
                print(f"DEBUG: Messages search returned {{len(result)}} results")
                return result
            else:
                print(f"DEBUG: Skipping messages search (type: {{params['search_type']}}, logs: {{params['include_logs']}})")
                return []
        except Exception as e:
            print(f"ERROR in search_messages: {{e}}")
            return []
    
    def search_files():
        try:
            if params["include_files"] or params["search_type"] == "files":
                model_type = "all" if params["search_type"] in ["all", "files"] else params["search_type"]
                result = searcher.search_files(
                    params["search_term"], 
                    since_date, 
                    params["file_types"], 
                    model_type, 
                    params["limit"]
                )
                print(f"DEBUG: Files search returned {{len(result)}} results")
                return result
            else:
                print(f"DEBUG: Skipping files search (type: {{params['search_type']}}, files: {{params['include_files']}})")
                return []
        except Exception as e:
            print(f"ERROR in search_files: {{e}}")
            return []
    
    # Execute searches sequentially to avoid threading issues in subprocess
    print(f"DEBUG: Starting sequential searches...")
    
    # Search projects
    try:
        print(f"DEBUG: Starting projects search...")
        results["projects"] = search_projects()
        print(f"✅ Projects search completed: {{len(results['projects'])}} results")
    except Exception as exc:
        print(f"❌ Projects search failed: {{exc}}")
        import traceback
        print(f"   Traceback: {{traceback.format_exc()}}")
        results["projects"] = []
    
    # Search tasks
    try:
        print(f"DEBUG: Starting tasks search...")
        results["tasks"] = search_tasks()
        print(f"✅ Tasks search completed: {{len(results['tasks'])}} results")
    except Exception as exc:
        print(f"❌ Tasks search failed: {{exc}}")
        import traceback
        print(f"   Traceback: {{traceback.format_exc()}}")
        results["tasks"] = []
    
    # Search messages
    try:
        print(f"DEBUG: Starting messages search...")
        results["messages"] = search_messages()
        print(f"✅ Messages search completed: {{len(results['messages'])}} results")
    except Exception as exc:
        print(f"❌ Messages search failed: {{exc}}")
        import traceback
        print(f"   Traceback: {{traceback.format_exc()}}")
        results["messages"] = []
    
    # Search files
    try:
        print(f"DEBUG: Starting files search...")
        results["files"] = search_files()
        print(f"✅ Files search completed: {{len(results['files'])}} results")
    except Exception as exc:
        print(f"❌ Files search failed: {{exc}}")
        import traceback
        print(f"   Traceback: {{traceback.format_exc()}}")
        results["files"] = []
    
    print(f"DEBUG: Final results summary:")
    for category, items in results.items():
        print(f"  {{category}}: {{len(items)}} items")
    
    # Add URLs to results
    for project in results.get("projects", []):
        project["url"] = searcher.get_project_url(project["id"])
    
    for task in results.get("tasks", []):
        task["url"] = searcher.get_task_url(task["id"])
        if task.get("project_id"):
            task["project_url"] = searcher.get_project_url(task["project_id"])
    
    for message in results.get("messages", []):
        message["url"] = searcher.get_message_url(message["id"])
        if message.get("model") == "project.project" and message.get("res_id"):
            message["related_url"] = searcher.get_project_url(message["res_id"])
        elif message.get("model") == "project.task" and message.get("res_id"):
            message["related_url"] = searcher.get_task_url(message["res_id"])
    
    for file in results.get("files", []):
        file["url"] = searcher.get_file_url(file["id"])
        file["download_url"] = "/api/download?id=" + str(file["id"])
        if file.get("related_type") == "Project" and file.get("related_id"):
            file["related_url"] = searcher.get_project_url(file["related_id"])
        elif file.get("related_type") == "Task" and file.get("related_id"):
            file["related_url"] = searcher.get_task_url(file["related_id"])
            if file.get("project_id"):
                file["project_url"] = searcher.get_project_url(file["project_id"])
    
    # Make results JSON-safe
    def convert_value(value):
        if value is None:
            return None
        elif hasattr(value, "__class__") and "odoo" in str(value.__class__).lower():
            if hasattr(value, "id"):
                return value.id
            else:
                return str(value)
        elif isinstance(value, (str, int, float, bool)):
            return value
        elif isinstance(value, (list, tuple)):
            return [convert_value(item) for item in value]
        elif isinstance(value, dict):
            return {{k: convert_value(v) for k, v in value.items()}}
        else:
            return str(value)
    
    json_safe_results = {{}}
    for category, items in results.items():
        if isinstance(items, list):
            json_safe_results[category] = []
            for item in items:
                if isinstance(item, dict):
                    json_safe_item = {{k: convert_value(v) for k, v in item.items()}}
                    json_safe_results[category].append(json_safe_item)
                else:
                    json_safe_results[category].append(convert_value(item))
        else:
            json_safe_results[category] = convert_value(items)
    
    # Calculate totals
    total_results = sum(len(json_safe_results.get(key, [])) for key in ["projects", "tasks", "messages", "files"])
    
    # Write results
    output_data = {{
        "success": True,
        "results": json_safe_results,
        "total": total_results,
        "search_params": params
    }}
    
    with open("{output_file_path}", "w") as f:
        json.dump(output_data, f)

except Exception as e:
    import traceback
    error_data = {{
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }}
    
    with open("{output_file_path}", "w") as f:
        json.dump(error_data, f)
'''
            ]
            
            # Run the process
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=os.getcwd())  # 5 minute timeout
            
            # Read results
            try:
                with open(output_file_path, 'r') as f:
                    results = json.load(f)
            except Exception as read_error:
                results = {
                    'success': False,
                    'error': f'Failed to read search results: {str(read_error)}',
                    'process_stdout': process.stdout,
                    'process_stderr': process.stderr,
                    'process_returncode': process.returncode
                }
            
            # Update search status
            with WebSearchHandler._search_lock:
                if search_id in WebSearchHandler._active_searches:
                    WebSearchHandler._active_searches[search_id].update({
                        'status': 'completed',
                        'completed_at': time.time(),
                        'results': results
                    })
            
            # Log process output for debugging
            if process.stdout:
                print(f"📝 Process output [{search_id[:8]}]: {process.stdout[:200]}...")
            if process.stderr:
                print(f"⚠️ Process errors [{search_id[:8]}]: {process.stderr[:200]}...")
            if process.returncode != 0:
                print(f"⚠️ Process exit code [{search_id[:8]}]: {process.returncode}")
            
            # Cleanup temp files
            try:
                os.unlink(input_file_path)
                os.unlink(output_file_path)
            except Exception as cleanup_error:
                print(f"⚠️ Cleanup error [{search_id[:8]}]: {cleanup_error}")
                
            if results.get('success'):
                print(f"✅ Search [{search_id[:8]}] completed: {results.get('total', 0)} results")
            else:
                print(f"❌ Search [{search_id[:8]}] failed: {results.get('error', 'Unknown error')}")
            
        except subprocess.TimeoutExpired:
            with WebSearchHandler._search_lock:
                if search_id in WebSearchHandler._active_searches:
                    WebSearchHandler._active_searches[search_id].update({
                        'status': 'timeout',
                        'completed_at': time.time(),
                        'results': {'success': False, 'error': 'Search timed out after 5 minutes'}
                    })
            print(f"⏰ Search [{search_id[:8]}] timed out")
            
        except Exception as e:
            with WebSearchHandler._search_lock:
                if search_id in WebSearchHandler._active_searches:
                    WebSearchHandler._active_searches[search_id].update({
                        'status': 'error',
                        'completed_at': time.time(),
                        'results': {'success': False, 'error': str(e)}
                    })
            print(f"❌ Search [{search_id[:8]}] failed: {e}")
    
    def handle_search_status_api(self, query_string):
        """Handle search status polling requests"""
        try:
            params = parse_qs(query_string)
            search_id = params.get('id', [''])[0]
            
            if not search_id:
                self.send_json_response({'error': 'Search ID is required'}, 400)
                return
            
            with WebSearchHandler._search_lock:
                if search_id not in WebSearchHandler._active_searches:
                    self.send_json_response({'error': 'Search not found'}, 404)
                    return
                
                search_info = WebSearchHandler._active_searches[search_id]
                
                response = {
                    'search_id': search_id,
                    'status': search_info['status'],
                    'search_term': search_info['search_term'],
                    'started_at': search_info['started_at']
                }
                
                if search_info['status'] in ['completed', 'error', 'timeout']:
                    response['completed_at'] = search_info.get('completed_at')
                    response['results'] = search_info.get('results', {})
                    
                    # Clean up completed searches after returning results
                    if search_info['status'] == 'completed':
                        # Keep for a short while in case of retry, then clean up in background
                        threading.Timer(30.0, lambda: WebSearchHandler._active_searches.pop(search_id, None)).start()
                
                self.send_json_response(response)
                
        except Exception as e:
            import traceback
            error_msg = f"Status check error: {str(e)}"
            traceback_msg = traceback.format_exc()

            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)
    
    def handle_download_api(self, query_string):
        """Handle file download API requests"""
        try:
            params = parse_qs(query_string)
            file_id = params.get('id', [''])[0]
            
            if not file_id:
                self.send_json_response({'error': 'File ID is required'}, 400)
                return
            
            # Create temporary base connection for download (downloads are infrequent)
            try:
                odoo_base = OdooBase(verbose=False)
            except Exception as e:
                self.send_json_response({'error': f'Failed to connect to Odoo: {str(e)}'}, 500)
                return
            
            # Get file info first
            attachment_records = odoo_base.attachments.search_records([('id', '=', int(file_id))])
            
            if not attachment_records:
                self.send_json_response({'error': 'File not found'}, 404)
                return
            
            attachment = attachment_records[0]
            file_name = getattr(attachment, 'name', f'file_{file_id}')
            
            # Get file data using shared method
            if not hasattr(attachment, 'datas'):
                self.send_json_response({'error': 'No data available for this file'}, 404)
                return
            
            file_data_b64 = attachment.datas
            if hasattr(file_data_b64, '__call__'):
                file_data_b64 = file_data_b64()
            
            if not file_data_b64:
                self.send_json_response({'error': 'File data is empty'}, 404)
                return
            
            # Decode base64 data
            file_data = base64.b64decode(file_data_b64)
            
            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(file_name)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Send file
            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Disposition', f'attachment; filename="{file_name}"')
            self.send_header('Content-Length', str(len(file_data)))
            self.end_headers()
            self.wfile.write(file_data)
            
        except Exception as e:
            import traceback
            error_msg = f"Search error: {str(e)}"
            traceback_msg = traceback.format_exc()

            # Print to console
            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)
    
    def handle_settings_get(self):
        """Handle GET request for settings"""
        try:
            # Use ConfigManager to load current configuration
            try:
                config = ConfigManager.load_config(verbose=False)
                settings = {
                    'host': config.get('host', ''),
                    'database': config.get('database', ''),
                    'user': config.get('user', ''),
                    'password': '***' if config.get('password') else '',
                    'port': config.get('port', 443),
                    'protocol': config.get('protocol', 'xml-rpcs')
                }
            except (FileNotFoundError, ValueError):
                # No config file exists yet
                settings = {
                    'host': '',
                    'database': '',
                    'user': '',
                    'password': '',
                    'port': 443,
                    'protocol': 'xml-rpcs'
                }
            
            self.send_json_response({'success': True, 'settings': settings})
        except Exception as e:
            self.send_json_response({'error': str(e)}, 500)
    
    def handle_settings_post(self):
        """Handle POST request for settings"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            # Get the config file path using ConfigManager
            config_path = ConfigManager.get_config_path()
            
            # Ensure the config directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Read existing config if it exists
            env_lines = []
            if config_path.exists():
                with open(config_path, 'r') as f:
                    env_lines = f.readlines()
            
            # Update or add settings
            settings_map = {
                'ODOO_HOST': data.get('host', ''),
                'ODOO_DATABASE': data.get('database', ''),
                'ODOO_USER': data.get('user', ''),
                'ODOO_PORT': data.get('port', '443'),
                'ODOO_PROTOCOL': data.get('protocol', 'xml-rpcs')
            }
            
            # Only update password if provided
            if data.get('password') and data.get('password') != '***':
                settings_map['ODOO_PASSWORD'] = data.get('password', '')
            
            # Update existing lines or prepare new ones
            updated_keys = set()
            for i, line in enumerate(env_lines):
                for key, value in settings_map.items():
                    if line.startswith(f'{key}='):
                        if key == 'ODOO_PASSWORD' and value == '':
                            continue  # Don't update password if empty
                        env_lines[i] = f'{key}={value}\n'
                        updated_keys.add(key)
                        break
            
            # Add new settings that weren't found
            for key, value in settings_map.items():
                if key not in updated_keys and value:
                    env_lines.append(f'{key}={value}\n')
            
            # Write back to config file
            with open(config_path, 'w') as f:
                f.writelines(env_lines)
            
            # Reload environment variables
            from dotenv import load_dotenv
            load_dotenv(config_path, override=True)
            
            self.send_json_response({'success': True, 'message': 'Settings updated successfully'})
            
        except Exception as e:
            self.send_json_response({'error': str(e)}, 500)
    
    def make_results_json_safe(self, results):
        """Convert all results to JSON-serializable format"""
        def convert_value(value):
            """Convert a single value to JSON-safe format"""
            if value is None:
                return None
            elif hasattr(value, '__class__') and 'odoo' in str(value.__class__).lower():
                # This is likely an Odoo Record object
                if hasattr(value, 'id'):
                    return value.id
                else:
                    return str(value)
            elif isinstance(value, (str, int, float, bool)):
                return value
            elif isinstance(value, (list, tuple)):
                return [convert_value(item) for item in value]
            elif isinstance(value, dict):
                return {k: convert_value(v) for k, v in value.items()}
            else:
                return str(value)
        
        json_safe_results = {}
        for category, items in results.items():
            if isinstance(items, list):
                json_safe_results[category] = []
                for item in items:
                    if isinstance(item, dict):
                        json_safe_item = {k: convert_value(v) for k, v in item.items()}
                        json_safe_results[category].append(json_safe_item)
                    else:
                        json_safe_results[category].append(convert_value(item))
            else:
                json_safe_results[category] = convert_value(items)
        
        return json_safe_results

    
    def send_json_response(self, data, status_code=200):
        """Send JSON response"""
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(json_data.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))
    
    def serve_static_file(self, path):
        """Serve static files (if any)"""
        self.send_error(404, "Static files not implemented")
    
    def get_main_html(self):
        """Generate the main HTML page"""
        return r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Odoo Search</title>
    <style>
        :root {
            --bg-color: #ffffff;
            --text-color: #333333;
            --border-color: #e0e0e0;
            --accent-color: #007bff;
            --success-color: #28a745;
            --warning-color: #ffc107;
            --danger-color: #dc3545;
            --card-bg: #f8f9fa;
            --input-bg: #ffffff;
            --shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        [data-theme="dark"] {
            --bg-color: #1a1a1a;
            --text-color: #e0e0e0;
            --border-color: #404040;
            --accent-color: #4dabf7;
            --success-color: #51cf66;
            --warning-color: #ffd43b;
            --danger-color: #ff6b6b;
            --card-bg: #2d2d2d;
            --input-bg: #404040;
            --shadow: 0 2px 4px rgba(0,0,0,0.3);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            transition: background-color 0.3s, color 0.3s;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid var(--border-color);
        }
        
        .header h1 {
            color: var(--accent-color);
            font-size: 2rem;
        }
        
        .header-controls {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
            text-decoration: none;
            display: inline-block;
        }
        
        .btn-primary {
            background-color: var(--accent-color);
            color: white;
        }
        
        .btn-primary:hover {
            opacity: 0.9;
            transform: translateY(-1px);
        }
        
        .btn-secondary {
            background-color: var(--card-bg);
            color: var(--text-color);
            border: 1px solid var(--border-color);
        }
        
        .btn-secondary:hover {
            background-color: var(--border-color);
        }
        
        .search-form {
            background: var(--card-bg);
            padding: 25px;
            border-radius: 12px;
            box-shadow: var(--shadow);
            margin-bottom: 30px;
        }
        
        .form-row {
            display: flex;
            gap: 15px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }
        
        .form-group {
            flex: 1;
            min-width: 200px;
        }
        
        .form-group.small {
            flex: 0 0 150px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            color: var(--text-color);
        }
        
        input, select {
            width: 100%;
            padding: 10px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background-color: var(--input-bg);
            color: var(--text-color);
            font-size: 14px;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: var(--accent-color);
            box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
        }
        
        .checkbox-group {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .checkbox-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .checkbox-item input[type="checkbox"] {
            width: auto;
        }
        
        .search-history {
            margin-top: 15px;
        }
        
        .history-item {
            display: inline-block;
            background: var(--accent-color);
            color: white;
            padding: 4px 8px;
            margin: 2px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            transition: opacity 0.3s;
            position: relative;
        }
        
        .history-item:hover {
            opacity: 0.8;
        }
        
        .history-item small {
            opacity: 0.8;
            font-size: 10px;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: var(--accent-color);
        }
        
        .loading::after {
            content: '';
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid var(--accent-color);
            border-radius: 50%;
            border-top-color: transparent;
            animation: spin 1s linear infinite;
            margin-left: 10px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .progress-dots {
            display: inline-block;
            margin-left: 10px;
        }
        
        .progress-dots span {
            animation: blink 1.4s infinite both;
        }
        
        .progress-dots span:nth-child(2) {
            animation-delay: 0.2s;
        }
        
        .progress-dots span:nth-child(3) {
            animation-delay: 0.4s;
        }
        
        @keyframes blink {
            0%, 80%, 100% {
                opacity: 0;
            }
            40% {
                opacity: 1;
            }
        }
        
        .results {
            margin-top: 30px;
        }
        
        .results-summary {
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: var(--shadow);
        }
        
        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .results-actions {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .cache-info {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.9rem;
        }
        
        .cache-age {
            color: var(--warning-color);
            font-weight: 500;
        }
        
        .refresh-btn {
            font-size: 0.8rem;
            padding: 6px 12px;
        }
        
        .refresh-btn:hover {
            background-color: var(--accent-color);
            color: white;
        }
        
        .results-stats {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        
        .stat-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: var(--bg-color);
            border-radius: 6px;
            border: 1px solid var(--border-color);
            text-decoration: none;
            color: var(--text-color);
            transition: all 0.3s;
        }
        
        .stat-item:hover {
            background: var(--accent-color);
            color: white;
            transform: translateY(-1px);
        }
        
        .result-section {
            margin-bottom: 30px;
        }
        
        .section-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 15px;
            padding: 10px 0;
            border-bottom: 1px solid var(--border-color);
        }
        
        .section-title {
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--accent-color);
        }
        
        .result-item {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: var(--shadow);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .result-item:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }
        
        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 10px;
        }
        
        .result-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        
        .result-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .result-title a {
            color: var(--accent-color);
            text-decoration: none;
        }
        
        .result-title a:hover {
            text-decoration: underline;
        }
        
        .result-meta {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 10px;
        }
        
        [data-theme="dark"] .result-meta {
            color: #aaa;
        }
        
        .meta-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .result-description {
            margin-top: 10px;
            padding: 10px;
            background: var(--bg-color);
            border-radius: 6px;
            border-left: 3px solid var(--accent-color);
            font-size: 0.9rem;
            line-height: 1.5;
        }
        
        .download-btn {
            background: var(--success-color);
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.8rem;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
        
        .download-btn:hover {
            opacity: 0.9;
        }
        
        .error {
            background: #ffe6e6;
            color: var(--danger-color);
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
            border-left: 4px solid var(--danger-color);
        }
        
        .tab-container {
            margin-bottom: 20px;
        }
        
        .tab-buttons {
            display: flex;
            gap: 2px;
            background: var(--border-color);
            border-radius: 8px;
            padding: 4px;
        }
        
        .tab-button {
            flex: 1;
            padding: 12px 20px;
            border: none;
            background: transparent;
            color: var(--text-color);
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .tab-button:hover {
            background: var(--card-bg);
        }
        
        .tab-button.active {
            background: var(--accent-color);
            color: white;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .pins-content, .settings-content {
            background: var(--card-bg);
            padding: 25px;
            border-radius: 12px;
            box-shadow: var(--shadow);
        }
        
        .pins-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .pins-actions {
            display: flex;
            gap: 10px;
        }
        
        .pins-container {
            max-height: 60vh;
            overflow-y: auto;
        }
        
        .pin-item {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            position: relative;
        }
        
        .pin-item-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }
        
        .pin-item-title {
            font-weight: 600;
            color: var(--accent-color);
        }
        
        .pin-item-title a {
            color: var(--accent-color);
            text-decoration: none;
        }
        
        .pin-item-title a:hover {
            text-decoration: underline;
        }
        
        .unpin-btn {
            background: var(--danger-color);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 12px;
            cursor: pointer;
        }
        
        .unpin-btn:hover {
            opacity: 0.8;
        }
        
        .pin-item-meta {
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 8px;
        }
        
        [data-theme="dark"] .pin-item-meta {
            color: #aaa;
        }
        
        .pin-item-description {
            font-size: 0.9rem;
            line-height: 1.4;
            color: var(--text-color);
        }
        
        .pin-btn {
            background: var(--warning-color);
            color: #333;
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 12px;
            cursor: pointer;
            margin-left: 8px;
        }
        
        .pin-btn:hover {
            opacity: 0.8;
        }
        
        .pin-btn.pinned {
            background: var(--success-color);
            color: white;
        }
        
        .theme-toggle {
            background: none;
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 8px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
        }
        
        .theme-toggle:hover {
            background: var(--card-bg);
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }
            
            .header {
                flex-direction: column;
                gap: 15px;
                text-align: center;
            }
            
            .tab-buttons {
                flex-direction: column;
            }
            
            .form-row {
                flex-direction: column;
            }
            
            .form-group.small {
                flex: 1;
            }
            
            .checkbox-group {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .results-stats {
                flex-direction: column;
            }
            
            .result-header {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .result-meta {
                flex-direction: column;
                gap: 5px;
            }
            
            .pins-header {
                flex-direction: column;
                gap: 15px;
                align-items: flex-start;
            }
            
            .pins-actions {
                flex-direction: column;
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Odoo Search</h1>
            <div class="header-controls">
                <button class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">🌓</button>
            </div>
        </div>
        
        <div class="tab-container">
            <div class="tab-buttons">
                <button class="tab-button active" onclick="switchTab('search')">🔍 Search</button>
                <button class="tab-button" onclick="switchTab('pins')">📌 Pins</button>
                <button class="tab-button" onclick="switchTab('settings')">⚙️ Settings</button>
            </div>
        </div>
        
        <div id="search-tab" class="tab-content active">
            <form class="search-form" onsubmit="performSearch(event)">
            <div class="form-row">
                <div class="form-group">
                    <label for="searchTerm">Search Term</label>
                    <input type="text" id="searchTerm" name="searchTerm" placeholder="Enter search term..." required>
                </div>
                <div class="form-group small">
                    <label for="since">Since</label>
                    <input type="text" id="since" name="since" placeholder="1 week">
                </div>
                <div class="form-group small">
                    <label for="searchType">Type</label>
                    <select id="searchType" name="searchType">
                        <option value="all">All</option>
                        <option value="projects">Projects</option>
                        <option value="tasks">Tasks</option>
                        <option value="logs">Logs</option>
                        <option value="files">Files</option>
                    </select>
                </div>
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="fileTypes">File Types (comma-separated)</label>
                    <input type="text" id="fileTypes" name="fileTypes" placeholder="pdf, docx, png">
                </div>
                <div class="form-group small">
                    <label for="limit">Limit</label>
                    <input type="number" id="limit" name="limit" placeholder="No limit">
                </div>
            </div>
            
            <div class="form-row">
                <div class="checkbox-group">
                    <div class="checkbox-item">
                        <input type="checkbox" id="includeDescriptions" name="includeDescriptions" checked>
                        <label for="includeDescriptions">Include descriptions</label>
                    </div>
                    <div class="checkbox-item">
                        <input type="checkbox" id="includeLogs" name="includeLogs" checked>
                        <label for="includeLogs">Include logs</label>
                    </div>
                    <div class="checkbox-item">
                        <input type="checkbox" id="includeFiles" name="includeFiles" checked>
                        <label for="includeFiles">Include files</label>
                    </div>
                </div>
            </div>
            
            <div class="form-row">
                <button type="submit" class="btn btn-primary">🔍 Search</button>
                <button type="button" class="btn btn-secondary" onclick="clearCache()" title="Clear cached results">
                    🗑️ Clear Cache
                </button>
                <button type="button" class="btn btn-secondary" onclick="scrollToResults()" title="Scroll to results">
                    ⬇️ Results
                </button>
            </div>
            
            <div class="search-history" id="searchHistory">
                <label>Recent searches:</label>
                <div id="historyItems"></div>
            </div>
            </form>
            
            <div id="results" class="results"></div>
        </div>
        
        <div id="pins-tab" class="tab-content">
            <div class="pins-content">
                <div class="pins-header">
                    <h2>📌 Pinned Items</h2>
                    <div class="pins-actions">
                        <button type="button" class="btn btn-secondary" onclick="clearAllPins()">🗑️ Clear All Pins</button>
                        <button type="button" class="btn btn-secondary" onclick="exportPins()">📤 Export Pins</button>
                    </div>
                </div>
                <div id="pinsContainer" class="pins-container">
                    <!-- Pinned items will be loaded here -->
                </div>
            </div>
        </div>
        
        <div id="settings-tab" class="tab-content">
            <div class="settings-content">
                <h2>⚙️ Settings</h2>
                <form onsubmit="saveSettings(event)">
                    <div class="form-group">
                        <label for="odooHost">Odoo Host</label>
                        <input type="text" id="odooHost" name="host" placeholder="your-instance.odoo.com">
                    </div>
                    <div class="form-group">
                        <label for="odooDatabase">Database</label>
                        <input type="text" id="odooDatabase" name="database" placeholder="your-database">
                    </div>
                    <div class="form-group">
                        <label for="odooUser">User</label>
                        <input type="email" id="odooUser" name="user" placeholder="user@domain.com">
                    </div>
                    <div class="form-group">
                        <label for="odooPassword">Password/API Key</label>
                        <input type="password" id="odooPassword" name="password" placeholder="Leave empty to keep current">
                    </div>
                    <div class="form-row">
                        <div class="form-group small">
                            <label for="odooPort">Port</label>
                            <input type="number" id="odooPort" name="port" placeholder="443" value="443">
                        </div>
                        <div class="form-group small">
                            <label for="odooProtocol">Protocol</label>
                            <select id="odooProtocol" name="protocol">
                                <option value="xml-rpcs">xml-rpcs (HTTPS)</option>
                                <option value="xml-rpc">xml-rpc (HTTP)</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-row">
                        <button type="submit" class="btn btn-primary">💾 Save Settings</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    
    
    <script>
        // Theme management
        function toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        }
        
        // Load saved theme
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        
        // Search history and results caching management
        function loadSearchHistory() {
            const history = JSON.parse(localStorage.getItem('searchHistory') || '[]');
            const cachedResults = JSON.parse(localStorage.getItem('cachedSearchResults') || '{}');
            const historyContainer = document.getElementById('historyItems');
            historyContainer.innerHTML = '';
            
            history.slice(-10).reverse().forEach(term => {
                const item = document.createElement('span');
                item.className = 'history-item';
                
                // Check if we have cached results for this term
                const cacheKey = generateCacheKey(term);
                const cached = cachedResults[cacheKey];
                
                if (cached) {
                    const age = getResultAge(cached.timestamp);
                    item.innerHTML = `${term} <small>(${age})</small>`;
                    item.title = `Cached results from ${new Date(cached.timestamp).toLocaleString()}`;
                } else {
                    item.textContent = term;
                }
                
                item.onclick = () => {
                    document.getElementById('searchTerm').value = term;
                    if (cached) {
                        // Load from cache
                        loadCachedResults(term, cached);
                    }
                };
                historyContainer.appendChild(item);
            });
        }
        
        function addToSearchHistory(term) {
            let history = JSON.parse(localStorage.getItem('searchHistory') || '[]');
            history = history.filter(h => h !== term); // Remove duplicates
            history.push(term);
            if (history.length > 20) history = history.slice(-20); // Keep last 20
            localStorage.setItem('searchHistory', JSON.stringify(history));
            loadSearchHistory();
        }
        
        function generateCacheKey(searchTerm, params = {}) {
            // Create a cache key based on search term and parameters
            const key = {
                term: searchTerm,
                since: params.since || '',
                type: params.type || 'all',
                descriptions: params.descriptions !== false,
                logs: params.logs !== false,
                files: params.files !== false,
                file_types: params.file_types || '',
                limit: params.limit || ''
            };
            return btoa(JSON.stringify(key)).replace(/[^a-zA-Z0-9]/g, '');
        }
        
        function cacheSearchResults(searchTerm, params, results) {
            const cacheKey = generateCacheKey(searchTerm, params);
            const cachedResults = JSON.parse(localStorage.getItem('cachedSearchResults') || '{}');
            
            cachedResults[cacheKey] = {
                searchTerm: searchTerm,
                params: params,
                results: results,
                timestamp: Date.now()
            };
            
            // Keep only last 50 cached results to avoid localStorage bloat
            const entries = Object.entries(cachedResults);
            if (entries.length > 50) {
                entries.sort((a, b) => b[1].timestamp - a[1].timestamp);
                const keepEntries = entries.slice(0, 50);
                const newCache = {};
                keepEntries.forEach(([key, value]) => {
                    newCache[key] = value;
                });
                localStorage.setItem('cachedSearchResults', JSON.stringify(newCache));
            } else {
                localStorage.setItem('cachedSearchResults', JSON.stringify(cachedResults));
            }
        }
        
        function loadCachedResults(searchTerm, cached) {
            console.log('Loading cached results for:', searchTerm);
            
            // Set form values to match cached search
            document.getElementById('searchTerm').value = cached.searchTerm;
            document.getElementById('since').value = cached.params.since || '';
            document.getElementById('searchType').value = cached.params.type || 'all';
            document.getElementById('includeDescriptions').checked = cached.params.descriptions !== false;
            document.getElementById('includeLogs').checked = cached.params.logs !== false;
            document.getElementById('includeFiles').checked = cached.params.files !== false;
            document.getElementById('fileTypes').value = cached.params.file_types || '';
            document.getElementById('limit').value = cached.params.limit || '';
            
            // Display cached results with age indicator
            displayCachedResults(cached);
        }
        
        function getResultAge(timestamp) {
            const now = Date.now();
            const diff = now - timestamp;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);
            
            if (days > 0) return `${days}d ago`;
            if (hours > 0) return `${hours}h ago`;
            if (minutes > 0) return `${minutes}m ago`;
            return 'just now';
        }
        
        function displayCachedResults(cached) {
            const age = getResultAge(cached.timestamp);
            const ageDate = new Date(cached.timestamp).toLocaleString();
            
            // Create the cached results display with refresh option
            const data = {
                success: true,
                results: cached.results,
                total: cached.results.projects.length + cached.results.tasks.length + 
                       cached.results.messages.length + cached.results.files.length,
                cached: true,
                age: age,
                timestamp: ageDate
            };
            
            displayResults(data);
        }
        
        // Tab management
        function switchTab(tabName) {
            // Hide all tab contents
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(tab => tab.classList.remove('active'));
            
            // Remove active class from all tab buttons
            const tabButtons = document.querySelectorAll('.tab-button');
            tabButtons.forEach(button => button.classList.remove('active'));
            
            // Show selected tab content
            document.getElementById(tabName + '-tab').classList.add('active');
            
            // Add active class to selected tab button
            event.target.classList.add('active');
            
            // Load content for specific tabs
            if (tabName === 'pins') {
                loadPins();
            } else if (tabName === 'settings') {
                loadSettings();
            }
        }
        
        function loadSettings() {
            fetch('/api/settings')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('odooHost').value = data.settings.host || '';
                        document.getElementById('odooDatabase').value = data.settings.database || '';
                        document.getElementById('odooUser').value = data.settings.user || '';
                        document.getElementById('odooPassword').placeholder = data.settings.password ? 'Password is set (leave empty to keep current)' : 'Enter password';
                        document.getElementById('odooPort').value = data.settings.port || '443';
                        document.getElementById('odooProtocol').value = data.settings.protocol || 'xml-rpcs';
                    }
                })
                .catch(error => console.error('Error loading settings:', error));
        }
        
        function saveSettings(event) {
            event.preventDefault();
            const formData = new FormData(event.target);
            const settings = Object.fromEntries(formData.entries());
            
            fetch('/api/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(settings)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Settings saved successfully!');
                } else {
                    alert('Error saving settings: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error saving settings:', error);
                alert('Error saving settings');
            });
        }
        
        // Search functionality with background processing
        function performSearch(event, forceRefresh = false) {
            event.preventDefault();
            
            const formData = new FormData(event.target);
            const searchParams = {
                q: formData.get('searchTerm'),
                since: formData.get('since') || '',
                type: formData.get('searchType'),
                descriptions: formData.get('includeDescriptions') ? 'true' : 'false',
                logs: formData.get('includeLogs') ? 'true' : 'false',
                files: formData.get('includeFiles') ? 'true' : 'false',
                file_types: formData.get('fileTypes') || '',
                limit: formData.get('limit') || ''
            };
            
            // Check for cached results if not forcing refresh
            if (!forceRefresh) {
                const cacheKey = generateCacheKey(searchParams.q, searchParams);
                const cachedResults = JSON.parse(localStorage.getItem('cachedSearchResults') || '{}');
                const cached = cachedResults[cacheKey];
                
                if (cached) {
                    console.log('Using cached results');
                    displayCachedResults(cached);
                    addToSearchHistory(searchParams.q);
                    return;
                }
            }
            
            // Build URL params for API call
            const params = new URLSearchParams();
            Object.entries(searchParams).forEach(([key, value]) => {
                if (value) params.append(key, value);
            });
            
            // Add to search history
            addToSearchHistory(searchParams.q);
            
            // Show loading with progress
            showSearchProgress('Starting search...');
            
            // Start background search
            fetch('/api/search?' + params.toString())
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.search_id) {
                        // Start polling for results
                        pollSearchResults(data.search_id, searchParams);
                    } else {
                        document.getElementById('results').innerHTML = 
                            `<div class="error">Error: ${data.error || 'Failed to start search'}</div>`;
                    }
                })
                .catch(error => {
                    console.error('Search error:', error);
                    document.getElementById('results').innerHTML = 
                        `<div class="error">Search failed: ${error.message}</div>`;
                });
        }
        
        function showSearchProgress(message) {
            document.getElementById('results').innerHTML = `
                <div class="loading">
                    ${message}
                    <div class="progress-dots">
                        <span>.</span><span>.</span><span>.</span>
                    </div>
                </div>
            `;
        }
        
        function pollSearchResults(searchId, searchParams) {
            const startTime = Date.now();
            
            function checkStatus() {
                fetch(`/api/search/status?id=${searchId}`)
                    .then(response => response.json())
                    .then(data => {
                        const elapsed = Math.round((Date.now() - startTime) / 1000);
                        
                        if (data.status === 'running') {
                            showSearchProgress(`Searching... (${elapsed}s)`);
                            // Continue polling
                            setTimeout(checkStatus, 1000);
                        } else if (data.status === 'completed') {
                            if (data.results && data.results.success) {
                                console.log('Search completed, results:', data.results);
                                
                                // Cache the results
                                cacheSearchResults(searchParams.q, searchParams, data.results.results);
                                
                                // Display results
                                displayResults(data.results);
                                
                                // Update search history to show cached status
                                loadSearchHistory();
                            } else {
                                console.error('Search failed:', data.results);
                                document.getElementById('results').innerHTML = 
                                    `<div class="error">Search completed but failed: ${data.results?.error || 'Unknown error'}</div>`;
                            }
                        } else if (data.status === 'timeout') {
                            document.getElementById('results').innerHTML = 
                                `<div class="error">Search timed out after 5 minutes. Please try a more specific search.</div>`;
                        } else if (data.status === 'error') {
                            document.getElementById('results').innerHTML = 
                                `<div class="error">Search failed: ${data.results?.error || 'Unknown error'}</div>`;
                        } else {
                            document.getElementById('results').innerHTML = 
                                `<div class="error">Unknown search status: ${data.status}</div>`;
                        }
                    })
                    .catch(error => {
                        console.error('Status check error:', error);
                        document.getElementById('results').innerHTML = 
                            `<div class="error">Failed to check search status: ${error.message}</div>`;
                    });
            }
            
            // Start polling
            checkStatus();
        }
        
        function refreshSearch() {
            // Get current search parameters from the form
            const form = document.querySelector('.search-form');
            const formData = new FormData(form);
            const searchParams = {
                q: formData.get('searchTerm'),
                since: formData.get('since') || '',
                type: formData.get('searchType'),
                descriptions: formData.get('includeDescriptions') ? 'true' : 'false',
                logs: formData.get('includeLogs') ? 'true' : 'false',
                files: formData.get('includeFiles') ? 'true' : 'false',
                file_types: formData.get('fileTypes') || '',
                limit: formData.get('limit') || ''
            };
            
            // Clear only this specific query's cache
            const cacheKey = generateCacheKey(searchParams.q, searchParams);
            const cachedResults = JSON.parse(localStorage.getItem('cachedSearchResults') || '{}');
            
            if (cachedResults[cacheKey]) {
                delete cachedResults[cacheKey];
                localStorage.setItem('cachedSearchResults', JSON.stringify(cachedResults));
                console.log('Cleared cache for current search');
            }
            
            // Update search history to remove cached indicator
            loadSearchHistory();
            
            // Trigger the search button click
            const searchButton = document.querySelector('.search-form button[type="submit"]');
            if (searchButton) {
                searchButton.click();
            }
        }
        
        function displayResults(data) {
            const resultsContainer = document.getElementById('results');
            const results = data.results;
            const total = data.total;
            
            console.log('Displaying results:', results);
            console.log('Total:', total);
            console.log('Projects:', results.projects?.length || 0);
            console.log('Tasks:', results.tasks?.length || 0);
            console.log('Messages:', results.messages?.length || 0);
            console.log('Files:', results.files?.length || 0);
            
            // Store current results globally for pin functionality
            window.currentSearchResults = results;
            
            if (total === 0) {
                resultsContainer.innerHTML = '<div class="error">No results found.</div>';
                return;
            }
            
            let html = `
                <div class="results-summary">
                    <div class="results-header">
                        <h2>Search Results (${total} total)</h2>
                        <div class="results-actions">
            `;
            
            // Add age indicator and refresh button for cached results
            if (data.cached) {
                html += `
                    <div class="cache-info">
                        <span class="cache-age">📅 ${data.age} (${data.timestamp})</span>
                        <button class="btn btn-secondary refresh-btn" onclick="refreshSearch()" title="Refresh results">
                            🔄 Refresh
                        </button>
                    </div>
                `;
            }
            
            html += `
                        </div>
                    </div>
                    <div class="results-stats">
                        <a href="#projects-section" class="stat-item">📂 Projects: ${results.projects?.length || 0}</a>
                        <a href="#tasks-section" class="stat-item">📋 Tasks: ${results.tasks?.length || 0}</a>
                        <a href="#messages-section" class="stat-item">💬 Messages: ${results.messages?.length || 0}</a>
                        <a href="#files-section" class="stat-item">📁 Files: ${results.files?.length || 0}</a>
                    </div>
                </div>
            `;
            
            // Display each section
            if (results.projects?.length > 0) {
                html += renderSection('Projects', '📂', results.projects, 'project', 'projects-section');
            }
            
            if (results.tasks?.length > 0) {
                html += renderSection('Tasks', '📋', results.tasks, 'task', 'tasks-section');
            }
            
            if (results.messages?.length > 0) {
                html += renderSection('Messages', '💬', results.messages, 'message', 'messages-section');
            }
            
            if (results.files?.length > 0) {
                html += renderSection('Files', '📁', results.files, 'file', 'files-section');
            }
            
            resultsContainer.innerHTML = html;
        }
        
        function renderSection(title, icon, items, type, sectionId) {
            let html = `
                <div class="result-section" id="${sectionId}">
                    <div class="section-header">
                        <span class="section-title">${icon} ${title} (${items.length})</span>
                    </div>
            `;
            
            items.forEach(item => {
                html += renderResultItem(item, type);
            });
            
            html += '</div>';
            return html;
        }
        
        function renderResultItem(item, type) {
            let html = `<div class="result-item">`;
            
            // Header with title and actions
            html += `<div class="result-header">`;
            html += `<div class="result-title">`;
            if (item.url) {
                html += `<a href="${item.url}" target="_blank">${escapeHtml(item.name || item.subject || 'Untitled')}</a>`;
            } else {
                html += escapeHtml(item.name || item.subject || 'Untitled');
            }
            html += ` <small>(ID: ${item.id})</small></div>`;
            
            // Actions
            html += `<div class="result-actions">`;
            if (type === 'file' && item.download_url) {
                html += `<a href="${item.download_url}" class="download-btn">📥 Download</a>`;
            }
            
            // Pin button
            const isPinned = isItemPinned(item.id, type);
            const pinText = isPinned ? '📌 Unpin' : '📌 Pin';
            const pinClass = isPinned ? 'pin-btn pinned' : 'pin-btn';
            html += `<button class="${pinClass}" onclick="togglePin('${item.id}', '${type}', this)" title="${pinText}">${pinText}</button>`;
            
            html += `</div>`;
            html += `</div>`;
            
            // Metadata
            html += `<div class="result-meta">`;
            
            if (type === 'project') {
                if (item.partner) html += `<div class="meta-item">🏢 ${escapeHtml(item.partner)}</div>`;
                if (item.user) html += `<div class="meta-item">👤 ${escapeHtml(item.user)}</div>`;
            } else if (type === 'task') {
                if (item.project_name) {
                    if (item.project_url) {
                        html += `<div class="meta-item">📂 <a href="${item.project_url}" target="_blank">${escapeHtml(item.project_name)}</a></div>`;
                    } else {
                        html += `<div class="meta-item">📂 ${escapeHtml(item.project_name)}</div>`;
                    }
                }
                if (item.user) html += `<div class="meta-item">👤 ${escapeHtml(item.user)}</div>`;
                if (item.stage) html += `<div class="meta-item">📊 ${escapeHtml(item.stage)}</div>`;
            } else if (type === 'message') {
                if (item.author) html += `<div class="meta-item">👤 ${escapeHtml(item.author)}</div>`;
                if (item.related_name && item.related_url) {
                    html += `<div class="meta-item">📎 <a href="${item.related_url}" target="_blank">${escapeHtml(item.related_name)}</a></div>`;
                } else if (item.related_name) {
                    html += `<div class="meta-item">📎 ${escapeHtml(item.related_name)}</div>`;
                }
            } else if (type === 'file') {
                if (item.mimetype) html += `<div class="meta-item">📊 ${escapeHtml(item.mimetype)}</div>`;
                if (item.file_size_human) html += `<div class="meta-item">📏 ${escapeHtml(item.file_size_human)}</div>`;
                if (item.related_name && item.related_url) {
                    html += `<div class="meta-item">📎 <a href="${item.related_url}" target="_blank">${escapeHtml(item.related_name)}</a></div>`;
                } else if (item.related_name) {
                    html += `<div class="meta-item">📎 ${escapeHtml(item.related_name)}</div>`;
                }
            }
            
            // Date
            const date = item.date || item.write_date || item.create_date;
            if (date) {
                html += `<div class="meta-item">📅 ${new Date(date).toLocaleString()}</div>`;
            }
            
            html += `</div>`;
            
            // Description/Body
            const description = item.description || item.body;
            if (description && description.trim()) {
                // Description is already converted to markdown on the server side
                const truncated = description.length > 300 ? description.substring(0, 300) + '...' : description;
                html += `<div class="result-description">${escapeHtml(truncated)}</div>`;
            }
            
            html += `</div>`;
            return html;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        
        function loadPins() {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            const container = document.getElementById('pinsContainer');
            
            if (pins.length === 0) {
                container.innerHTML = '<div class="error">No pinned items yet. Pin items from search results to see them here.</div>';
                return;
            }
            
            let html = '';
            pins.forEach(pin => {
                html += renderPinItem(pin);
            });
            
            container.innerHTML = html;
        }
        
        function renderPinItem(pin) {
            const typeIcon = {
                'project': '📂',
                'task': '📋', 
                'message': '💬',
                'file': '📁'
            }[pin.type] || '📄';
            
            let html = `
                <div class="pin-item">
                    <div class="pin-item-header">
                        <div class="pin-item-title">
                            ${typeIcon} 
            `;
            
            if (pin.url) {
                html += `<a href="${pin.url}" target="_blank">${escapeHtml(pin.name)}</a>`;
            } else {
                html += escapeHtml(pin.name);
            }
            
            html += ` <small>(ID: ${pin.id})</small>
                        </div>
                        <button class="unpin-btn" onclick="unpinItem('${pin.id}', '${pin.type}')">🗑️ Remove</button>
                    </div>
            `;
            
            // Meta information
            if (pin.meta) {
                html += `<div class="pin-item-meta">${escapeHtml(pin.meta)}</div>`;
            }
            
            // Description
            if (pin.description) {
                const truncated = pin.description.length > 200 ? pin.description.substring(0, 200) + '...' : pin.description;
                html += `<div class="pin-item-description">${escapeHtml(truncated)}</div>`;
            }
            
            html += `<div class="pin-item-meta">Pinned: ${new Date(pin.pinnedAt).toLocaleString()}</div>`;
            html += `</div>`;
            
            return html;
        }
        
        function togglePin(itemId, itemType, buttonElement) {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            const existingIndex = pins.findIndex(p => p.id === itemId && p.type === itemType);
            
            if (existingIndex >= 0) {
                // Unpin
                pins.splice(existingIndex, 1);
                buttonElement.textContent = '📌 Pin';
                buttonElement.className = 'pin-btn';
                buttonElement.title = '📌 Pin';
            } else {
                // Pin - find the item data from current search results
                const itemData = findItemInResults(itemId, itemType);
                if (itemData) {
                    const pinItem = createPinItem(itemData, itemType);
                    pins.push(pinItem);
                    buttonElement.textContent = '📌 Unpin';
                    buttonElement.className = 'pin-btn pinned';
                    buttonElement.title = '📌 Unpin';
                }
            }
            
            localStorage.setItem('pinnedItems', JSON.stringify(pins));
        }
        
        function findItemInResults(itemId, itemType) {
            // Search through current results to find the item
            const resultsContainer = document.getElementById('results');
            if (!resultsContainer || !window.currentSearchResults) return null;
            
            const results = window.currentSearchResults;
            const categoryMap = {
                'project': 'projects',
                'task': 'tasks',
                'message': 'messages',
                'file': 'files'
            };
            
            const category = categoryMap[itemType];
            if (!category || !results[category]) return null;
            
            return results[category].find(item => item.id == itemId);
        }
        
        function createPinItem(itemData, itemType) {
            const pin = {
                id: itemData.id,
                type: itemType,
                name: itemData.name || itemData.subject || 'Untitled',
                url: itemData.url || null,
                pinnedAt: Date.now()
            };
            
            // Add type-specific metadata
            if (itemType === 'project') {
                pin.meta = `Client: ${itemData.partner || 'No client'} | User: ${itemData.user || 'Unassigned'}`;
                pin.description = itemData.description || '';
            } else if (itemType === 'task') {
                pin.meta = `Project: ${itemData.project_name || 'No project'} | User: ${itemData.user || 'Unassigned'} | Stage: ${itemData.stage || 'No stage'}`;
                pin.description = itemData.description || '';
            } else if (itemType === 'message') {
                pin.meta = `Author: ${itemData.author || 'System'} | Related: ${itemData.related_name || 'Unknown'}`;
                pin.description = itemData.body || '';
            } else if (itemType === 'file') {
                pin.meta = `Type: ${itemData.mimetype || 'Unknown'} | Size: ${itemData.file_size_human || '0 B'} | Related: ${itemData.related_name || 'Unknown'}`;
                pin.description = '';
            }
            
            return pin;
        }
        
        function isItemPinned(itemId, itemType) {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            return pins.some(p => p.id == itemId && p.type === itemType);
        }
        
        function unpinItem(itemId, itemType) {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            const filteredPins = pins.filter(p => !(p.id == itemId && p.type === itemType));
            localStorage.setItem('pinnedItems', JSON.stringify(filteredPins));
            loadPins();
            
            // Update pin buttons in search results if visible
            updatePinButtonsInResults();
        }
        
        function clearAllPins() {
            if (confirm('Clear all pinned items?')) {
                localStorage.removeItem('pinnedItems');
                loadPins();
                updatePinButtonsInResults();
                alert('All pins cleared successfully!');
            }
        }
        
        function exportPins() {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            if (pins.length === 0) {
                alert('No pins to export');
                return;
            }
            
            const dataStr = JSON.stringify(pins, null, 2);
            const dataBlob = new Blob([dataStr], {type: 'application/json'});
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'odoo-search-pins.json';
            link.click();
            URL.revokeObjectURL(url);
        }
        
        function updatePinButtonsInResults() {
            // Update all pin buttons in current search results
            const pinButtons = document.querySelectorAll('.pin-btn');
            pinButtons.forEach(button => {
                const onclick = button.getAttribute('onclick');
                if (onclick) {
                    const match = onclick.match(/togglePin\('([^']+)', '([^']+)'/);
                    if (match) {
                        const itemId = match[1];
                        const itemType = match[2];
                        const isPinned = isItemPinned(itemId, itemType);
                        
                        if (isPinned) {
                            button.textContent = '📌 Unpin';
                            button.className = 'pin-btn pinned';
                            button.title = '📌 Unpin';
                        } else {
                            button.textContent = '📌 Pin';
                            button.className = 'pin-btn';
                            button.title = '📌 Pin';
                        }
                    }
                }
            });
        }
        
        function scrollToResults() {
            // First make sure we're on the search tab
            const searchTab = document.getElementById('search-tab');
            if (!searchTab.classList.contains('active')) {
                switchTab('search');
            }
            
            // Then scroll to results
            const resultsElement = document.getElementById('results');
            if (resultsElement && resultsElement.innerHTML.trim() !== '') {
                resultsElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } else {
                // If no results, just scroll to the form
                const searchForm = document.querySelector('.search-form');
                if (searchForm) {
                    searchForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        }
        
        // Cache management
        function clearCache() {
            if (confirm('Clear all cached search results and search history?')) {
                localStorage.removeItem('cachedSearchResults');
                localStorage.removeItem('searchHistory');
                loadSearchHistory();
                alert('Cache and search history cleared successfully!');
            }
        }
        
        // Initialize
        loadSearchHistory();
    </script>
</body>
</html>"""

    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        pass


class WebSearchServer:
    """Web server for Odoo search interface"""
    
    def __init__(self, host='localhost', port=1900):
        self.host = host
        self.port = port
        self.server = None
        
    def start(self, open_browser=True):
        """Start the web server"""
        try:
            self.server = HTTPServer((self.host, self.port), WebSearchHandler)
            
            print(f"🚀 Odoo Web Search Server starting...")
            print(f"📍 Server running at: http://{self.host}:{self.port}")
            print(f"🌐 Open in browser: http://{self.host}:{self.port}")
            print(f"⏹️  Press Ctrl+C to stop")
            
            if open_browser:
                # Open browser in a separate thread to avoid blocking
                threading.Timer(1.0, lambda: webbrowser.open(f'http://{self.host}:{self.port}')).start()
            
            self.server.serve_forever()
            
        except KeyboardInterrupt:
            print(f"\n🛑 Server stopped by user")
            self.stop()
        except Exception as e:
            print(f"❌ Server error: {e}")
            
    def stop(self):
        """Stop the web server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            print(f"✅ Server stopped")


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Odoo Web Search Server - Web interface for Odoo text search',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python web_search_server.py
  python web_search_server.py --port 1900 --host 0.0.0.0
  python web_search_server.py --no-browser
        """
    )
    
    parser.add_argument('--host', default='localhost', help='Host to bind to (default: localhost)')
    parser.add_argument('--port', type=int, default=1900, help='Port to bind to (default: 1900)')
    parser.add_argument('--no-browser', action='store_true', help='Do not open browser automatically')
    
    args = parser.parse_args()
    
    # Check if config file exists using ConfigManager
    config_path = ConfigManager.get_config_path()
    if not config_path.exists():
        print(f"⚠️  No configuration file found at: {config_path}")
        print("   You can configure settings through the web interface.")
        print("   Or run: edwh odoo.setup")
    else:
        try:
            ConfigManager.load_config(verbose=False)
            print("✅ Configuration loaded successfully")
        except Exception as e:
            print(f"⚠️  Configuration error: {e}")
            print("   You can fix settings through the web interface.")
    
    # Start server
    server = WebSearchServer(host=args.host, port=args.port)
    server.start(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
