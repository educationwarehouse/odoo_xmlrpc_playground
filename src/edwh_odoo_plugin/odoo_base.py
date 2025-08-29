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
from dotenv import load_dotenv
from openerp_proxy import Client
from openerp_proxy.ext.all import *
import warnings

# Suppress the pkg_resources deprecation warning from odoo_rpc_client globally
warnings.filterwarnings("ignore", 
                      message="pkg_resources is deprecated as an API.*",
                      category=UserWarning)


class OdooBase:
    """
    Base class for Odoo connections and common functionality
    
    Provides:
    - Connection management
    - Configuration loading
    - Model shortcuts
    - URL generation
    - File size formatting
    """

    def __init__(self, verbose=False):
        """Initialize with .env configuration"""
        from pathlib import Path
        
        self.verbose = verbose

        # Only use config directory location
        config_dotenv = Path.home() / ".config/edwh/edwh_odoo_plugin.env"
        
        if config_dotenv.exists():
            load_dotenv(config_dotenv)
            if self.verbose:
                print(f"📁 Loading configuration from: {config_dotenv.absolute()}")
        else:
            print(f"❌ No configuration file found!")
            print(f"   Expected location: {config_dotenv.absolute()}")
            print(f"")
            print(f"   Please run: edwh odoo.setup")
            raise FileNotFoundError("No configuration file found. Run 'edwh odoo.setup' to create one.")

        self.host = os.getenv('ODOO_HOST')
        self.database = os.getenv('ODOO_DATABASE')
        self.user = os.getenv('ODOO_USER')
        self.password = os.getenv('ODOO_PASSWORD')
        self.port = int(os.getenv('ODOO_PORT', '443'))
        self.protocol = os.getenv('ODOO_PROTOCOL', 'xml-rpcs')

        if not all([self.host, self.database, self.user, self.password]):
            missing_vars = []
            if not self.host: missing_vars.append('ODOO_HOST')
            if not self.database: missing_vars.append('ODOO_DATABASE')
            if not self.user: missing_vars.append('ODOO_USER')
            if not self.password: missing_vars.append('ODOO_PASSWORD')
            
            print(f"❌ Configuration incomplete!")
            print(f"   Missing required variables: {', '.join(missing_vars)}")
            print(f"   Configuration file: {config_dotenv.absolute()}")
            print(f"")
            print(f"   Please run: edwh odoo.setup")
            raise ValueError(f"Missing required configuration variables: {', '.join(missing_vars)}. Run 'edwh odoo.setup' to configure.")

        # Build base URL for links
        self.base_url = f"https://{self.host}"

        self._connect()

    def _connect(self):
        """Connect to Odoo"""
        try:
            if self.verbose:
                print(f"🔌 Connecting to Odoo...")
                print(f"   Host: {self.host}")
                print(f"   Database: {self.database}")
                print(f"   User: {self.user}")

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

            # Model shortcuts
            self.projects = self.client['project.project']
            self.tasks = self.client['project.task']
            self.attachments = self.client['ir.attachment']
            self.messages = self.client['mail.message']

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            raise

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


