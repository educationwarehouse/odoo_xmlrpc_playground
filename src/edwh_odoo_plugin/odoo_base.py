#!/usr/bin/env python3
"""
Odoo Base Module - Shared Functionality
=======================================

Shared functionality for Odoo project search tools.
Contains common connection, configuration, and utility functions.

Author: Based on search.py and text_search.py
Date: August 2025
"""

import os
import re
import base64
import html
import secrets
import hashlib
import logging
from pathlib import Path
from dotenv import load_dotenv
from openerp_proxy import Client
from openerp_proxy.ext.all import *
import warnings
import time

# Configure secure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Suppress the pkg_resources deprecation warning from odoo_rpc_client globally
warnings.filterwarnings("ignore", 
                      message="pkg_resources is deprecated as an API.*",
                      category=UserWarning)


class ConfigManager:
    """Centralized configuration management with security hardening"""
    
    @staticmethod
    def get_config_path():
        """Get the standard config file path"""
        return Path.home() / ".config/edwh/edwh_odoo_plugin.env"
    
    @staticmethod
    def _validate_config_security(config_path):
        """Validate configuration file security"""
        # Check file permissions (should be 600 - owner read/write only)
        stat_info = config_path.stat()
        if stat_info.st_mode & 0o077:  # Check if group/other have any permissions
            logger.warning(f"Configuration file has insecure permissions: {oct(stat_info.st_mode)}")
            # Attempt to fix permissions
            try:
                config_path.chmod(0o600)
                logger.info("Fixed configuration file permissions to 600")
            except Exception as e:
                logger.error(f"Could not fix file permissions: {e}")
    
    @staticmethod
    def _sanitize_config_value(key, value):
        """Sanitize configuration values"""
        if not value:
            return value
            
        # Remove any potential injection characters
        if key in ['host', 'database', 'user']:
            # Allow only alphanumeric, dots, hyphens, underscores
            sanitized = re.sub(r'[^a-zA-Z0-9.\-_@]', '', str(value))
            if sanitized != value:
                logger.warning(f"Sanitized config value for {key}")
            return sanitized
        elif key == 'protocol':
            # Only allow known protocols
            if value not in ['xml-rpc', 'xml-rpcs']:
                logger.error(f"Invalid protocol: {value}")
                return 'xml-rpcs'  # Default to secure
        elif key == 'port':
            # Validate port range
            try:
                port = int(value)
                if not (1 <= port <= 65535):
                    logger.error(f"Invalid port: {port}")
                    return 443  # Default to HTTPS port
                return port
            except ValueError:
                logger.error(f"Invalid port format: {value}")
                return 443
        
        return value
    
    @staticmethod
    def load_config(verbose=False):
        """Load configuration with validation and security checks"""
        config_path = ConfigManager.get_config_path()
        
        if not config_path.exists():
            logger.error("No configuration file found")
            if verbose:
                print(f"❌ No configuration file found!")
                print(f"   Expected location: {config_path.absolute()}")
                print(f"   Please run: edwh odoo.setup")
            raise FileNotFoundError("No configuration file found. Run 'edwh odoo.setup' to create one.")
        
        # Validate file security
        ConfigManager._validate_config_security(config_path)
        
        load_dotenv(config_path)
        
        if verbose:
            print(f"📁 Loading configuration from: {config_path.absolute()}")
        
        # Load and sanitize configuration
        raw_config = {
            'host': os.getenv('ODOO_HOST'),
            'database': os.getenv('ODOO_DATABASE'),
            'user': os.getenv('ODOO_USER'),
            'password': os.getenv('ODOO_PASSWORD'),
            'port': os.getenv('ODOO_PORT', '443'),
            'protocol': os.getenv('ODOO_PROTOCOL', 'xml-rpcs')
        }
        
        # Sanitize all values
        config = {}
        for key, value in raw_config.items():
            config[key] = ConfigManager._sanitize_config_value(key, value)
        
        # Validate required fields
        missing = [k for k, v in config.items() if not v and k != 'port']
        if missing:
            logger.error(f"Missing required configuration: {missing}")
            if verbose:
                print(f"❌ Configuration incomplete!")
                print(f"   Missing required variables: {', '.join(missing)}")
                print(f"   Please run: edwh odoo.setup")
            raise ValueError(f"Missing required configuration variables: {', '.join(missing)}. Run 'edwh odoo.setup' to configure.")
        
        # Validate host format
        if config['host'] and not re.match(r'^[a-zA-Z0-9.\-]+$', config['host']):
            logger.error("Invalid host format")
            raise ValueError("Invalid host format")
        
        return config


class DomainBuilder:
    """Utility class for building Odoo search domains"""
    
    @staticmethod
    def combine_with_and(base_domain, *additional_conditions):
        """Combine domain with additional conditions using AND"""
        domain = base_domain[:]
        for condition in additional_conditions:
            if condition:
                domain = ['&'] + domain + [condition]
        return domain
    
    @staticmethod
    def combine_with_or(*domains):
        """Combine multiple domains with OR"""
        valid_domains = [d for d in domains if d]
        if len(valid_domains) == 1:
            return valid_domains[0]
        elif len(valid_domains) == 2:
            return ['|'] + valid_domains[0] + valid_domains[1]
        elif len(valid_domains) > 2:
            # Build nested OR structure
            result = valid_domains[0]
            for domain in valid_domains[1:]:
                result = ['|'] + result + domain
            return result
        return []
    
    @staticmethod
    def text_search_domain(search_term, fields, include_descriptions=True):
        """Build text search domain for multiple fields"""
        if not include_descriptions:
            fields = [f for f in fields if 'description' not in f]
        
        if len(fields) == 1:
            return [(fields[0], 'ilike', search_term)]
        else:
            conditions = [(field, 'ilike', search_term) for field in fields]
            return ['|'] * (len(conditions) - 1) + conditions
    
    @staticmethod
    def date_filter_domain(since_date, date_field='write_date'):
        """Build date filter domain"""
        if since_date:
            return [(date_field, '>=', since_date.strftime('%Y-%m-%d %H:%M:%S'))]
        return []


class ErrorHandler:
    """Standardized error handling"""
    
    @staticmethod
    def handle_search_error(operation, error, verbose=False):
        """Standard error handling for search operations"""
        print(f"❌ Error in {operation}: {error}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        return []
    
    @staticmethod
    def handle_connection_error(error, verbose=False):
        """Standard error handling for connection issues"""
        print(f"❌ Connection failed: {error}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        raise


class OdooBase:
    """
    Base class for Odoo connections and common functionality
    
    Provides:
    - Connection management
    - Configuration loading
    - Model shortcuts
    - URL generation
    - File size formatting
    - Shared utilities for user extraction, task enrichment, etc.
    """

    def __init__(self, verbose=False):
        """Initialize with .env configuration"""
        self.verbose = verbose
        
        # Load configuration using centralized manager
        config = ConfigManager.load_config(verbose)
        
        self.host = config['host']
        self.database = config['database']
        self.user = config['user']
        self.password = config['password']
        self.port = config['port']
        self.protocol = config['protocol']

        # Build base URL for links
        self.base_url = f"https://{self.host}"

        # Simple in-memory caches
        self._user_name_cache = {}  # user_id -> (ts, name)
        self._user_name_ttl = 300   # seconds

        self._connect()

    def _connect(self):
        """Connect to Odoo with improved error handling"""
        try:
            if self.verbose:
                print(f"🔌 Connecting to Odoo...")
                print(f"   Host: {self.host}")
                print(f"   Database: {self.database}")
                print(f"   User: {self.user}")

            # Add connection timeout and retry logic
            import socket
            socket.setdefaulttimeout(30)  # 30 second timeout
            
            self.client = Client(
                host=self.host, 
                dbname=self.database, 
                user=self.user, 
                pwd=self.password, 
                port=self.port, 
                protocol=self.protocol
            )

            if self.verbose:
                print(f"✅ Connected as: {self.client.user.name} (ID: {self.client.uid})")

            # Model shortcuts with error handling
            try:
                self.projects = self.client['project.project']
                self.tasks = self.client['project.task']
                self.attachments = self.client['ir.attachment']
                self.messages = self.client['mail.message']
            except Exception as model_error:
                logger.warning(f"Error accessing models: {model_error}")
                raise

        except Exception as e:
            ErrorHandler.handle_connection_error(e, self.verbose)

    def extract_user_from_task(self, task):
        """Extract user ID and name from task using safe field access"""
        user_id = None
        user_name = 'Unassigned'
        
        # Try user fields in order of reliability with safer access
        for field_name in ['user_ids', 'user_id', 'create_uid', 'write_uid']:
            try:
                if not hasattr(task, field_name):
                    continue
                    
                user_field = getattr(task, field_name, None)
                if not user_field:
                    continue
                
                # Handle RecordList (user_ids field) - be more careful
                if hasattr(user_field, '__len__'):
                    try:
                        if len(user_field) > 0:
                            first_user = user_field[0]
                            if hasattr(first_user, 'id'):
                                user_id = first_user.id
                                if self.verbose:
                                    print(f"🔍 Found user ID {user_id} via {field_name}[0].id")
                                break
                    except (IndexError, AttributeError):
                        continue
                        
                # Handle direct Record objects - safer access
                elif hasattr(user_field, 'id'):
                    try:
                        # Avoid accessing partial objects that might cause server calls
                        if not str(user_field).startswith('functools.partial'):
                            user_id = user_field.id
                            if self.verbose:
                                print(f"🔍 Found user ID {user_id} via {field_name}.id")
                            break
                    except AttributeError:
                        continue
                        
                # Handle integer IDs
                elif isinstance(user_field, int) and user_field > 0:
                    user_id = user_field
                    if self.verbose:
                        print(f"🔍 Found user ID {user_id} via {field_name} (int)")
                    break
                    
            except Exception as field_error:
                if self.verbose:
                    print(f"⚠️ Error accessing field {field_name}: {field_error}")
                continue
        
        # Get user name from cache or direct lookup - with error handling
        if user_id and isinstance(user_id, int) and user_id > 0:
            try:
                user_name = self._get_user_name(user_id)
            except Exception as e:
                if self.verbose:
                    print(f"⚠️ Error getting user name for ID {user_id}: {e}")
                user_name = f'User {user_id}'
        
        return user_id, user_name

    def enrich_task_data(self, task, search_term=None):
        """Unified task data enrichment"""
        # Handle functools.partial objects
        if hasattr(task, 'id') and not hasattr(task, 'name'):
            task = self.tasks.browse(task.id)
        
        # Extract user info
        user_id, user_name = self.extract_user_from_task(task)
        
        # Extract project info
        project_name = 'No project'
        project_id = None
        if hasattr(task, 'project_id') and task.project_id:
            try:
                project_name = task.project_id.name if hasattr(task.project_id, 'name') else f'Project {task.project_id.id}'
                project_id = task.project_id.id if hasattr(task.project_id, 'id') else task.project_id
            except:
                project_name = 'Project (unavailable)'
        
        # Extract stage info
        stage_name = 'No stage'
        stage_id = None
        if hasattr(task, 'stage_id') and task.stage_id:
            try:
                if hasattr(task.stage_id, 'name'):
                    stage_name = task.stage_id.name
                    stage_id = task.stage_id.id if hasattr(task.stage_id, 'id') else task.stage_id
                else:
                    stage_id = task.stage_id
                    stage_name = f'Stage {stage_id}'
            except:
                stage_name = 'Stage (unavailable)'
        
        # Convert description to markdown
        raw_description = getattr(task, 'description', '') or ''
        markdown_description = self.html_to_markdown(raw_description) if raw_description else ''
        
        enriched_data = {
            'id': task.id,
            'name': getattr(task, 'name', f'Task {task.id}'),
            'description': markdown_description,
            'project_name': project_name,
            'project_id': project_id,
            'stage': stage_name,
            'stage_id': stage_id,
            'user': user_name,
            'user_id': user_id,
            'priority': getattr(task, 'priority', '0'),
            'create_date': str(getattr(task, 'create_date', '')) if getattr(task, 'create_date', None) else '',
            'write_date': str(getattr(task, 'write_date', '')) if getattr(task, 'write_date', None) else '',
            'type': 'task'
        }
        
        if search_term:
            enriched_data.update({
                'search_term': search_term,
                'match_in_name': search_term.lower() in enriched_data['name'].lower(),
                'match_in_description': search_term.lower() in enriched_data['description'].lower()
            })
        
        return enriched_data

    def _sanitize_filename(self, filename):
        """Sanitize filename to prevent path traversal attacks"""
        if not filename:
            return "unknown_file"
        
        # Remove path separators and dangerous characters
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
        sanitized = re.sub(r'\.\.+', '.', sanitized)  # Remove multiple dots
        sanitized = sanitized.strip('. ')  # Remove leading/trailing dots and spaces
        
        # Ensure filename is not empty and not a reserved name
        reserved_names = ['CON', 'PRN', 'AUX', 'NUL'] + [f'COM{i}' for i in range(1, 10)] + [f'LPT{i}' for i in range(1, 10)]
        if not sanitized or sanitized.upper() in reserved_names:
            sanitized = f"file_{secrets.token_hex(4)}"
        
        # Limit filename length
        if len(sanitized) > 255:
            name, ext = os.path.splitext(sanitized)
            sanitized = name[:250] + ext
        
        return sanitized
    
    def _validate_download_path(self, output_path, base_dir=None):
        """Validate download path to prevent directory traversal"""
        if base_dir is None:
            base_dir = Path.cwd() / "downloads"
        
        try:
            # Resolve paths to absolute
            base_path = Path(base_dir).resolve()
            target_path = Path(output_path).resolve()
            
            # Ensure target is within base directory
            if not str(target_path).startswith(str(base_path)):
                logger.warning(f"Path traversal attempt blocked: {output_path}")
                # Create safe path within base directory
                safe_filename = self._sanitize_filename(os.path.basename(output_path))
                return base_path / safe_filename
            
            return target_path
            
        except Exception as e:
            logger.error(f"Path validation error: {e}")
            # Fallback to safe path
            safe_filename = self._sanitize_filename(f"file_{secrets.token_hex(4)}")
            return Path(base_dir) / safe_filename
    
    def download_attachment(self, attachment_id, output_path):
        """Unified file download method with security hardening"""
        try:
            # Validate attachment ID
            if not isinstance(attachment_id, int) or attachment_id <= 0:
                logger.error(f"Invalid attachment ID: {attachment_id}")
                return False
            
            attachment_records = self.attachments.search_records([('id', '=', attachment_id)])
            
            if not attachment_records:
                logger.warning(f"File with ID {attachment_id} not found")
                if self.verbose:
                    print(f"❌ File with ID {attachment_id} not found")
                return False
            
            attachment = attachment_records[0]
            file_name = getattr(attachment, 'name', f'file_{attachment_id}')
            
            # Sanitize filename
            safe_filename = self._sanitize_filename(file_name)
            
            if not hasattr(attachment, 'datas'):
                logger.warning(f"No data field available for file {safe_filename}")
                if self.verbose:
                    print(f"❌ No data field available for file {safe_filename}")
                return False
            
            # Get file data
            file_data_b64 = attachment.datas
            if hasattr(file_data_b64, '__call__'):
                file_data_b64 = file_data_b64()
            
            if not file_data_b64:
                logger.warning(f"No data available for file {safe_filename}")
                if self.verbose:
                    print(f"❌ No data available for file {safe_filename}")
                return False
            
            try:
                file_data = base64.b64decode(file_data_b64)
            except Exception as e:
                logger.error(f"Failed to decode file data: {e}")
                return False
            
            # Validate file size (max 100MB)
            max_size = 100 * 1024 * 1024  # 100MB
            if len(file_data) > max_size:
                logger.error(f"File too large: {len(file_data)} bytes (max: {max_size})")
                if self.verbose:
                    print(f"❌ File too large: {self.format_file_size(len(file_data))} (max: {self.format_file_size(max_size)})")
                return False
            
            # Validate and secure output path
            if output_path.endswith('/') or os.path.isdir(output_path):
                output_path = os.path.join(output_path, safe_filename)
            elif not os.path.basename(output_path):
                output_path = os.path.join(output_path, safe_filename)
            
            secure_path = self._validate_download_path(output_path)
            
            # Create directory securely
            try:
                secure_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            except Exception as e:
                logger.error(f"Failed to create directory: {e}")
                return False
            
            # Write file securely
            try:
                with open(secure_path, 'wb') as f:
                    f.write(file_data)
                
                # Set secure file permissions
                secure_path.chmod(0o644)
                
            except Exception as e:
                logger.error(f"Failed to write file: {e}")
                return False
            
            if self.verbose:
                print(f"✅ Downloaded: {safe_filename}")
                print(f"   To: {secure_path}")
                print(f"   Size: {len(file_data)} bytes")
            
            logger.info(f"File downloaded successfully: {safe_filename}")
            return True
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            if self.verbose:
                print(f"❌ Download failed: {str(e)[:100]}...")  # Limit error message length
            return False

    def html_to_markdown(self, html_content):
        """
        Convert HTML content to readable markdown-like text
        
        Args:
            html_content: HTML string to convert
            
        Returns:
            Cleaned markdown-like text
        """
        if not html_content:
            return ""
        
        try:
            # First try to convert any markdown content back to HTML for consistency
            import markdown2
            # But since we're getting HTML from Odoo, we'll just strip tags
            # and keep the existing logic for now
            pass
        except ImportError:
            if self.verbose:
                print("Warning: markdown2 not available")
        
        # Unescape HTML entities first
        text = html.unescape(html_content)
        
        # Convert common HTML tags to markdown equivalents
        conversions = [
            # Headers
            (r'<h1[^>]*>(.*?)</h1>', r'# \1'),
            (r'<h2[^>]*>(.*?)</h2>', r'## \1'),
            (r'<h3[^>]*>(.*?)</h3>', r'### \1'),
            (r'<h4[^>]*>(.*?)</h4>', r'#### \1'),
            (r'<h5[^>]*>(.*?)</h5>', r'##### \1'),
            (r'<h6[^>]*>(.*?)</h6>', r'###### \1'),
            
            # Text formatting
            (r'<strong[^>]*>(.*?)</strong>', r'**\1**'),
            (r'<b[^>]*>(.*?)</b>', r'**\1**'),
            (r'<em[^>]*>(.*?)</em>', r'*\1*'),
            (r'<i[^>]*>(.*?)</i>', r'*\1*'),
            (r'<u[^>]*>(.*?)</u>', r'_\1_'),
            (r'<code[^>]*>(.*?)</code>', r'`\1`'),
            
            # Links
            (r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)'),
            
            # Lists
            (r'<ul[^>]*>', r''),
            (r'</ul>', r''),
            (r'<ol[^>]*>', r''),
            (r'</ol>', r''),
            (r'<li[^>]*>(.*?)</li>', r'- \1'),
            
            # Paragraphs and breaks
            (r'<p[^>]*>', r''),
            (r'</p>', r'\n'),
            (r'<br[^>]*/?>', r'\n'),
            (r'<div[^>]*>', r''),
            (r'</div>', r'\n'),
            
            # Blockquotes
            (r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1'),
            
            # Remove remaining HTML tags
            (r'<[^>]+>', r''),
            
            # Clean up whitespace
            (r'\n\s*\n\s*\n', r'\n\n'),  # Multiple newlines to double
            (r'^\s+', r''),  # Leading whitespace
            (r'\s+$', r''),  # Trailing whitespace
        ]
        
        # Apply conversions
        for pattern, replacement in conversions:
            text = re.sub(pattern, replacement, text, flags=re.DOTALL | re.IGNORECASE)
        
        # Final cleanup
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 consecutive newlines
        text = text.strip()
        
        return text

    def markdown_to_html(self, markdown_content):
        """
        Convert markdown content to HTML using markdown2 library
        
        Args:
            markdown_content: Markdown string to convert
            
        Returns:
            HTML string
        """
        if not markdown_content:
            return ""
        
        try:
            import markdown2
            return markdown2.markdown(markdown_content)
        except ImportError:
            if self.verbose:
                print("Warning: markdown2 not available, returning content as-is")
            return markdown_content
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to convert markdown with markdown2: {e}")
            return markdown_content

    def _get_user_name(self, user_id):
        """Get user name with a small in-memory TTL cache to reduce RPC calls"""
        if not user_id:
            return 'Unassigned'

        # Check cache
        try:
            entry = self._user_name_cache.get(user_id)
            now = time.time()
            if entry:
                ts, name = entry
                if now - ts <= self._user_name_ttl:
                    return name
                else:
                    # Expired; remove to allow refresh
                    self._user_name_cache.pop(user_id, None)
        except Exception:
            # If cache fails for any reason, fall back to direct fetch
            pass
        
        # Fetch from server on miss
        try:
            user_records = self.client['res.users'].search_records([('id', '=', user_id)])
            if user_records:
                name = user_records[0].name
                # Store in cache
                try:
                    self._user_name_cache[user_id] = (time.time(), name)
                except Exception:
                    pass
                return name
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not get user {user_id}: {e}")
        
        return f'User {user_id} (not found)'

    def create_terminal_link(self, url, text):
        """
        Create a clickable terminal hyperlink using ANSI escape sequences
        
        Args:
            url: The URL to link to
            text: The display text
            
        Returns:
            Formatted string with terminal hyperlink
        """
        # ANSI escape sequence for hyperlinks: \033]8;;URL\033\\TEXT\033]8;;\033\\
        # Use \x1b instead of \033 for better compatibility
        return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"

    def get_project_url(self, project_id):
        """Get the URL for a project"""
        return f"{self.base_url}/web#id={project_id}&model=project.project&view_type=form"

    def get_task_url(self, task_id):
        """Get the URL for a task"""
        return f"{self.base_url}/web#id={task_id}&model=project.task&view_type=form"

    def get_message_url(self, message_id):
        """Get the URL for a message"""
        return f"{self.base_url}/mail/message/{message_id}"

    def get_file_url(self, file_id):
        """Get the URL for a file/attachment"""
        return f"{self.base_url}/web/content/{file_id}"

    def format_file_size(self, size_bytes):
        """Format file size in human readable format"""
        if not size_bytes:
            return "0 B"

        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"


