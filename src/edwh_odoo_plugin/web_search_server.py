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
import secrets
import hashlib
import logging
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import base64
import mimetypes
import time
import warnings

# Configure secure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

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
    """HTTP request handler for the web search interface with security hardening"""
    
    # Class-level storage for active searches
    _active_searches = {}
    _search_lock = threading.Lock()
    
    # Security configuration
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    MAX_SEARCH_TERM_LENGTH = 1000
    RATE_LIMIT_REQUESTS = 100  # requests per minute
    RATE_LIMIT_WINDOW = 60  # seconds
    
    # Rate limiting storage
    _rate_limit_storage = {}
    _rate_limit_lock = threading.Lock()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def _check_rate_limit(self, client_ip):
        """Check if client is within rate limits"""
        current_time = time.time()
        
        with WebSearchHandler._rate_limit_lock:
            if client_ip not in WebSearchHandler._rate_limit_storage:
                WebSearchHandler._rate_limit_storage[client_ip] = []
            
            # Clean old requests
            requests = WebSearchHandler._rate_limit_storage[client_ip]
            requests[:] = [req_time for req_time in requests if current_time - req_time < self.RATE_LIMIT_WINDOW]
            
            # Check limit
            if len(requests) >= self.RATE_LIMIT_REQUESTS:
                return False
            
            # Add current request
            requests.append(current_time)
            return True
    
    def _sanitize_input(self, value, max_length=None):
        """Sanitize user input"""
        if not value:
            return ""
        
        # Convert to string and limit length
        value = str(value)
        if max_length:
            value = value[:max_length]
        
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>"\'\x00-\x1f\x7f-\x9f]', '', value)
        
        return sanitized.strip()
    
    def _validate_search_params(self, params):
        """Validate search parameters"""
        validated = {}
        
        # Sanitize search term
        search_term = params.get('q', [''])[0]
        validated['q'] = self._sanitize_input(search_term, self.MAX_SEARCH_TERM_LENGTH)
        
        # Validate since parameter
        since = params.get('since', [''])[0]
        if since:
            # Only allow alphanumeric and spaces
            if re.match(r'^[a-zA-Z0-9\s]+$', since) and len(since) <= 50:
                validated['since'] = since
            else:
                logger.warning(f"Invalid since parameter: {since}")
                validated['since'] = ''
        else:
            validated['since'] = ''
        
        # Validate type parameter
        valid_types = ['all', 'projects', 'tasks', 'logs', 'files']
        search_type = params.get('type', ['all'])[0]
        validated['type'] = search_type if search_type in valid_types else 'all'
        
        # Validate boolean parameters
        for param in ['descriptions', 'logs', 'files']:
            value = params.get(param, ['true'])[0].lower()
            validated[param] = value in ['true', '1', 'yes']
        
        # Validate file types
        file_types = params.get('file_types', [''])[0]
        if file_types:
            # Only allow alphanumeric and common file extensions
            safe_types = []
            for ft in file_types.split(','):
                ft = ft.strip()
                if re.match(r'^[a-zA-Z0-9]+$', ft) and len(ft) <= 10:
                    safe_types.append(ft)
            validated['file_types'] = ','.join(safe_types[:10])  # Max 10 file types
        else:
            validated['file_types'] = ''
        
        # Validate limit
        try:
            limit = int(params.get('limit', ['0'])[0])
            validated['limit'] = min(max(0, limit), 10000)  # Max 10000 results
        except ValueError:
            validated['limit'] = 0
        
        return validated
    
    def do_GET(self):
        """Handle GET requests with security checks"""
        # Rate limiting
        client_ip = self.client_address[0]
        if not self._check_rate_limit(client_ip):
            self.send_error(429, "Too Many Requests")
            return
        
        try:
            parsed_path = urlparse(self.path)
            path = parsed_path.path
            
            # Validate path to prevent directory traversal
            if '..' in path or path.count('/') > 10:
                logger.warning(f"Suspicious path detected: {path}")
                self.send_error(400, "Bad Request")
                return
            
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
            elif path.startswith('/api/hierarchy/project/'):
                project_id = self.extract_id_from_path(path, '/api/hierarchy/project/')
                if project_id and isinstance(project_id, int) and project_id > 0:
                    self.handle_project_hierarchy_api(project_id)
                else:
                    self.send_error(400, "Invalid project ID")
            elif path.startswith('/api/hierarchy/task/'):
                task_id = self.extract_id_from_path(path, '/api/hierarchy/task/')
                if task_id and isinstance(task_id, int) and task_id > 0:
                    self.handle_task_hierarchy_api(task_id)
                else:
                    self.send_error(400, "Invalid task ID")
            elif path.startswith('/api/move-task'):
                self.handle_move_task_api(parsed_path.query)
            elif path.startswith('/static/'):
                # Disable static file serving for security
                self.send_error(403, "Forbidden")
            else:
                self.send_error(404, "Not Found")
                
        except Exception as e:
            logger.error(f"Error handling GET request: {e}")
            self.send_error(500, "Internal Server Error")
    
    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/api/settings':
            self.handle_settings_post()
        else:
            self.send_error(404, "Not Found")
    
    def serve_main_page(self):
        """Serve the main HTML page with security headers"""
        html_content = self.get_main_html()
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html_content.encode('utf-8'))))
        
        # Security headers
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")
        
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def handle_search_api(self, query_string):
        """Handle search API requests using background processes with security validation"""
        try:
            params = parse_qs(query_string)
            
            # Validate and sanitize parameters
            validated_params = self._validate_search_params(params)
            
            search_term = validated_params['q']
            if not search_term or len(search_term.strip()) < 2:
                self.send_json_response({'error': 'Search term must be at least 2 characters'}, 400)
                return

            # Generate unique search ID
            search_id = str(uuid.uuid4())
            
            # Log search request to console (sanitized)
            safe_term = search_term[:50] + "..." if len(search_term) > 50 else search_term
            print(f"🔍 Web search request [{search_id[:8]}]: '{safe_term}' (type: {validated_params['type']})")
            print(f"   Parameters: descriptions={validated_params['descriptions']}, logs={validated_params['logs']}, files={validated_params['files']}")
            if validated_params['file_types']:
                print(f"   File types: {validated_params['file_types']}")
            if validated_params['limit']:
                print(f"   Limit: {validated_params['limit']}")

            # Start background search process
            search_thread = threading.Thread(
                target=self._execute_search_process,
                args=(search_id, validated_params)
            )
            search_thread.daemon = True
            search_thread.start()
            
            # Store search info
            with WebSearchHandler._search_lock:
                WebSearchHandler._active_searches[search_id] = {
                    'status': 'running',
                    'started_at': time.time(),
                    'search_term': safe_term,  # Store sanitized version
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
    
    def _execute_search_process(self, search_id, validated_params):
        """Execute search in a separate Python process with security controls"""
        try:
            safe_term = validated_params['q'][:50] + "..." if len(validated_params['q']) > 50 else validated_params['q']
            print(f"🔍 Starting search process [{search_id[:8]}]: '{safe_term}'")
            print(f"   Search type: {validated_params['type']}, Include descriptions: {validated_params['descriptions']}")
            print(f"   Include logs: {validated_params['logs']}, Include files: {validated_params['files']}")
            
            # Create temporary files for communication with secure permissions
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as input_file:
                # Only pass validated parameters
                input_data = {
                    'search_term': validated_params['q'],
                    'since': validated_params['since'],
                    'search_type': validated_params['type'],
                    'include_descriptions': validated_params['descriptions'],
                    'include_logs': validated_params['logs'],
                    'include_files': validated_params['files'],
                    'file_types': validated_params['file_types'].split(',') if validated_params['file_types'] else None,
                    'limit': validated_params['limit'] if validated_params['limit'] > 0 else None
                }
                json.dump(input_data, input_file)
                input_file_path = input_file.name
            
            # Set secure permissions on temp files
            os.chmod(input_file_path, 0o600)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as output_file:
                output_file_path = output_file.name
            
            os.chmod(output_file_path, 0o600)
            
            # Execute search in separate process with security restrictions
            # Validate that we're not executing arbitrary code
            current_dir = os.getcwd()
            if not os.path.isabs(current_dir):
                raise ValueError("Invalid working directory")
            
            cmd = [
                sys.executable, '-c', f'''
import sys
import json
import os
import signal
import threading
import concurrent.futures
from datetime import datetime

# Set timeout for the entire process
def timeout_handler(signum, frame):
    raise TimeoutError("Search process timed out")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(300)  # 5 minute timeout

# Add both current directory and src directory to path
sys.path.insert(0, "{current_dir}")
sys.path.insert(0, os.path.join("{current_dir}", "src"))

try:
    from edwh_odoo_plugin.text_search import OdooTextSearch
except ImportError:
    try:
        from src.edwh_odoo_plugin.text_search import OdooTextSearch
    except ImportError:
        from text_search import OdooTextSearch

# Read input with validation
try:
    with open("{input_file_path}", "r") as f:
        params = json.load(f)
except Exception as e:
    raise ValueError(f"Failed to read input parameters: {{e}}")

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
            
            # Run the process with security restrictions
            print(f"⚙️  Executing search subprocess [{search_id[:8]}]...")
            
            # Security: Run with limited environment
            secure_env = {
                'PATH': os.environ.get('PATH', ''),
                'PYTHONPATH': os.environ.get('PYTHONPATH', ''),
                'HOME': os.environ.get('HOME', ''),
                'USER': os.environ.get('USER', ''),
            }
            
            process = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=300,  # 5 minute timeout
                cwd=current_dir,
                env=secure_env,
                shell=False  # Never use shell=True for security
            )
            
            print(f"📊 Search subprocess completed [{search_id[:8]}]:")
            print(f"   Return code: {process.returncode}")
            if process.stdout:
                print(f"   Stdout preview: {process.stdout[:200]}...")
            if process.stderr:
                print(f"   Stderr preview: {process.stderr[:200]}...")
            
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
                
                elapsed = time.time() - search_info['started_at']
                response = {
                    'search_id': search_id,
                    'status': search_info['status'],
                    'search_term': search_info['search_term'],
                    'started_at': search_info['started_at'],
                    'elapsed': elapsed
                }
                
                # Add progress estimation for running searches
                if search_info['status'] == 'running':
                    if elapsed < 10:
                        response['progress_message'] = f"🔄 Initializing search... ({elapsed:.0f}s)"
                    elif elapsed < 20:
                        response['progress_message'] = f"📂 Searching projects... ({elapsed:.0f}s)"
                    elif elapsed < 35:
                        response['progress_message'] = f"📋 Searching tasks... ({elapsed:.0f}s)"
                    elif elapsed < 50:
                        response['progress_message'] = f"💬 Searching messages... ({elapsed:.0f}s)"
                    elif elapsed < 70:
                        response['progress_message'] = f"📁 Searching files... ({elapsed:.0f}s)"
                    else:
                        response['progress_message'] = f"🔧 Processing results... ({elapsed:.0f}s)"
                
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
        """Handle file download API requests with security validation"""
        try:
            params = parse_qs(query_string)
            file_id = params.get('id', [''])[0]
            
            # Validate file ID
            if not file_id:
                self.send_json_response({'error': 'File ID is required'}, 400)
                return
            
            try:
                file_id_int = int(file_id)
                if file_id_int <= 0:
                    raise ValueError("Invalid file ID")
            except ValueError:
                logger.warning(f"Invalid file ID format: {file_id}")
                self.send_json_response({'error': 'Invalid file ID format'}, 400)
                return
            
            # Create temporary base connection for download (downloads are infrequent)
            try:
                odoo_base = OdooBase(verbose=False)
            except Exception as e:
                logger.error(f"Failed to connect to Odoo: {e}")
                self.send_json_response({'error': 'Failed to connect to Odoo'}, 500)
                return
            
            # Get file info first
            attachment_records = odoo_base.attachments.search_records([('id', '=', file_id_int)])
            
            if not attachment_records:
                logger.warning(f"File not found: {file_id_int}")
                self.send_json_response({'error': 'File not found'}, 404)
                return
            
            attachment = attachment_records[0]
            file_name = getattr(attachment, 'name', f'file_{file_id}')
            
            # Sanitize filename for security
            safe_filename = odoo_base._sanitize_filename(file_name)
            
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
            
            try:
                # Decode base64 data
                file_data = base64.b64decode(file_data_b64)
            except Exception as e:
                logger.error(f"Failed to decode file data: {e}")
                self.send_json_response({'error': 'Invalid file data'}, 500)
                return
            
            # Validate file size (max 100MB for web downloads)
            max_size = 100 * 1024 * 1024  # 100MB
            if len(file_data) > max_size:
                logger.warning(f"File too large for web download: {len(file_data)} bytes")
                self.send_json_response({'error': 'File too large for web download'}, 413)
                return
            
            # Determine MIME type safely
            mime_type, _ = mimetypes.guess_type(safe_filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Validate MIME type for security
            dangerous_types = [
                'application/x-executable',
                'application/x-msdownload',
                'application/x-msdos-program',
                'text/html',
                'text/javascript',
                'application/javascript'
            ]
            
            if mime_type in dangerous_types:
                logger.warning(f"Blocked download of potentially dangerous file type: {mime_type}")
                mime_type = 'application/octet-stream'
            
            # Send file with security headers
            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Disposition', f'attachment; filename="{safe_filename}"')
            self.send_header('Content-Length', str(len(file_data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(file_data)
            
            logger.info(f"File downloaded: {safe_filename} ({len(file_data)} bytes)")
            
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
    
    def extract_id_from_path(self, path, prefix):
        """Extract ID from URL path"""
        try:
            return int(path[len(prefix):].split('/')[0])
        except (ValueError, IndexError):
            return None

    def handle_project_hierarchy_api(self, project_id):
        """Handle project hierarchy API requests"""
        try:
            if not project_id:
                self.send_json_response({'error': 'Invalid project ID'}, 400)
                return

            print(f"🌳 Hierarchy request for project {project_id}")

            # Import TaskManager
            try:
                from .task_manager import TaskManager
            except ImportError:
                try:
                    from edwh_odoo_plugin.task_manager import TaskManager
                except ImportError:
                    from task_manager import TaskManager

            # Get hierarchy
            manager = TaskManager(verbose=False)
            result = manager.show_project_hierarchy(int(project_id))
            
            if result['success']:
                # Convert hierarchy to web-friendly format
                web_hierarchy = self.convert_hierarchy_for_web(result['hierarchy'], 'project')
                self.send_json_response({
                    'success': True,
                    'hierarchy': web_hierarchy,
                    'type': 'project'
                })
            else:
                self.send_json_response({
                    'success': False,
                    'error': result['error']
                }, 400)
                
        except Exception as e:
            import traceback
            error_msg = f"Hierarchy error: {str(e)}"
            traceback_msg = traceback.format_exc()

            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)

    def handle_task_hierarchy_api(self, task_id):
        """Handle task hierarchy API requests"""
        try:
            if not task_id:
                self.send_json_response({'error': 'Invalid task ID'}, 400)
                return

            print(f"🌳 Hierarchy request for task {task_id}")

            # Import TaskManager
            try:
                from .task_manager import TaskManager
            except ImportError:
                try:
                    from edwh_odoo_plugin.task_manager import TaskManager
                except ImportError:
                    from task_manager import TaskManager

            # Get hierarchy
            manager = TaskManager(verbose=False)
            result = manager.show_hierarchy(int(task_id))
            
            if result['success']:
                # Convert hierarchy to web-friendly format
                web_hierarchy = self.convert_hierarchy_for_web(result['hierarchy'], 'task')
                self.send_json_response({
                    'success': True,
                    'hierarchy': web_hierarchy,
                    'type': 'task'
                })
            else:
                self.send_json_response({
                    'success': False,
                    'error': result['error']
                }, 400)
                
        except Exception as e:
            import traceback
            error_msg = f"Hierarchy error: {str(e)}"
            traceback_msg = traceback.format_exc()

            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)

    def handle_move_task_api(self, query_string):
        """Handle task move API requests for drag & drop with partial tree updates"""
        try:
            params = parse_qs(query_string)
            
            # Extract parameters
            task_id = params.get('task_id', [''])[0]
            new_parent_id = params.get('new_parent_id', [''])[0]
            project_id = params.get('project_id', [''])[0] or None
            partial_update = params.get('partial', ['true'])[0].lower() == 'true'
            old_parent_id = params.get('old_parent_id', [''])[0] or None
            
            # Validate task_id
            if not task_id or task_id in ['null', 'undefined', '']:
                self.send_json_response({'error': 'Valid Task ID is required'}, 400)
                return
            
            # Validate new_parent_id
            if not new_parent_id or new_parent_id in ['null', 'undefined', '']:
                self.send_json_response({'error': 'Valid New parent ID is required'}, 400)
                return

            print(f"🔄 Move task request: {task_id} -> {new_parent_id} (partial: {partial_update})")

            # Validate that task_id can be converted to int
            try:
                int(task_id)
            except (ValueError, TypeError):
                self.send_json_response({'error': f'Task ID must be a valid number, got: {task_id}'}, 400)
                return

            # Validate that new_parent_id can be converted to int (unless it's 'root')
            if new_parent_id != 'root':
                try:
                    int(new_parent_id)
                except (ValueError, TypeError):
                    self.send_json_response({'error': f'New parent ID must be a valid number or "root", got: {new_parent_id}'}, 400)
                    return

            # Import TaskManager
            try:
                from .task_manager import TaskManager
            except ImportError:
                try:
                    from edwh_odoo_plugin.task_manager import TaskManager
                except ImportError:
                    from task_manager import TaskManager

            # Get pre-move state for partial updates
            pre_move_state = None
            if partial_update:
                pre_move_state = self._capture_move_state(task_id, old_parent_id, new_parent_id)

            # Perform the move
            manager = TaskManager(verbose=False)
            
            # Handle special case: moving to project root (promote to main task)
            if new_parent_id == 'root':
                result = manager.promote_task(int(task_id))
            else:
                result = manager.move_subtask(int(task_id), int(new_parent_id), project_id)
            
            if result['success']:
                if partial_update:
                    # Generate partial update response
                    update_data = self._generate_partial_updates(
                        task_id, old_parent_id, new_parent_id, pre_move_state, manager
                    )
                    
                    self.send_json_response({
                        'success': True,
                        'message': 'Task moved successfully',
                        'partial_update': True,
                        'updates': update_data,
                        'operation_id': str(uuid.uuid4()),
                        'details': result
                    })
                else:
                    # Legacy full response
                    self.send_json_response({
                        'success': True,
                        'message': 'Task moved successfully',
                        'partial_update': False,
                        'details': result
                    })
            else:
                self.send_json_response({
                    'success': False,
                    'error': result['error']
                }, 400)
                
        except Exception as e:
            import traceback
            error_msg = f"Move task error: {str(e)}"
            traceback_msg = traceback.format_exc()

            print(f"❌ {error_msg}")
            print(f"   Traceback: {traceback_msg}")

            self.send_json_response({
                'error': error_msg,
                'traceback': traceback_msg
            }, 500)

    def _capture_move_state(self, task_id, old_parent_id, new_parent_id):
        """Capture state before move operation for partial updates"""
        try:
            # Import TaskManager
            try:
                from .task_manager import TaskManager
            except ImportError:
                try:
                    from edwh_odoo_plugin.task_manager import TaskManager
                except ImportError:
                    from task_manager import TaskManager
            
            manager = TaskManager(verbose=False)
            
            # Get task details
            task_data = manager._get_task_name(int(task_id))
            
            state = {
                'task_id': task_id,
                'old_parent_id': old_parent_id,
                'new_parent_id': new_parent_id,
                'task_name': task_data if isinstance(task_data, str) else f"Task {task_id}",
                'timestamp': time.time()
            }
            
            return state
            
        except Exception as e:
            print(f"⚠️ Failed to capture move state: {e}")
            return {
                'task_id': task_id,
                'old_parent_id': old_parent_id,
                'new_parent_id': new_parent_id,
                'task_name': f"Task {task_id}",
                'timestamp': time.time()
            }

    def _generate_partial_updates(self, task_id, old_parent_id, new_parent_id, pre_move_state, manager):
        """Generate partial update instructions for the client"""
        try:
            updates = {
                'removed_from': None,
                'added_to': None,
                'updated_nodes': [],
                'operation_type': 'move'
            }
            
            # Handle removal from old parent
            if old_parent_id and old_parent_id != 'root':
                updates['removed_from'] = {
                    'parent_id': old_parent_id,
                    'task_id': task_id
                }
                
                # Update old parent metadata (child count)
                updates['updated_nodes'].append({
                    'node_id': f"node-task-{old_parent_id}",
                    'updates': {
                        'child_count_change': -1
                    }
                })
            
            # Handle addition to new parent
            if new_parent_id == 'root':
                # Promoted to main task
                updates['added_to'] = {
                    'parent_type': 'project',
                    'parent_id': 'root',
                    'task_id': task_id,
                    'operation': 'promote'
                }
            else:
                # Moved to new parent task
                updates['added_to'] = {
                    'parent_type': 'task',
                    'parent_id': new_parent_id,
                    'task_id': task_id,
                    'operation': 'move'
                }
                
                # Update new parent metadata (child count)
                updates['updated_nodes'].append({
                    'node_id': f"node-task-{new_parent_id}",
                    'updates': {
                        'child_count_change': 1
                    }
                })
            
            # Get updated task data for the moved task
            try:
                # Get fresh task data after move
                task_hierarchy = manager.show_hierarchy(int(task_id))
                if task_hierarchy['success']:
                    task_data = task_hierarchy['hierarchy']['main_task']
                    task_node = self._convert_single_task_node(task_data)
                    updates['moved_task_data'] = task_node
            except Exception as e:
                print(f"⚠️ Failed to get updated task data: {e}")
            
            return updates
            
        except Exception as e:
            print(f"❌ Failed to generate partial updates: {e}")
            return {
                'removed_from': {'parent_id': old_parent_id, 'task_id': task_id} if old_parent_id else None,
                'added_to': {'parent_id': new_parent_id, 'task_id': task_id},
                'updated_nodes': [],
                'operation_type': 'move',
                'error': str(e)
            }

    def _convert_single_task_node(self, task_data):
        """Convert a single task to web format for partial updates"""
        if not task_data:
            return None
            
        def clean_text(text):
            if not text:
                return ""
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', str(text))

        def normalize_priority(priority_value):
            try:
                priority = int(priority_value) if priority_value else 0
                if priority == 0:
                    return {'level': 0, 'name': 'Normal', 'stars': 1}
                elif priority == 1:
                    return {'level': 1, 'name': 'High', 'stars': 2}
                elif priority == 2:
                    return {'level': 2, 'name': 'Urgent', 'stars': 3}
                elif priority >= 3:
                    return {'level': 3, 'name': 'Critical', 'stars': 4}
                else:
                    return {'level': 0, 'name': 'Normal', 'stars': 1}
            except (ValueError, TypeError):
                return {'level': 0, 'name': 'Normal', 'stars': 1}

        def clean_stage_name(stage_name):
            if not stage_name or stage_name == 'No Stage':
                return 'No Stage'
            import re
            cleaned = re.sub(r'^\d+_', '', str(stage_name))
            cleaned = cleaned.replace('_', ' ').title()
            stage_mapping = {
                'Inbox': 'Inbox', 'In Progress': 'In Progress', 'Done': 'Done',
                'Cancelled': 'Cancelled', 'Waiting': 'Waiting', 'New': 'New', 'Draft': 'Draft'
            }
            return stage_mapping.get(cleaned, cleaned)

        # Normalize priority and stage
        priority_info = normalize_priority(task_data.get('priority', '0'))
        raw_stage = task_data.get('stage_name', 'No Stage')
        cleaned_stage = clean_stage_name(raw_stage)
        
        node = {
            'id': task_data.get('id'),
            'name': clean_text(task_data.get('name', 'Untitled')),
            'type': 'task',
            'url': f"https://education-warehouse.odoo.com/web#id={task_data.get('id')}&model=project.task&view_type=form",
            'stage': cleaned_stage,
            'priority': priority_info,
            'metadata': {}
        }
        
        # Add metadata
        if task_data.get('user'):
            node['metadata']['user'] = clean_text(task_data['user'])
        if task_data.get('stage_name'):
            node['metadata']['stage'] = cleaned_stage
        if task_data.get('priority'):
            node['metadata']['priority'] = clean_text(task_data['priority'])
        if task_data.get('state'):
            node['metadata']['state'] = clean_text(task_data['state'])
        if task_data.get('deadline'):
            node['metadata']['deadline'] = clean_text(task_data['deadline'])
        if task_data.get('project_name'):
            node['metadata']['project'] = clean_text(task_data['project_name'])
        if task_data.get('description'):
            node['metadata']['description'] = clean_text(task_data['description'])[:200] + ('...' if len(clean_text(task_data['description'])) > 200 else '')
        
        # Convert children recursively
        if task_data.get('children'):
            node['children'] = []
            for child in task_data['children']:
                child_node = self._convert_single_task_node(child)
                if child_node:
                    node['children'].append(child_node)
        
        return node

    def convert_hierarchy_for_web(self, hierarchy, hierarchy_type):
        """Convert terminal-friendly hierarchy to web-friendly format"""
        def clean_text(text):
            """Remove terminal escape codes and clean text"""
            if not text:
                return ""
            # Remove ANSI escape sequences
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', str(text))

        def normalize_priority(priority_value):
            """Convert priority to normalized format"""
            try:
                priority = int(priority_value) if priority_value else 0
                if priority == 0:
                    return {'level': 0, 'name': 'Normal', 'stars': 1}
                elif priority == 1:
                    return {'level': 1, 'name': 'High', 'stars': 2}
                elif priority == 2:
                    return {'level': 2, 'name': 'Urgent', 'stars': 3}
                elif priority >= 3:
                    return {'level': 3, 'name': 'Critical', 'stars': 4}
                else:
                    return {'level': 0, 'name': 'Normal', 'stars': 1}
            except (ValueError, TypeError):
                return {'level': 0, 'name': 'Normal', 'stars': 1}

        def clean_stage_name(stage_name):
            """Clean stage names by removing prefixes and formatting properly"""
            if not stage_name or stage_name == 'No Stage':
                return 'No Stage'
            
            # Remove common prefixes like "01_", "04_", etc.
            import re
            cleaned = re.sub(r'^\d+_', '', str(stage_name))
            
            # Convert underscores to spaces and title case
            cleaned = cleaned.replace('_', ' ').title()
            
            # Handle common stage names
            stage_mapping = {
                'Inbox': 'Inbox',
                'In Progress': 'In Progress', 
                'Done': 'Done',
                'Cancelled': 'Cancelled',
                'Waiting': 'Waiting',
                'New': 'New',
                'Draft': 'Draft'
            }
            
            return stage_mapping.get(cleaned, cleaned)

        def convert_task_node(task_data):
            """Convert a task node to web format"""
            if not task_data:
                return None
                
            # Normalize priority
            priority_info = normalize_priority(task_data.get('priority', '0'))
            
            # Clean stage name
            raw_stage = task_data.get('stage_name', 'No Stage')
            cleaned_stage = clean_stage_name(raw_stage)
            
            node = {
                'id': task_data.get('id'),
                'name': clean_text(task_data.get('name', 'Untitled')),
                'type': 'task',
                'url': f"https://education-warehouse.odoo.com/web#id={task_data.get('id')}&model=project.task&view_type=form",
                'stage': cleaned_stage,
                'priority': priority_info,
                'metadata': {}
            }
            
            # Add metadata
            if task_data.get('user'):
                node['metadata']['user'] = clean_text(task_data['user'])
            if task_data.get('stage_name'):
                node['metadata']['stage'] = cleaned_stage
            if task_data.get('priority'):
                node['metadata']['priority'] = clean_text(task_data['priority'])
            if task_data.get('state'):
                node['metadata']['state'] = clean_text(task_data['state'])
            if task_data.get('deadline'):
                node['metadata']['deadline'] = clean_text(task_data['deadline'])
            if task_data.get('project_name'):
                node['metadata']['project'] = clean_text(task_data['project_name'])
            if task_data.get('description'):
                node['metadata']['description'] = clean_text(task_data['description'])[:200] + ('...' if len(clean_text(task_data['description'])) > 200 else '')
            
            # Convert children recursively
            if task_data.get('children'):
                node['children'] = []
                for child in task_data['children']:
                    child_node = convert_task_node(child)
                    if child_node:
                        node['children'].append(child_node)
            
            return node

        def collect_filter_data(node, stages=None, priorities=None):
            """Recursively collect unique stages and priorities with optional verbose logging and timing"""
            if stages is None:
                stages = set()
            if priorities is None:
                priorities = set()

            verbose = getattr(self, 'verbose', False)
            t_start = time.time()
            
            def scan_node(current_node):
                if not current_node:
                    return
                    
                if current_node.get('type') == 'task':
                    # Collect stage
                    stage = current_node.get('stage')
                    if stage and isinstance(stage, str):
                        s = stage.strip()
                        if s:
                            stages.add(s)
                            if verbose:
                                print(f"   Collected stage: '{s}'")
                    
                    # Collect priority
                    priority = current_node.get('priority')
                    if priority and isinstance(priority, dict):
                        lvl = priority.get('level')
                        if lvl is not None:
                            priorities.add(lvl)
                            if verbose:
                                print(f"   Collected priority level: {lvl}")
                
                # Process children recursively
                children = current_node.get('children', [])
                if children:
                    if verbose:
                        print(f"   Scanning {len(children)} children of {current_node.get('name', 'unnamed')}")
                    for child in children:
                        scan_node(child)
            
            if verbose:
                print(f"🔍 Starting filter data collection from node: {node.get('name', 'unnamed') if node else 'None'}")
            scan_node(node)
            
            if verbose:
                print(f"📊 Filter data collection complete:")
                print(f"   Stages found: {sorted(list(stages))}")
                print(f"   Priority levels found: {sorted(list(priorities))}")
                print(f"   Took: {int((time.time() - t_start)*1000)} ms")
            
            return stages, priorities

        web_data = {}
        
        if hierarchy_type == 'project':
            # Project hierarchy
            project = hierarchy.get('project', {})
            web_data = {
                'type': 'project',
                'root': {
                    'id': project.get('id'),
                    'name': clean_text(project.get('name', 'Untitled Project')),
                    'type': 'project',
                    'url': f"https://education-warehouse.odoo.com/web#id={project.get('id')}&model=project.project&view_type=form",
                    'metadata': {
                        'manager': clean_text(project.get('user_name', 'Unassigned')),
                        'client': clean_text(project.get('partner_name', 'No client')),
                        'total_tasks': hierarchy.get('total_tasks', 0),
                        'main_tasks': hierarchy.get('main_task_count', 0)
                    },
                    'children': []
                }
            }
            
            # Add main tasks as children
            for main_task in hierarchy.get('main_tasks', []):
                task_node = convert_task_node(main_task)
                if task_node:
                    web_data['root']['children'].append(task_node)
            
            # Collect filter data
            if getattr(self, 'verbose', False):
                print(f"🔍 Collecting filter data for project hierarchy...")
            _t_fd_start = time.time()
            stages, priorities = collect_filter_data(web_data['root'])
            web_data['filter_data'] = {
                'stages': sorted(list(stages)),
                'priorities': sorted(list(priorities))
            }
            web_data['filter_data_timings'] = {
                'collect_ms': int((time.time() - _t_fd_start) * 1000)
            }
            if getattr(self, 'verbose', False):
                print(f"📋 Project filter data: {web_data['filter_data']}")
                    
        elif hierarchy_type == 'task':
            # Task hierarchy
            main_task = hierarchy.get('main_task', {})
            web_data = {
                'type': 'task',
                'root': convert_task_node(main_task),
                'parents': []
            }
            
            # Add parent chain
            for parent in hierarchy.get('parents', []):
                parent_node = convert_task_node(parent)
                if parent_node:
                    web_data['parents'].append(parent_node)
            
            # Collect filter data
            if getattr(self, 'verbose', False):
                print(f"🔍 Collecting filter data for task hierarchy...")
            _t_fd_start = time.time()
            stages, priorities = collect_filter_data(web_data['root'])
            web_data['filter_data'] = {
                'stages': sorted(list(stages)),
                'priorities': sorted(list(priorities))
            }
            web_data['filter_data_timings'] = {
                'collect_ms': int((time.time() - _t_fd_start) * 1000)
            }
            if getattr(self, 'verbose', False):
                print(f"📋 Task filter data: {web_data['filter_data']}")
        
        return web_data

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
        """Send JSON response with security headers"""
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(json_data.encode('utf-8'))))
        
        # Security headers
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        
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
    <!-- Disable verbose console logging by default to reduce memory usage. Enable by setting localStorage.EDWH_DEBUG='1'. -->
    <script>
      (function(){
        try {
          var dbg = (typeof window !== 'undefined') && (window.localStorage && window.localStorage.getItem('EDWH_DEBUG') === '1');
          if (!dbg && typeof console !== 'undefined') {
            console.log = function(){};
          }
        } catch(e) {
          if (typeof console !== 'undefined') { console.log = function(){}; }
        }
      })();
    </script>
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
        
        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .progress-step {
            font-weight: 600;
            font-size: 1.1rem;
            color: var(--accent-color);
        }
        
        .progress-time {
            font-size: 0.9rem;
            color: #666;
            font-family: monospace;
        }
        
        [data-theme="dark"] .progress-time {
            color: #aaa;
        }
        
        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: var(--border-color);
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 10px;
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--accent-color), var(--success-color));
            border-radius: 4px;
            transition: width 0.5s ease;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .progress-description {
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 8px;
            font-style: italic;
        }
        
        [data-theme="dark"] .progress-description {
            color: #aaa;
        }
        
        .progress-message {
            font-size: 0.85rem;
            color: var(--text-color);
            margin-bottom: 10px;
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
        
        .pins-content, .settings-content, .hierarchy-content {
            background: var(--card-bg);
            padding: 25px;
            border-radius: 12px;
            box-shadow: var(--shadow);
        }
        
        .hierarchy-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .hierarchy-actions {
            display: flex;
            gap: 10px;
        }
        
        .hierarchy-search {
            margin-bottom: 20px;
            padding: 20px;
            background: var(--bg-color);
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        
        .hierarchy-container {
            /* Allow the tree to take all required vertical space; avoid inner scrolling */
            max-height: none;
            overflow: visible;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: var(--bg-color);
        }
        
        .hierarchy-filters {
            margin-bottom: 20px;
            padding: 15px;
            background: var(--card-bg);
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        
        .filter-section {
            margin-bottom: 15px;
        }
        
        .filter-section:last-child {
            margin-bottom: 0;
        }
        
        .filter-label {
            font-weight: 600;
            margin-bottom: 8px;
            display: block;
            color: var(--text-color);
        }
        
        .stage-filters {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 10px;
        }
        
        .stage-toggle {
            padding: 4px 12px;
            border: 1px solid var(--border-color);
            border-radius: 20px;
            background: var(--bg-color);
            color: var(--text-color);
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
            user-select: none;
        }
        
        .stage-toggle:hover {
            background: var(--card-bg);
        }
        
        .stage-toggle.active {
            background: var(--accent-color);
            color: white;
            border-color: var(--accent-color);
        }
        
        .stage-toggle.active:hover {
            opacity: 0.9;
        }
        
        .priority-filter {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .priority-slider {
            flex: 1;
            max-width: 200px;
        }
        
        .priority-label {
            font-size: 12px;
            color: var(--text-color);
            min-width: 60px;
        }
        
        .filter-actions {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }
        
        .filter-btn {
            padding: 4px 8px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            background: var(--bg-color);
            color: var(--text-color);
            cursor: pointer;
            font-size: 11px;
            transition: all 0.2s;
        }
        
        .filter-btn:hover {
            background: var(--card-bg);
        }
        
        .filter-summary {
            font-size: 11px;
            color: #666;
            margin-top: 8px;
            font-style: italic;
        }
        
        [data-theme="dark"] .filter-summary {
            color: #aaa;
        }
        
        .hierarchy-placeholder {
            text-align: center;
            padding: 40px 20px;
            color: #666;
        }
        
        [data-theme="dark"] .hierarchy-placeholder {
            color: #aaa;
        }
        
        .tree-view {
            padding: 20px;
            font-family: 'Courier New', monospace;
            line-height: 1.6;
        }
        
        .tree-node {
            margin: 2px 0;
            position: relative;
            transition: opacity 0.3s, transform 0.2s;
        }
        
        .tree-node.filtered-hidden {
            display: none;
        }
        
        .tree-node.drag-over {
            background-color: rgba(0, 123, 255, 0.2) !important;
            border: 3px solid var(--accent-color) !important;
            border-radius: 8px !important;
            box-shadow: 0 0 15px rgba(0, 123, 255, 0.5) !important;
            transform: scale(1.02) !important;
            transition: all 0.2s ease !important;
        }
        
        .tree-node.dragging {
            opacity: 0.7;
            transform: rotate(2deg) scale(0.95);
            z-index: 1000;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3);
        }
        
        .tree-node.valid-drop-target {
            background-color: rgba(40, 167, 69, 0.15) !important;
            border: 3px solid var(--success-color) !important;
            border-radius: 8px !important;
            box-shadow: 0 0 15px rgba(40, 167, 69, 0.4) !important;
            transform: scale(1.02) !important;
        }
        
        .tree-node.invalid-drop-target {
            background-color: rgba(220, 53, 69, 0.15) !important;
            border: 3px solid var(--danger-color) !important;
            border-radius: 8px !important;
            box-shadow: 0 0 15px rgba(220, 53, 69, 0.4) !important;
            cursor: not-allowed !important;
        }
        
        .tree-node.potential-drop-zone {
            background-color: rgba(0, 123, 255, 0.05);
            border: 2px dashed rgba(0, 123, 255, 0.3);
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        
        .tree-node-content {
            display: flex;
            align-items: center;
            padding: 4px 8px;
            border-radius: 4px;
            transition: background-color 0.2s;
            cursor: pointer;
            position: relative;
        }
        
        .tree-node-content:hover {
            background-color: var(--card-bg);
        }
        
        .tree-node-content.draggable {
            cursor: grab;
        }
        
        .tree-node-content.draggable:active {
            cursor: grabbing;
        }
        
        .drag-handle {
            opacity: 0;
            margin-right: 4px;
            cursor: grab;
            color: #999;
            transition: opacity 0.2s;
            font-size: 12px;
        }
        
        .tree-node-content:hover .drag-handle {
            opacity: 1;
        }
        
        .drag-handle:hover {
            color: var(--accent-color);
        }
        
        .drop-indicator {
            height: 2px;
            background: var(--accent-color);
            margin: 2px 0;
            border-radius: 1px;
            opacity: 0;
            transition: opacity 0.2s;
        }
        
        .drop-indicator.active {
            opacity: 1;
        }
        
        .tree-toggle {
            width: 16px;
            height: 16px;
            margin-right: 8px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .tree-toggle:hover {
            background-color: var(--border-color);
            border-radius: 2px;
        }
        
        .tree-icon {
            margin-right: 8px;
            font-size: 14px;
        }
        
        .tree-label {
            flex: 1;
            font-weight: 500;
        }
        
        .tree-label a {
            color: var(--accent-color);
            text-decoration: none;
        }
        
        .tree-label a:hover {
            text-decoration: underline;
        }
        
        .tree-metadata {
            font-size: 12px;
            color: #666;
            margin-left: 8px;
            display: flex;
            gap: 12px;
            align-items: center;
        }
        
        [data-theme="dark"] .tree-metadata {
            color: #aaa;
        }
        
        .priority-stars {
            color: #ffc107;
            font-size: 10px;
        }
        
        .stage-badge {
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 10px;
            background: var(--border-color);
            color: var(--text-color);
        }
        
        .stage-badge.in-progress {
            background: #007bff;
            color: white;
        }
        
        .stage-badge.done {
            background: #28a745;
            color: white;
        }
        
        .stage-badge.waiting {
            background: #ffc107;
            color: #333;
        }
        
        .stage-badge.cancelled {
            background: #dc3545;
            color: white;
        }
        
        .tree-children {
            margin-left: 24px;
            border-left: 1px solid var(--border-color);
            padding-left: 12px;
        }
        
        .tree-children.collapsed {
            display: none;
        }
        
        .hierarchy-breadcrumb {
            padding: 10px 20px;
            background: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
        }
        
        .breadcrumb-item {
            display: inline;
        }
        
        .breadcrumb-item:not(:last-child)::after {
            content: ' › ';
            color: #666;
            margin: 0 8px;
        }
        
        .breadcrumb-item a {
            color: var(--accent-color);
            text-decoration: none;
        }
        
        .breadcrumb-item a:hover {
            text-decoration: underline;
        }
        
        /* Custom Modal System */
        .custom-modal {
            display: none;
            position: fixed;
            z-index: 10000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(2px);
        }
        
        .custom-modal.show {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .modal-content {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 25px;
            max-width: 500px;
            width: 90%;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border-color);
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .modal-title {
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--text-color);
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-color);
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
        }
        
        .modal-close:hover {
            background: var(--border-color);
        }
        
        .modal-body {
            margin-bottom: 20px;
            color: var(--text-color);
            line-height: 1.5;
        }
        
        .modal-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        
        /* Toast Notification System */
        .toast-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10001;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        .toast {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 15px 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            max-width: 400px;
            opacity: 0;
            transform: translateX(100%);
            transition: all 0.3s ease;
        }
        
        .toast.show {
            opacity: 1;
            transform: translateX(0);
        }
        
        .toast.success {
            border-left: 4px solid var(--success-color);
        }
        
        .toast.error {
            border-left: 4px solid var(--danger-color);
        }
        
        .toast.warning {
            border-left: 4px solid var(--warning-color);
        }
        
        .toast-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .toast-title {
            font-weight: 600;
            color: var(--text-color);
        }
        
        .toast-close {
            background: none;
            border: none;
            font-size: 18px;
            cursor: pointer;
            color: var(--text-color);
            opacity: 0.7;
        }
        
        .toast-close:hover {
            opacity: 1;
        }
        
        .toast-body {
            color: var(--text-color);
            font-size: 14px;
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
                <button class="tab-button" onclick="switchTab('hierarchy')">🌳 Hierarchy</button>
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
        
        <div id="hierarchy-tab" class="tab-content">
            <div class="hierarchy-content">
                <div class="hierarchy-header">
                    <h2>🌳 Project & Task Hierarchy</h2>
                    <div class="hierarchy-actions">
                        <button type="button" class="btn btn-secondary" onclick="expandAllNodes()">📂 Expand All</button>
                        <button type="button" class="btn btn-secondary" onclick="collapseAllNodes()">📁 Collapse All</button>
                    </div>
                </div>
                
                <div class="hierarchy-search">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="hierarchySearch">Search Project or Task</label>
                            <input type="text" id="hierarchySearch" placeholder="Enter project name, task name, or ID...">
                        </div>
                        <div class="form-group small">
                            <label for="hierarchyType">Type</label>
                            <select id="hierarchyType">
                                <option value="project">Project</option>
                                <option value="task">Task</option>
                            </select>
                        </div>
                        <div class="form-group small">
                            <button type="button" class="btn btn-primary" onclick="searchHierarchy()">🔍 Load</button>
                        </div>
                    </div>
                </div>
                
                <div class="hierarchy-filters" id="hierarchyFilters" style="display: none;">
                    <div class="filter-section">
                        <span class="filter-label">📊 Filter by Stage:</span>
                        <div class="stage-filters" id="stageFilters">
                            <!-- Stage toggles will be populated here -->
                        </div>
                        <div class="filter-actions">
                            <button class="filter-btn" onclick="toggleAllStages(true)">Show All</button>
                            <button class="filter-btn" onclick="toggleAllStages(false)">Hide All</button>
                        </div>
                    </div>
                    
                    <div class="filter-section">
                        <span class="filter-label">🔥 Minimum Priority:</span>
                        <div class="priority-filter">
                            <input type="range" id="prioritySlider" class="priority-slider" min="0" max="3" value="0" onchange="updatePriorityFilter()">
                            <span class="priority-label" id="priorityLabel">Normal+</span>
                        </div>
                    </div>
                    
                    <div class="filter-summary" id="filterSummary">
                        <!-- Filter summary will be shown here -->
                    </div>
                </div>
                
                <div id="hierarchyContainer" class="hierarchy-container">
                    <div class="hierarchy-placeholder">
                        <p>🌳 Search for a project or task above to view its hierarchy</p>
                        <p>Or click "View Hierarchy" from search results</p>
                    </div>
                </div>
            </div>
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
    
    <!-- Custom Modal -->
    <div id="customModal" class="custom-modal">
        <div class="modal-content">
            <div class="modal-header">
                <div class="modal-title" id="modalTitle">Confirm Action</div>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody">
                Are you sure you want to proceed?
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" id="modalConfirmBtn" onclick="confirmModal()">Confirm</button>
            </div>
        </div>
    </div>
    
    <!-- Toast Container -->
    <div id="toastContainer" class="toast-container"></div>
    
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
            } else if (tabName === 'hierarchy') {
                // Hierarchy tab doesn't need initial loading
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
                    showToast('Settings saved successfully!', 'success');
                } else {
                    showToast('Error saving settings: ' + data.error, 'error');
                }
            })
            .catch(error => {
                console.error('Error saving settings:', error);
                showToast('Error saving settings', 'error');
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
        
        function showSearchProgress(message, elapsed = 0) {
            const progressSteps = [
                { time: 0, step: "🔄 Initializing search...", desc: "Setting up search parameters" },
                { time: 5, step: "📂 Searching projects...", desc: "Looking through project names and descriptions" },
                { time: 15, step: "📋 Searching tasks...", desc: "Scanning task titles and content" },
                { time: 30, step: "💬 Searching messages...", desc: "Examining log messages and comments" },
                { time: 45, step: "📁 Searching files...", desc: "Checking file names and metadata" },
                { time: 60, step: "🔧 Processing results...", desc: "Organizing and enriching data" }
            ];
            
            let currentStep = progressSteps[0];
            for (let i = progressSteps.length - 1; i >= 0; i--) {
                if (elapsed >= progressSteps[i].time) {
                    currentStep = progressSteps[i];
                    break;
                }
            }
            
            const progressPercent = Math.min(90, (elapsed / 90) * 100); // Cap at 90% until complete
            
            document.getElementById('results').innerHTML = `
                <div class="loading">
                    <div class="progress-header">
                        <div class="progress-step">${currentStep.step}</div>
                        <div class="progress-time">⏱️ ${elapsed}s</div>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="width: ${progressPercent}%"></div>
                    </div>
                    <div class="progress-description">${currentStep.desc}</div>
                    <div class="progress-message">${message}</div>
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
                            const progressMessage = data.progress_message || `Searching... (${elapsed}s)`;
                            showSearchProgress(progressMessage, elapsed);
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
            
            // Hierarchy button for projects and tasks
            if (type === 'project') {
                html += `<button class="btn btn-secondary" onclick="viewHierarchy('project', '${item.id}')" title="View Project Hierarchy">🌳 Hierarchy</button>`;
            } else if (type === 'task') {
                html += `<button class="btn btn-secondary" onclick="viewHierarchy('task', '${item.id}')" title="View Task Hierarchy">🌳 Hierarchy</button>`;
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
        
        async function clearAllPins() {
            const confirmed = await showModal('Clear All Pins', 'Clear all pinned items?', 'Clear', 'Cancel');
            if (confirmed) {
                localStorage.removeItem('pinnedItems');
                loadPins();
                updatePinButtonsInResults();
                showToast('All pins cleared successfully!', 'success');
            }
        }
        
        function exportPins() {
            const pins = JSON.parse(localStorage.getItem('pinnedItems') || '[]');
            if (pins.length === 0) {
                showToast('No pins to export', 'warning');
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
        async function clearCache() {
            const confirmed = await showModal('Clear Cache', 'Clear all cached search results and search history?', 'Clear', 'Cancel');
            if (confirmed) {
                localStorage.removeItem('cachedSearchResults');
                localStorage.removeItem('searchHistory');
                loadSearchHistory();
                showToast('Cache and search history cleared successfully!', 'success');
            }
        }
        
        // Debug function to inspect hierarchy data
        function debugHierarchy(hierarchy) {
            console.log('=== HIERARCHY DEBUG ===');
            console.log('Full hierarchy object:', hierarchy);
            console.log('Type:', hierarchy?.type);
            console.log('Root exists:', !!hierarchy?.root);
            if (hierarchy?.root) {
                console.log('Root name:', hierarchy.root.name);
                console.log('Root type:', hierarchy.root.type);
                console.log('Root children exists:', !!hierarchy.root.children);
                console.log('Root children is array:', Array.isArray(hierarchy.root.children));
                console.log('Root children length:', hierarchy.root.children?.length || 0);
                if (hierarchy.root.children && hierarchy.root.children.length > 0) {
                    console.log('First child:', hierarchy.root.children[0]);
                }
            }
            console.log('Filter data:', hierarchy?.filter_data);
            console.log('=== END DEBUG ===');
        }

        // Hierarchy functionality
        function viewHierarchy(type, id) {
            // Switch to hierarchy tab
            switchTab('hierarchy');
            
            // Set the search form
            document.getElementById('hierarchySearch').value = id;
            document.getElementById('hierarchyType').value = type;
            
            // Load the hierarchy
            loadHierarchy(type, id);
        }
        
        function searchHierarchy() {
            const searchValue = document.getElementById('hierarchySearch').value.trim();
            const type = document.getElementById('hierarchyType').value;
            
            if (!searchValue) {
                showToast('Please enter a project name, task name, or ID', 'warning');
                return;
            }
            
            // If it's a number, treat as ID
            if (/^\d+$/.test(searchValue)) {
                loadHierarchy(type, searchValue);
            } else {
                // Search for the item first
                searchForHierarchyItem(searchValue, type);
            }
        }
        
        function searchForHierarchyItem(searchTerm, type) {
            const container = document.getElementById('hierarchyContainer');
            container.innerHTML = '<div class="loading">Searching for ' + type + '...</div>';
            
            // Use existing search API
            const params = new URLSearchParams({
                q: searchTerm,
                type: type === 'project' ? 'projects' : 'tasks',
                limit: '10'
            });
            
            fetch('/api/search?' + params.toString())
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.search_id) {
                        pollSearchForHierarchy(data.search_id, type);
                    } else {
                        container.innerHTML = '<div class="error">Search failed: ' + (data.error || 'Unknown error') + '</div>';
                    }
                })
                .catch(error => {
                    container.innerHTML = '<div class="error">Search error: ' + error.message + '</div>';
                });
        }
        
        function pollSearchForHierarchy(searchId, type) {
            function checkStatus() {
                fetch(`/api/search/status?id=${searchId}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'running') {
                            setTimeout(checkStatus, 1000);
                        } else if (data.status === 'completed' && data.results && data.results.success) {
                            const results = data.results.results;
                            const items = type === 'project' ? results.projects : results.tasks;
                            
                            if (items && items.length > 0) {
                                showHierarchySearchResults(items, type);
                            } else {
                                document.getElementById('hierarchyContainer').innerHTML = 
                                    '<div class="error">No ' + type + 's found</div>';
                            }
                        } else {
                            document.getElementById('hierarchyContainer').innerHTML = 
                                '<div class="error">Search failed</div>';
                        }
                    })
                    .catch(error => {
                        document.getElementById('hierarchyContainer').innerHTML = 
                            '<div class="error">Search error: ' + error.message + '</div>';
                    });
            }
            checkStatus();
        }
        
        function showHierarchySearchResults(items, type) {
            const container = document.getElementById('hierarchyContainer');
            let html = '<div style="padding: 20px;"><h3>Select ' + type + ' to view hierarchy:</h3>';
            
            items.forEach(item => {
                html += `
                    <div class="result-item" style="margin: 10px 0; cursor: pointer;" onclick="loadHierarchy('${type}', '${item.id}')">
                        <div class="result-title">
                            ${escapeHtml(item.name)} <small>(ID: ${item.id})</small>
                        </div>
                `;
                
                if (type === 'project' && item.partner) {
                    html += `<div class="result-meta"><div class="meta-item">🏢 ${escapeHtml(item.partner)}</div></div>`;
                } else if (type === 'task' && item.project_name) {
                    html += `<div class="result-meta"><div class="meta-item">📂 ${escapeHtml(item.project_name)}</div></div>`;
                }
                
                html += '</div>';
            });
            
            html += '</div>';
            container.innerHTML = html;
        }
        
        function loadHierarchy(type, id) {
            const container = document.getElementById('hierarchyContainer');
            container.innerHTML = '<div class="loading">Loading ' + type + ' hierarchy...</div>';
            
            fetch(`/api/hierarchy/${type}/${id}`)
                .then(response => response.json())
                .then(data => {
                    console.log('Hierarchy API response:', data);
                    if (data.success) {
                        debugHierarchy(data.hierarchy);
                        displayHierarchy(data.hierarchy);
                    } else {
                        container.innerHTML = '<div class="error">Error: ' + (data.error || 'Failed to load hierarchy') + '</div>';
                    }
                })
                .catch(error => {
                    console.error('Hierarchy load error:', error);
                    container.innerHTML = '<div class="error">Error: ' + error.message + '</div>';
                });
        }
        
        function displayHierarchy(hierarchy) {
            const container = document.getElementById('hierarchyContainer');
            const filtersContainer = document.getElementById('hierarchyFilters');
            
            console.log('🌳 Displaying hierarchy:', hierarchy);
            console.log('Hierarchy type:', hierarchy?.type);
            console.log('Root node:', hierarchy?.root);
            console.log('Filter data available:', !!hierarchy?.filter_data);
            console.log('Filter data content:', hierarchy?.filter_data);
            
            if (!hierarchy || !hierarchy.root) {
                console.error('❌ Invalid hierarchy data:', hierarchy);
                container.innerHTML = '<div class="error">Invalid hierarchy data received</div>';
                return;
            }
            
            // Store hierarchy globally for filtering and drag & drop
            window.currentHierarchy = hierarchy;
            
            let html = '';
            
            // Add breadcrumb for task hierarchy
            if (hierarchy.type === 'task' && hierarchy.parents && hierarchy.parents.length > 0) {
                html += '<div class="hierarchy-breadcrumb">';
                html += '<span>Path: </span>';
                hierarchy.parents.forEach((parent, index) => {
                    html += `<span class="breadcrumb-item"><a href="${parent.url}" target="_blank">${escapeHtml(parent.name)}</a></span>`;
                });
                html += `<span class="breadcrumb-item">${escapeHtml(hierarchy.root.name)}</span>`;
                html += '</div>';
            }
            
            // Render tree
            html += '<div class="tree-view" id="treeView">';
            console.log('About to render root node:', hierarchy.root.name, 'with children:', hierarchy.root.children?.length || 0);
            const rootHtml = renderTreeNode(hierarchy.root, 0, true);
            if (rootHtml) {
                html += rootHtml;
                console.log('Root node rendered successfully');
            } else {
                console.error('Root node failed to render');
                html += '<div class="error">Failed to render hierarchy tree</div>';
            }
            html += '</div>';
            
            console.log('Generated HTML length:', html.length);
            console.log('Generated HTML preview:', html.substring(0, 500) + '...');
            container.innerHTML = html;
            
            // Setup filters AFTER DOM is populated
            console.log('🔧 Setting up filters after DOM population...');
            setupHierarchyFilters(hierarchy);
            filtersContainer.style.display = 'block';
            
            // Setup drag & drop
            setupDragAndDrop();
            
            // Apply saved filters
            applySavedFilters();
            
            // Restore state if this is a refresh
            if (HierarchyState.expandedNodes.size > 0) {
                setTimeout(() => {
                    HierarchyState.restoreState();
                }, 100);
            }
        }
        
        function renderTreeNode(node, depth, isRoot = false) {
            if (!node) {
                console.warn('renderTreeNode called with null/undefined node');
                return '';
            }
            
            console.log('Rendering node:', node.name, 'Type:', node.type, 'Children:', node.children?.length || 0);
            
            const hasChildren = node.children && Array.isArray(node.children) && node.children.length > 0;
            const nodeId = `node-${node.type}-${node.id}`;
            const isDraggable = node.type === 'task' && !isRoot;
            
            // Get stage and priority for filtering
            const stage = node.stage || 'No Stage';
            const priorityLevel = node.priority ? node.priority.level : 0;
            
            let html = `<div class="tree-node" data-node-id="${nodeId}" data-task-id="${node.id}" data-stage="${stage}" data-priority="${priorityLevel}" data-type="${node.type}">`;
            
            // Drop indicator (for drag & drop)
            html += '<div class="drop-indicator"></div>';
            
            html += `<div class="tree-node-content ${isDraggable ? 'draggable' : ''}" ${isDraggable ? 'draggable="true"' : ''}>`;
            
            // Drag handle (only for tasks)
            if (isDraggable) {
                html += '<span class="drag-handle" title="Drag to move">⋮⋮</span>';
            }
            
            // Toggle button
            if (hasChildren) {
                html += '<button class="tree-toggle" onclick="toggleTreeNode(\'' + nodeId + '\')" title="Expand/Collapse">▼</button>';
            } else {
                html += '<span class="tree-toggle"></span>';
            }
            
            // Icon
            const icon = node.type === 'project' ? '📂' : '📋';
            html += '<span class="tree-icon">' + icon + '</span>';
            
            // Label with link
            html += '<span class="tree-label">';
            html += '<a href="' + node.url + '" target="_blank">' + escapeHtml(node.name) + '</a>';
            html += ' <small>(ID: ' + node.id + ')</small>';
            html += '</span>';
            
            // Metadata with enhanced display
            if (node.type === 'task') {
                html += '<div class="tree-metadata">';
                
                // Stage badge
                if (node.stage && node.stage !== 'No Stage') {
                    const stageClass = getStageClass(node.stage);
                    html += `<span class="stage-badge ${stageClass}">${escapeHtml(node.stage)}</span>`;
                }
                
                // Priority stars
                if (node.priority && node.priority.level > 0) {
                    const stars = '★'.repeat(node.priority.stars);
                    html += `<span class="priority-stars" title="${node.priority.name}">${stars}</span>`;
                }
                
                // User
                if (node.metadata && node.metadata.user) {
                    html += '<span>👤 ' + escapeHtml(node.metadata.user) + '</span>';
                }
                
                html += '</div>';
            } else if (node.metadata && Object.keys(node.metadata).length > 0) {
                html += '<div class="tree-metadata">';
                
                if (node.metadata.manager) {
                    html += '<span>👤 ' + escapeHtml(node.metadata.manager) + '</span>';
                }
                if (node.metadata.total_tasks) {
                    html += '<span>📊 ' + node.metadata.total_tasks + ' tasks</span>';
                }
                
                html += '</div>';
            }
            
            html += '</div>';
            
            // Children
            if (hasChildren) {
                html += '<div class="tree-children" id="children-' + nodeId + '">';
                console.log(`Rendering ${node.children.length} children for ${node.name}`);
                node.children.forEach((child, index) => {
                    if (child && typeof child === 'object') {
                        console.log(`  Child ${index + 1}:`, child.name || 'Unnamed', 'Type:', child.type || 'Unknown');
                        const childHtml = renderTreeNode(child, depth + 1);
                        if (childHtml) {
                            html += childHtml;
                        } else {
                            console.warn(`  Child ${index + 1} rendered empty HTML`);
                        }
                    } else {
                        console.warn(`  Child ${index + 1} is invalid:`, child);
                    }
                });
                html += '</div>';
            } else {
                console.log(`No children for ${node.name} (hasChildren: ${hasChildren}, children:`, node.children, ')');
            }
            
            html += '</div>';
            return html;
        }
        
        function getStageClass(stage) {
            const stageLower = stage.toLowerCase();
            if (stageLower.includes('progress') || stageLower.includes('doing')) {
                return 'in-progress';
            } else if (stageLower.includes('done') || stageLower.includes('complete')) {
                return 'done';
            } else if (stageLower.includes('wait') || stageLower.includes('pending')) {
                return 'waiting';
            } else if (stageLower.includes('cancel') || stageLower.includes('reject')) {
                return 'cancelled';
            }
            return '';
        }
        
        function toggleTreeNode(nodeId) {
            const childrenContainer = document.getElementById('children-' + nodeId);
            const toggleButton = document.querySelector('[data-node-id="' + nodeId + '"] .tree-toggle');
            
            if (childrenContainer) {
                if (childrenContainer.classList.contains('collapsed')) {
                    childrenContainer.classList.remove('collapsed');
                    toggleButton.textContent = '▼';
                } else {
                    childrenContainer.classList.add('collapsed');
                    toggleButton.textContent = '▶';
                }
            }
        }
        
        function expandAllNodes() {
            const collapsedNodes = document.querySelectorAll('.tree-children.collapsed');
            collapsedNodes.forEach(node => {
                node.classList.remove('collapsed');
            });
            
            const toggleButtons = document.querySelectorAll('.tree-toggle');
            toggleButtons.forEach(button => {
                if (button.textContent === '▶') {
                    button.textContent = '▼';
                }
            });
        }
        
        function collapseAllNodes() {
            const expandedNodes = document.querySelectorAll('.tree-children:not(.collapsed)');
            expandedNodes.forEach(node => {
                node.classList.add('collapsed');
            });
            
            const toggleButtons = document.querySelectorAll('.tree-toggle');
            toggleButtons.forEach(button => {
                if (button.textContent === '▼') {
                    button.textContent = '▶';
                }
            });
        }
        
        // Hierarchy Filtering System
        function setupHierarchyFilters(hierarchy) {
            console.log('🔧 Setting up hierarchy filters...');
            console.log('Hierarchy object:', hierarchy);
            console.log('Filter data:', hierarchy?.filter_data);
            
            const stageFilters = document.getElementById('stageFilters');
            const prioritySlider = document.getElementById('prioritySlider');
            
            if (!stageFilters || !prioritySlider) {
                console.error('❌ Filter UI elements not found');
                return;
            }
            
            // Clear existing filters
            stageFilters.innerHTML = '';
            
            // Get stages from multiple sources with fallback
            let stages = [];
            
            // Primary: Use hierarchy.filter_data.stages
            if (hierarchy?.filter_data?.stages && Array.isArray(hierarchy.filter_data.stages)) {
                stages = hierarchy.filter_data.stages;
                console.log('✅ Using hierarchy.filter_data.stages:', stages);
            } else {
                console.warn('⚠️ hierarchy.filter_data.stages not available, using fallback');
                // Fallback: Scan DOM for actual stage values
                stages = extractStagesFromDOM();
                console.log('🔄 Extracted stages from DOM:', stages);
            }
            
            // Emergency fallback: Scan hierarchy data directly
            if (stages.length === 0) {
                console.warn('⚠️ No stages found in DOM, scanning hierarchy data directly');
                stages = extractStagesFromHierarchyData(hierarchy);
                console.log('🔍 Extracted stages from hierarchy data:', stages);
            }
            
            // Final fallback: Common stage names
            if (stages.length === 0) {
                console.warn('⚠️ No stages found anywhere, using default stages');
                stages = ['No Stage', 'Inbox', 'In Progress', 'Done', 'Cancelled'];
                console.log('📋 Using default stages:', stages);
            }
            
            // Remove duplicates and sort
            stages = [...new Set(stages)].sort();
            console.log('📊 Final stages list:', stages);
            
            // Create stage filter toggles
            stages.forEach(stage => {
                const toggle = document.createElement('span');
                toggle.className = 'stage-toggle active';
                toggle.textContent = stage;
                toggle.dataset.stage = stage;
                toggle.onclick = () => toggleStageFilter(stage, toggle);
                toggle.title = `Toggle ${stage} tasks`;
                stageFilters.appendChild(toggle);
                console.log(`➕ Added stage filter: ${stage}`);
            });
            
            // Setup priority filter
            prioritySlider.value = 0;
            updatePriorityLabel(0);
            
            // Update UI
            updateFilterSummary();
            
            // Apply filters immediately to ensure all stages are visible initially
            applyFilters();
            
            console.log('✅ Hierarchy filters setup complete');
        }
        
        function extractStagesFromDOM() {
            const stages = new Set();
            const taskNodes = document.querySelectorAll('.tree-node[data-type="task"]');
            
            console.log(`🔍 Scanning ${taskNodes.length} task nodes for stages...`);
            
            taskNodes.forEach(node => {
                const stage = node.dataset.stage;
                if (stage && stage.trim()) {
                    stages.add(stage.trim());
                    console.log(`  Found stage: "${stage}"`);
                }
            });
            
            return Array.from(stages);
        }
        
        function extractStagesFromHierarchyData(hierarchy) {
            const stages = new Set();
            
            function scanNode(node) {
                if (!node) return;
                
                if (node.type === 'task' && node.stage) {
                    stages.add(node.stage);
                    console.log(`  Found stage in hierarchy data: "${node.stage}"`);
                }
                
                if (node.children && Array.isArray(node.children)) {
                    node.children.forEach(child => scanNode(child));
                }
            }
            
            if (hierarchy?.root) {
                console.log('🔍 Scanning hierarchy root for stages...');
                scanNode(hierarchy.root);
            }
            
            return Array.from(stages);
        }
        
        function toggleStageFilter(stage, toggleElement) {
            toggleElement.classList.toggle('active');
            applyFilters();
            updateFilterSummary();
            saveFilterState();
        }
        
        function toggleAllStages(show) {
            const toggles = document.querySelectorAll('.stage-toggle');
            toggles.forEach(toggle => {
                if (show) {
                    toggle.classList.add('active');
                } else {
                    toggle.classList.remove('active');
                }
            });
            applyFilters();
            updateFilterSummary();
            saveFilterState();
        }
        
        function updatePriorityFilter() {
            const slider = document.getElementById('prioritySlider');
            const level = parseInt(slider.value);
            updatePriorityLabel(level);
            applyFilters();
            updateFilterSummary();
            saveFilterState();
        }
        
        function updatePriorityLabel(level) {
            const label = document.getElementById('priorityLabel');
            const labels = ['Normal+', 'High+', 'Urgent+', 'Critical'];
            label.textContent = labels[level] || 'Normal+';
        }
        
        function applyFilters() {
            const stageToggles = document.querySelectorAll('.stage-toggle.active');
            const activeStages = Array.from(stageToggles).map(t => t.dataset.stage);
            const minPriority = parseInt(document.getElementById('prioritySlider').value || 0);
            
            console.log('Applying filters - Active stages:', activeStages, 'Min priority:', minPriority);
            
            const allNodes = document.querySelectorAll('.tree-node[data-type="task"]');
            console.log('Found', allNodes.length, 'task nodes to filter');
            
            allNodes.forEach(node => {
                const stage = node.dataset.stage;
                const priority = parseInt(node.dataset.priority || 0);
                
                const stageMatch = activeStages.length === 0 || activeStages.includes(stage);
                const priorityMatch = priority >= minPriority;
                
                console.log(`Task ${node.dataset.taskId}: stage="${stage}" (match: ${stageMatch}), priority=${priority} (match: ${priorityMatch})`);
                
                if (stageMatch && priorityMatch) {
                    node.classList.remove('filtered-hidden');
                } else {
                    node.classList.add('filtered-hidden');
                }
            });
            
            // Handle parent visibility (show parents if they have visible children)
            updateParentVisibility();
            
            console.log('Filter application complete');
        }
        
        function updateParentVisibility() {
            const allNodes = document.querySelectorAll('.tree-node');
            
            // First pass: hide all parents that have no visible children
            allNodes.forEach(node => {
                if (node.dataset.type === 'task') {
                    const children = node.querySelectorAll('.tree-node[data-type="task"]:not(.filtered-hidden)');
                    const hasVisibleChildren = children.length > 0;
                    const isVisibleItself = !node.classList.contains('filtered-hidden');
                    
                    if (!isVisibleItself && !hasVisibleChildren) {
                        // This node should remain hidden
                    } else if (!isVisibleItself && hasVisibleChildren) {
                        // Show this node because it has visible children
                        node.classList.remove('filtered-hidden');
                        node.classList.add('parent-visible');
                    }
                }
            });
        }
        
        function updateFilterSummary() {
            const activeStages = Array.from(document.querySelectorAll('.stage-toggle.active')).map(t => t.textContent);
            const allStages = document.querySelectorAll('.stage-toggle');
            const prioritySlider = document.getElementById('prioritySlider');
            const minPriority = prioritySlider ? parseInt(prioritySlider.value) : 0;
            const priorityLabels = ['Normal', 'High', 'Urgent', 'Critical'];
            
            const summary = document.getElementById('filterSummary');
            if (!summary) {
                console.warn('⚠️ Filter summary element not found');
                return;
            }
            
            let text = '';
            
            console.log(`📊 Updating filter summary: ${activeStages.length}/${allStages.length} stages active`);
            
            if (activeStages.length === 0) {
                text += 'No stages selected';
            } else if (activeStages.length === allStages.length) {
                text += 'All stages';
            } else {
                text += `Stages: ${activeStages.join(', ')}`;
            }
            
            text += ` | Priority: ${priorityLabels[minPriority] || 'Normal'}+`;
            
            summary.textContent = text;
            console.log(`📊 Filter summary updated: "${text}"`);
        }
        
        function saveFilterState() {
            if (!window.currentHierarchy) return;
            
            const hierarchyId = window.currentHierarchy.root.id;
            const hierarchyType = window.currentHierarchy.type;
            
            const state = {
                stages: Array.from(document.querySelectorAll('.stage-toggle.active')).map(t => t.dataset.stage),
                priority: parseInt(document.getElementById('prioritySlider').value)
            };
            
            localStorage.setItem(`hierarchy_filters_${hierarchyType}_${hierarchyId}`, JSON.stringify(state));
        }
        
        function applySavedFilters() {
            if (!window.currentHierarchy) {
                console.log('📋 No current hierarchy, skipping saved filters');
                return;
            }
            
            const hierarchyId = window.currentHierarchy.root.id;
            const hierarchyType = window.currentHierarchy.type;
            
            const saved = localStorage.getItem(`hierarchy_filters_${hierarchyType}_${hierarchyId}`);
            if (!saved) {
                console.log('📋 No saved filters found, using defaults (all stages active)');
                // Ensure all stages are active by default
                const stageToggles = document.querySelectorAll('.stage-toggle');
                console.log(`📋 Found ${stageToggles.length} stage toggles to activate`);
                stageToggles.forEach(toggle => {
                    toggle.classList.add('active');
                    console.log(`  ✅ Activated stage: ${toggle.dataset.stage}`);
                });
                applyFilters();
                updateFilterSummary();
                return;
            }
            
            try {
                const state = JSON.parse(saved);
                console.log('📋 Applying saved filter state:', state);
                
                // Apply stage filters
                const stageToggles = document.querySelectorAll('.stage-toggle');
                console.log(`📋 Found ${stageToggles.length} stage toggles to configure`);
                stageToggles.forEach(toggle => {
                    const stage = toggle.dataset.stage;
                    if (state.stages && state.stages.includes(stage)) {
                        toggle.classList.add('active');
                        console.log(`  ✅ Activated saved stage: ${stage}`);
                    } else {
                        toggle.classList.remove('active');
                        console.log(`  ❌ Deactivated stage: ${stage}`);
                    }
                });
                
                // Apply priority filter
                const prioritySlider = document.getElementById('prioritySlider');
                if (prioritySlider) {
                    prioritySlider.value = state.priority || 0;
                    updatePriorityLabel(state.priority || 0);
                    console.log(`📋 Set priority filter to: ${state.priority || 0}`);
                }
                
                // Apply filters
                applyFilters();
                updateFilterSummary();
            } catch (e) {
                console.warn('⚠️ Failed to load saved filter state:', e);
                // Fallback to showing all stages
                const stageToggles = document.querySelectorAll('.stage-toggle');
                console.log(`📋 Fallback: activating all ${stageToggles.length} stage toggles`);
                stageToggles.forEach(toggle => {
                    toggle.classList.add('active');
                    console.log(`  ✅ Fallback activated stage: ${toggle.dataset.stage}`);
                });
                applyFilters();
                updateFilterSummary();
            }
        }
        
        // Drag & Drop System
        let draggedElement = null;
        let draggedTaskId = null;
        let lastMoveOperation = null;
        let dragEnterTimeout = null;
        let dragLeaveTimeout = null;
        let currentDropTarget = null;
        
        function setupDragAndDrop() {
            const draggableElements = document.querySelectorAll('.tree-node-content.draggable');
            const dropTargets = document.querySelectorAll('.tree-node');
            
            // Setup drag events
            draggableElements.forEach(element => {
                element.addEventListener('dragstart', handleDragStart);
                element.addEventListener('dragend', handleDragEnd);
            });
            
            // Setup drop events with improved handling
            dropTargets.forEach(target => {
                target.addEventListener('dragover', handleDragOver);
                target.addEventListener('dragenter', handleDragEnter);
                target.addEventListener('dragleave', handleDragLeave);
                target.addEventListener('drop', handleDrop);
            });
        }
        
        function handleDragStart(e) {
            draggedElement = e.target.closest('.tree-node');
            
            // Try multiple ways to get the task ID
            let taskId = null;
            
            // Method 1: Direct from dataset
            taskId = draggedElement.dataset.taskId;
            draggedTaskId = taskId;
            draggedElement.classList.add('dragging');
            
            // Highlight all potential drop zones
            highlightPotentialDropZones();
            
            // Set drag data
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', draggedTaskId);
        }
        
        function handleDragEnd(e) {
            if (draggedElement) {
                draggedElement.classList.remove('dragging');
            }
            
            // Clean up all drag classes
            clearAllDropZoneHighlighting();
            
            // Clear timeouts
            if (dragEnterTimeout) {
                clearTimeout(dragEnterTimeout);
                dragEnterTimeout = null;
            }
            if (dragLeaveTimeout) {
                clearTimeout(dragLeaveTimeout);
                dragLeaveTimeout = null;
            }
            
            draggedElement = null;
            draggedTaskId = null;
            currentDropTarget = null;
        }
        
        function handleDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        }
        
        function handleDragEnter(e) {
            e.preventDefault();
            const targetNode = e.target.closest('.tree-node');
            
            if (!targetNode || targetNode === draggedElement) return;
            
            // Clear any pending leave timeout
            if (dragLeaveTimeout) {
                clearTimeout(dragLeaveTimeout);
                dragLeaveTimeout = null;
            }
            
            // Clear previous target highlighting
            if (currentDropTarget && currentDropTarget !== targetNode) {
                clearActiveDropTargetClasses(currentDropTarget);
            }
            
            currentDropTarget = targetNode;
            
            // Add appropriate visual feedback with more stable highlighting
            if (isValidDropTarget(targetNode)) {
                targetNode.classList.remove('potential-drop-zone', 'invalid-drop-target');
                targetNode.classList.add('drag-over', 'valid-drop-target');
            } else {
                targetNode.classList.remove('potential-drop-zone', 'drag-over', 'valid-drop-target');
                targetNode.classList.add('invalid-drop-target');
            }
        }
        
        function handleDragLeave(e) {
            const targetNode = e.target.closest('.tree-node');
            if (!targetNode) return;
            
            // Only clear if we're actually leaving the node (not just moving to a child)
            const rect = targetNode.getBoundingClientRect();
            const x = e.clientX;
            const y = e.clientY;
            
            // Check if we're still within the node bounds
            const stillInside = (
                x >= rect.left && 
                x <= rect.right && 
                y >= rect.top && 
                y <= rect.bottom
            );
            
            if (!stillInside) {
                // Use a small timeout to prevent flickering
                dragLeaveTimeout = setTimeout(() => {
                    if (targetNode === currentDropTarget) {
                        clearActiveDropTargetClasses(targetNode);
                        // Restore potential drop zone highlighting
                        if (isValidDropTarget(targetNode)) {
                            targetNode.classList.add('potential-drop-zone');
                        }
                        currentDropTarget = null;
                    }
                }, 100);
            }
        }
        
        function clearDropTargetClasses(node) {
            if (node) {
                node.classList.remove('drag-over', 'valid-drop-target', 'invalid-drop-target', 'potential-drop-zone');
            }
        }
        
        function clearActiveDropTargetClasses(node) {
            if (node) {
                node.classList.remove('drag-over', 'valid-drop-target', 'invalid-drop-target');
            }
        }
        
        function highlightPotentialDropZones() {
            // Highlight all nodes that could potentially be drop targets
            const allNodes = document.querySelectorAll('.tree-node');
            allNodes.forEach(node => {
                if (node !== draggedElement && isValidDropTarget(node)) {
                    node.classList.add('potential-drop-zone');
                }
            });
        }
        
        function clearAllDropZoneHighlighting() {
            const allNodes = document.querySelectorAll('.tree-node');
            allNodes.forEach(node => {
                clearDropTargetClasses(node);
            });
        }
        
        async function handleDrop(e) {
            e.preventDefault();
            const targetNode = e.target.closest('.tree-node');
            
            // Capture the draggedTaskId and oldParentId immediately before any async operations
            const taskIdToMove = draggedTaskId;
            const oldParentId = draggedElement.closest('.tree-node[data-type="task"]')?.dataset.taskId || 'root';
            
            if (!targetNode || !draggedElement || targetNode === draggedElement) {
                console.log('Drop cancelled: invalid target or same element');
                return;
            }
            
            if (!isValidDropTarget(targetNode)) {
                showToast('Invalid drop target. Cannot create circular dependency.', 'error');
                return;
            }
            
            // Get target task ID using the same robust method
            let targetTaskId = null;
            const targetType = targetNode.dataset.type;
            
            if (targetType === 'task') {
                // Try multiple methods to get target task ID
                targetTaskId = targetNode.dataset.taskId;
                
                if (!targetTaskId || targetTaskId === 'null' || targetTaskId === 'undefined' || targetTaskId === 'unknown') {
                    const nodeId = targetNode.dataset.nodeId;
                    if (nodeId) {
                        const match = nodeId.match(/node-task-(\d+)/);
                        if (match) {
                            targetTaskId = match[1];
                        }
                    }
                }
                
                if (!targetTaskId || targetTaskId === 'null' || targetTaskId === 'undefined' || targetTaskId === 'unknown') {
                    const labelElement = targetNode.querySelector('.tree-label small');
                    if (labelElement) {
                        const match = labelElement.textContent.match(/ID:\s*(\d+)/);
                        if (match) {
                            targetTaskId = match[1];
                        }
                    }
                }
                
                if (!targetTaskId || targetTaskId === 'null' || targetTaskId === 'undefined' || targetTaskId === 'unknown') {
                    const linkElement = targetNode.querySelector('.tree-label a');
                    if (linkElement && linkElement.href) {
                        const match = linkElement.href.match(/id=(\d+)/);
                        if (match) {
                            targetTaskId = match[1];
                        }
                    }
                }
            }
            
            // Determine new parent ID
            let newParentId;
            if (targetType === 'project') {
                newParentId = 'root'; // Special case for promoting to main task
            } else {
                newParentId = targetTaskId;
            }
            
            // Validate we have valid IDs
            if (!taskIdToMove || !/^\d+$/.test(taskIdToMove)) {
                showToast('Cannot move task: Invalid source task ID', 'error');
                console.error('Invalid taskIdToMove:', taskIdToMove);
                return;
            }
            
            if (targetType === 'task' && (!newParentId || !/^\d+$/.test(newParentId))) {
                showToast('Cannot move task: Invalid target task ID', 'error');
                console.error('Invalid newParentId:', newParentId);
                return;
            }
            
            // Show confirmation with custom modal
            const draggedTaskName = draggedElement.querySelector('.tree-label a').textContent;
            const targetName = targetNode.querySelector('.tree-label a').textContent;
            
            const message = targetType === 'project' 
                ? `Move "${draggedTaskName}" to become a main task in project "${targetName}"?`
                : `Move "${draggedTaskName}" to become a subtask of "${targetName}"?`;
            
            
            const confirmed = await showModal('Move Task', message, 'Move', 'Cancel');
            
            if (confirmed) {
                performTaskMove(taskIdToMove, newParentId, targetTaskId, oldParentId);
            }
            
            // Clean up
            clearAllDropZoneHighlighting();
        }
        
        function isValidDropTarget(targetNode) {
            if (!targetNode || !draggedElement) return false;
            
            // Can't drop on itself
            if (targetNode === draggedElement) return false;
            
            // Can't drop on a descendant (would create circular dependency)
            return !isDescendant(targetNode, draggedElement);
        }
        
        function isDescendant(potentialDescendant, ancestor) {
            let current = potentialDescendant.parentElement;
            
            while (current) {
                if (current === ancestor) return true;
                current = current.parentElement;
            }
            
            return false;
        }
        
        // State Management for Partial Updates
        const HierarchyState = {
            expandedNodes: new Set(),
            scrollPosition: 0,
            activeFilters: {},
            
            captureState() {
                // Capture expanded nodes
                this.expandedNodes.clear();
                document.querySelectorAll('.tree-children:not(.collapsed)').forEach(child => {
                    const nodeId = child.id.replace('children-', '');
                    this.expandedNodes.add(nodeId);
                });
                
                // Capture scroll position
                const container = document.getElementById('hierarchyContainer');
                this.scrollPosition = container ? container.scrollTop : 0;
                
                // Capture active filters
                this.activeFilters = {
                    stages: Array.from(document.querySelectorAll('.stage-toggle.active')).map(t => t.dataset.stage),
                    priority: parseInt(document.getElementById('prioritySlider')?.value || 0)
                };
                
                console.log('📸 State captured:', {
                    expandedNodes: Array.from(this.expandedNodes),
                    scrollPosition: this.scrollPosition,
                    activeFilters: this.activeFilters
                });
            },
            
            restoreState() {
                // Restore expanded nodes
                this.expandedNodes.forEach(nodeId => {
                    const childrenContainer = document.getElementById('children-' + nodeId);
                    const toggleButton = document.querySelector('[data-node-id="' + nodeId + '"] .tree-toggle');
                    
                    if (childrenContainer && toggleButton) {
                        childrenContainer.classList.remove('collapsed');
                        toggleButton.textContent = '▼';
                    }
                });
                
                // Restore scroll position
                const container = document.getElementById('hierarchyContainer');
                if (container) {
                    container.scrollTop = this.scrollPosition;
                }
                
                // Restore filters
                if (this.activeFilters.stages) {
                    document.querySelectorAll('.stage-toggle').forEach(toggle => {
                        if (this.activeFilters.stages.includes(toggle.dataset.stage)) {
                            toggle.classList.add('active');
                        } else {
                            toggle.classList.remove('active');
                        }
                    });
                }
                
                if (this.activeFilters.priority !== undefined) {
                    const slider = document.getElementById('prioritySlider');
                    if (slider) {
                        slider.value = this.activeFilters.priority;
                        updatePriorityLabel(this.activeFilters.priority);
                    }
                }
                
                // Reapply filters
                applyFilters();
                updateFilterSummary();
                
                console.log('🔄 State restored');
            }
        };

        function performTaskMove(taskId, newParentId, targetTaskId, oldParentId) {
            // Validate inputs before making API call
            console.log('🔄 performTaskMove called with:', { taskId, newParentId, targetTaskId, oldParentId });
            
            // Strict validation
            if (!taskId || taskId === 'null' || taskId === 'undefined' || taskId === 'unknown' || !/^\d+$/.test(taskId)) {
                console.error('❌ Invalid taskId for move operation:', taskId);
                showToast('Error: Invalid task ID for move operation', 'error');
                return;
            }
            
            if (!newParentId || (newParentId !== 'root' && (newParentId === 'null' || newParentId === 'undefined' || newParentId === 'unknown' || !/^\d+$/.test(newParentId)))) {
                console.error('❌ Invalid newParentId for move operation:', newParentId);
                showToast('Error: Invalid parent ID for move operation', 'error');
                return;
            }
            
            // Capture current state before move
            HierarchyState.captureState();
            
            // Perform optimistic update
            const rollbackData = performOptimisticMove(taskId, newParentId, oldParentId);
            
            // Prepare API call with partial update support
            const params = new URLSearchParams({
                task_id: taskId,
                new_parent_id: newParentId,
                old_parent_id: oldParentId || '',
                partial: 'true'
            });
            
            // Add project ID if moving to project root
            if (newParentId === 'root' && window.currentHierarchy && window.currentHierarchy.type === 'project') {
                params.append('project_id', window.currentHierarchy.root.id);
            }
            
            const apiUrl = '/api/move-task?' + params.toString();
            fetch(apiUrl)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (data.partial_update && data.updates) {
                            // Apply server-side partial updates
                            applyPartialUpdates(data.updates);
                            
                            // Restore state
                            HierarchyState.restoreState();
                            
                            // Store for undo
                            lastMoveOperation = {
                                taskId: taskId,
                                oldParentId: oldParentId,
                                newParentId: newParentId,
                                timestamp: Date.now(),
                                operationId: data.operation_id
                            };
                            
                            showToast(data.message || 'Task moved successfully', 'success');
                        } else {
                            // Fallback to full refresh for legacy response
                            refreshCurrentHierarchy();
                            showToast(data.message || 'Task moved successfully', 'success');
                        }
                    } else {
                        // Rollback optimistic changes
                        rollbackOptimisticMove(rollbackData);
                        showToast('Move failed: ' + (data.error || 'Unknown error'), 'error');
                    }
                })
                .catch(error => {
                    // Rollback optimistic changes
                    rollbackOptimisticMove(rollbackData);
                    console.error('❌ Move API error:', error);
                    showToast('Move failed: ' + error.message, 'error');
                });
        }

        function performOptimisticMove(taskId, newParentId, oldParentId) {
            console.log('⚡ Performing optimistic move:', { taskId, newParentId, oldParentId });
            
            const draggedNode = document.querySelector(`[data-task-id="${taskId}"]`);
            if (!draggedNode) {
                console.warn('Could not find dragged node for optimistic update');
                return null;
            }
            
            // Store rollback data
            const rollbackData = {
                node: draggedNode.cloneNode(true),
                originalParent: draggedNode.parentElement,
                originalNextSibling: draggedNode.nextElementSibling
            };
            
            // Add visual feedback
            draggedNode.style.opacity = '0.7';
            draggedNode.style.transform = 'scale(0.98)';
            draggedNode.style.transition = 'all 0.3s ease';
            
            // Move the node in DOM (simplified optimistic update)
            if (newParentId === 'root') {
                // Moving to project root - find project children container
                const projectChildren = document.querySelector('.tree-view > .tree-node .tree-children');
                if (projectChildren) {
                    projectChildren.appendChild(draggedNode);
                }
            } else {
                // Moving to another task
                const newParentChildren = document.getElementById(`children-node-task-${newParentId}`);
                if (newParentChildren) {
                    newParentChildren.appendChild(draggedNode);
                }
            }
            
            return rollbackData;
        }

        function rollbackOptimisticMove(rollbackData) {
            if (!rollbackData) return;
            
            console.log('🔄 Rolling back optimistic move');
            
            // Find current node and remove it
            const currentNode = document.querySelector(`[data-task-id="${rollbackData.node.dataset.taskId}"]`);
            if (currentNode) {
                currentNode.remove();
            }
            
            // Restore original node at original position
            if (rollbackData.originalNextSibling) {
                rollbackData.originalParent.insertBefore(rollbackData.node, rollbackData.originalNextSibling);
            } else {
                rollbackData.originalParent.appendChild(rollbackData.node);
            }
            
            // Remove visual feedback
            rollbackData.node.style.opacity = '';
            rollbackData.node.style.transform = '';
            rollbackData.node.style.transition = '';
        }

        function applyPartialUpdates(updates) {
            console.log('🔧 Applying partial updates:', updates);
            
            try {
                // Handle removal from old parent
                if (updates.removed_from) {
                    const { parent_id, task_id } = updates.removed_from;
                    const nodeToRemove = document.querySelector(`[data-task-id="${task_id}"]`);
                    if (nodeToRemove) {
                        // Add removal animation
                        nodeToRemove.style.transition = 'all 0.3s ease';
                        nodeToRemove.style.opacity = '0';
                        nodeToRemove.style.transform = 'scale(0.8)';
                        
                        setTimeout(() => {
                            if (nodeToRemove.parentElement) {
                                nodeToRemove.remove();
                            }
                        }, 300);
                    }
                }
                
                // Handle addition to new parent
                if (updates.added_to && updates.moved_task_data) {
                    const { parent_id, parent_type } = updates.added_to;
                    const taskData = updates.moved_task_data;
                    
                    // Generate HTML for the moved task
                    const taskHtml = renderTreeNode(taskData, 1, false);
                    
                    // Find target container
                    let targetContainer;
                    if (parent_type === 'project' || parent_id === 'root') {
                        targetContainer = document.querySelector('.tree-view > .tree-node .tree-children');
                    } else {
                        targetContainer = document.getElementById(`children-node-task-${parent_id}`);
                    }
                    
                    if (targetContainer && taskHtml) {
                        // Create temporary container for the new node
                        const tempDiv = document.createElement('div');
                        tempDiv.innerHTML = taskHtml;
                        const newNode = tempDiv.firstElementChild;
                        
                        // Add entrance animation
                        newNode.style.opacity = '0';
                        newNode.style.transform = 'scale(0.8)';
                        newNode.style.transition = 'all 0.3s ease';
                        
                        targetContainer.appendChild(newNode);
                        
                        // Trigger entrance animation
                        setTimeout(() => {
                            newNode.style.opacity = '1';
                            newNode.style.transform = 'scale(1)';
                        }, 50);
                        
                        // Setup drag & drop for new node
                        setupDragAndDrop();
                    }
                }
                
                // Handle node metadata updates
                if (updates.updated_nodes) {
                    updates.updated_nodes.forEach(update => {
                        const { node_id, updates: nodeUpdates } = update;
                        const node = document.querySelector(`[data-node-id="${node_id}"]`);
                        
                        if (node && nodeUpdates.child_count_change) {
                            // Update child count in metadata if displayed
                            const metadata = node.querySelector('.tree-metadata');
                            if (metadata) {
                                // This would update task count displays if they exist
                                console.log(`Updated child count for ${node_id} by ${nodeUpdates.child_count_change}`);
                            }
                        }
                    });
                }
                
                console.log('✅ Partial updates applied successfully');
                
            } catch (error) {
                console.error('❌ Error applying partial updates:', error);
                // Fallback to full refresh on error
                refreshCurrentHierarchy();
            }
        }
        
        function showMoveSuccess(message) {
            showToast(message, 'success', 4000);
        }
        
        function refreshCurrentHierarchy() {
            if (!window.currentHierarchy) return;
            
            const hierarchyType = window.currentHierarchy.type;
            const hierarchyId = window.currentHierarchy.root.id;
            
            console.log('🔄 Refreshing hierarchy (fallback)');
            
            // Capture state before refresh
            HierarchyState.captureState();
            
            // Reload the hierarchy
            loadHierarchy(hierarchyType, hierarchyId);
        }
        
        // Custom Modal System
        let modalCallback = null;
        
        function showModal(title, message, confirmText = 'Confirm', cancelText = 'Cancel') {
            return new Promise((resolve) => {
                document.getElementById('modalTitle').textContent = title;
                document.getElementById('modalBody').textContent = message;
                document.getElementById('modalConfirmBtn').textContent = confirmText;
                
                modalCallback = resolve;
                document.getElementById('customModal').classList.add('show');
            });
        }
        
        function closeModal() {
            document.getElementById('customModal').classList.remove('show');
            if (modalCallback) {
                modalCallback(false);
                modalCallback = null;
            }
        }
        
        function confirmModal() {
            document.getElementById('customModal').classList.remove('show');
            if (modalCallback) {
                modalCallback(true);
                modalCallback = null;
            }
        }
        
        // Toast Notification System
        function showToast(message, type = 'success', duration = 3000) {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            
            const toastId = 'toast-' + Date.now();
            toast.id = toastId;
            
            const icon = {
                'success': '✅',
                'error': '❌',
                'warning': '⚠️',
                'info': 'ℹ️'
            }[type] || '✅';
            
            toast.innerHTML = `
                <div class="toast-header">
                    <div class="toast-title">${icon} ${type.charAt(0).toUpperCase() + type.slice(1)}</div>
                    <button class="toast-close" onclick="closeToast('${toastId}')">&times;</button>
                </div>
                <div class="toast-body">${message}</div>
            `;
            
            container.appendChild(toast);
            
            // Trigger animation
            setTimeout(() => {
                toast.classList.add('show');
            }, 10);
            
            // Auto-remove
            if (duration > 0) {
                setTimeout(() => {
                    closeToast(toastId);
                }, duration);
            }
            
            return toastId;
        }
        
        function closeToast(toastId) {
            const toast = document.getElementById(toastId);
            if (toast) {
                toast.classList.remove('show');
                setTimeout(() => {
                    if (toast.parentNode) {
                        toast.parentNode.removeChild(toast);
                    }
                }, 300);
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
