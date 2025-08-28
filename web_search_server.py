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
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import base64
import mimetypes

# Import our existing search functionality
from text_search import OdooTextSearch


class WebSearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the web search interface"""
    
    # Class-level searcher instance to persist across requests
    _searcher = None
    
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
        """Handle search API requests"""
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

            # Log search request to console
            print(f"🔍 Web search request: '{search_term}' (type: {search_type}, since: {since})")

            # Use class-level searcher instance to persist caches
            try:
                if WebSearchHandler._searcher is None:
                    WebSearchHandler._searcher = OdooTextSearch(verbose=True)
                searcher = WebSearchHandler._searcher

            except Exception as e:
                self.send_json_response({'error': f'Failed to connect to Odoo: {str(e)}'}, 500)
                return
            
            # Perform search
            results = searcher.full_text_search(
                search_term=search_term,
                since=since,
                search_type=search_type,
                include_descriptions=include_descriptions,
                include_logs=include_logs,
                include_files=include_files,
                file_types=file_types,
                limit=limit
            )
            
            # Add URLs to results using the searcher instance
            self.add_urls_to_results(results, searcher)

            # Make results JSON-safe
            json_safe_results = self.make_results_json_safe(results)

            # Calculate totals
            total_results = sum(len(json_safe_results.get(key, [])) for key in ['projects', 'tasks', 'messages', 'files'])
            
            response = {
                'success': True,
                'results': json_safe_results,
                'total': total_results,
                'search_params': {
                    'search_term': search_term,
                    'since': since,
                    'type': search_type,
                    'include_descriptions': include_descriptions,
                    'include_logs': include_logs,
                    'include_files': include_files,
                    'file_types': file_types,
                    'limit': limit
                }
            }

            self.send_json_response(response)
            
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
    
    def handle_download_api(self, query_string):
        """Handle file download API requests"""
        try:
            params = parse_qs(query_string)
            file_id = params.get('id', [''])[0]
            
            if not file_id:
                self.send_json_response({'error': 'File ID is required'}, 400)
                return
            
            # Use class-level searcher instance to persist caches
            try:
                if WebSearchHandler._searcher is None:
                    WebSearchHandler._searcher = OdooTextSearch(verbose=True)
                searcher = WebSearchHandler._searcher

            except Exception as e:
                self.send_json_response({'error': f'Failed to connect to Odoo: {str(e)}'}, 500)
                return
            
            # Get file info first
            attachment_records = searcher.attachments.search_records([('id', '=', int(file_id))])
            
            if not attachment_records:
                self.send_json_response({'error': 'File not found'}, 404)
                return
            
            attachment = attachment_records[0]
            file_name = getattr(attachment, 'name', f'file_{file_id}')
            
            # Get file data
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
            settings = {
                'host': os.getenv('ODOO_HOST', ''),
                'database': os.getenv('ODOO_DATABASE', ''),
                'user': os.getenv('ODOO_USER', ''),
                'password': '***' if os.getenv('ODOO_PASSWORD') else ''
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
            
            # Update .env file
            env_lines = []
            if os.path.exists('.env'):
                with open('.env', 'r') as f:
                    env_lines = f.readlines()
            
            # Update or add settings
            settings_map = {
                'ODOO_HOST': data.get('host', ''),
                'ODOO_DATABASE': data.get('database', ''),
                'ODOO_USER': data.get('user', ''),
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
            
            # Write back to .env
            with open('.env', 'w') as f:
                f.writelines(env_lines)
            
            # Reload environment variables
            from dotenv import load_dotenv
            load_dotenv(override=True)
            
            # Reset searcher to use new settings
            WebSearchHandler._searcher = None
            
            self.send_json_response({'success': True, 'message': 'Settings updated and server reloaded successfully'})
            
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

    def add_urls_to_results(self, results, searcher):
        """Add URLs to search results"""
        if not searcher:
            return
        
        # Add URLs to projects
        for project in results.get('projects', []):
            project['url'] = searcher.get_project_url(project['id'])
        
        # Add URLs to tasks
        for task in results.get('tasks', []):
            task['url'] = searcher.get_task_url(task['id'])
            if task.get('project_id'):
                task['project_url'] = searcher.get_project_url(task['project_id'])
        
        # Add URLs to messages
        for message in results.get('messages', []):
            message['url'] = searcher.get_message_url(message['id'])
            if message.get('model') == 'project.project' and message.get('res_id'):
                message['related_url'] = searcher.get_project_url(message['res_id'])
            elif message.get('model') == 'project.task' and message.get('res_id'):
                message['related_url'] = searcher.get_task_url(message['res_id'])
        
        # Add URLs to files
        for file in results.get('files', []):
            file['url'] = searcher.get_file_url(file['id'])
            file['download_url'] = f'/api/download?id={file["id"]}'
            if file.get('related_type') == 'Project' and file.get('related_id'):
                file['related_url'] = searcher.get_project_url(file['related_id'])
            elif file.get('related_type') == 'Task' and file.get('related_id'):
                file['related_url'] = searcher.get_task_url(file['related_id'])
                if file.get('project_id'):
                    file['project_url'] = searcher.get_project_url(file['project_id'])
    
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
        
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        
        .modal-content {
            background-color: var(--bg-color);
            margin: 5% auto;
            padding: 30px;
            border-radius: 12px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        
        .close:hover {
            color: var(--text-color);
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
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Odoo Search</h1>
            <div class="header-controls">
                <button class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">🌓</button>
                <button class="btn btn-secondary" onclick="openSettings()">⚙️ Settings</button>
            </div>
        </div>
        
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
            </div>
            
            <div class="search-history" id="searchHistory">
                <label>Recent searches:</label>
                <div id="historyItems"></div>
            </div>
        </form>
        
        <div id="results" class="results"></div>
    </div>
    
    <!-- Settings Modal -->
    <div id="settingsModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Settings</h2>
                <span class="close" onclick="closeSettings()">&times;</span>
            </div>
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
                    <button type="submit" class="btn btn-primary">💾 Save Settings</button>
                    <button type="button" class="btn btn-secondary" onclick="closeSettings()">Cancel</button>
                </div>
            </form>
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
        
        // Settings management
        function openSettings() {
            document.getElementById('settingsModal').style.display = 'block';
            loadSettings();
        }
        
        function closeSettings() {
            document.getElementById('settingsModal').style.display = 'none';
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
                    closeSettings();
                } else {
                    alert('Error saving settings: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error saving settings:', error);
                alert('Error saving settings');
            });
        }
        
        // Search functionality
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
            
            // Show loading
            document.getElementById('results').innerHTML = '<div class="loading">Searching...</div>';
            
            // Perform search
            fetch('/api/search?' + params.toString())
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Cache the results
                        cacheSearchResults(searchParams.q, searchParams, data.results);
                        
                        // Display results
                        displayResults(data);
                        
                        // Update search history to show cached status
                        loadSearchHistory();
                    } else {
                        document.getElementById('results').innerHTML = 
                            `<div class="error">Error: ${data.error}</div>`;
                    }
                })
                .catch(error => {
                    console.error('Search error:', error);
                    document.getElementById('results').innerHTML = 
                        `<div class="error">Search failed: ${error.message}</div>`;
                });
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
            if (type === 'file' && item.download_url) {
                html += `<a href="${item.download_url}" class="download-btn">📥 Download</a>`;
            }
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
                // Convert HTML to markdown-like text for better display
                let cleanDescription = description
                    .replace(/<br\s*\/?>/gi, '\n')
                    .replace(/<\/p>/gi, '\n')
                    .replace(/<p[^>]*>/gi, '')
                    .replace(/<strong[^>]*>(.*?)<\/strong>/gi, '**$1**')
                    .replace(/<b[^>]*>(.*?)<\/b>/gi, '**$1**')
                    .replace(/<em[^>]*>(.*?)<\/em>/gi, '*$1*')
                    .replace(/<i[^>]*>(.*?)<\/i>/gi, '*$1*')
                    .replace(/<u[^>]*>(.*?)<\/u>/gi, '_$1_')
                    .replace(/<code[^>]*>(.*?)<\/code>/gi, '`$1`')
                    .replace(/<a[^>]*href=["']([^"']*)["'][^>]*>(.*?)<\/a>/gi, '[$2]($1)')
                    .replace(/<li[^>]*>(.*?)<\/li>/gi, '- $1')
                    .replace(/<ul[^>]*>|<\/ul>|<ol[^>]*>|<\/ol>/gi, '')
                    .replace(/<div[^>]*>|<\/div>/gi, '\n')
                    .replace(/<[^>]+>/g, '')
                    .replace(/&nbsp;/g, ' ')
                    .replace(/&amp;/g, '&')
                    .replace(/&lt;/g, '<')
                    .replace(/&gt;/g, '>')
                    .replace(/&quot;/g, '"')
                    .replace(/&#39;/g, "'")
                    .replace(/\\n\\s*\\n\\s*\\n/g, '\\n\\n')
                    .trim();
                
                const truncated = cleanDescription.length > 300 ? cleanDescription.substring(0, 300) + '...' : cleanDescription;
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
        
        // Cache management
        function clearCache() {
            if (confirm('Clear all cached search results?')) {
                localStorage.removeItem('cachedSearchResults');
                localStorage.removeItem('searchHistory');
                loadSearchHistory();
                alert('Cache and search history cleared successfully!');
            }
        }
        
        // Initialize
        loadSearchHistory();
        
        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('settingsModal');
            if (event.target === modal) {
                closeSettings();
            }
        }
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
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("⚠️  No .env file found. You can configure settings through the web interface.")
        print("   Or create a .env file with your Odoo credentials.")
    
    # Start server
    server = WebSearchServer(host=args.host, port=args.port)
    server.start(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
