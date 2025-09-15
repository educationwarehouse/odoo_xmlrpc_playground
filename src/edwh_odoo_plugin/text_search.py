#!/usr/bin/env python3
"""
Odoo Project Text Search - Full Text Search Module
==================================================

Advanced text search functionality for Odoo projects and tasks.
Searches through:
- Project names and descriptions
- Task names and descriptions  
- Project and task log messages (mail.message)
- With time-based filtering to avoid server overload

Usage:
    python text_search.py "search term" --since "1 week"
    python text_search.py "bug fix" --since "2 days" --type tasks
    python text_search.py "client meeting" --since "1 month" --include-logs

Author: Based on search.py
Date: August 2025
"""

import os
import argparse
from datetime import datetime, timedelta
import re
import csv
import html
import base64
import textwrap
import logging
from .odoo_base import OdooBase

# Configure secure logging
logger = logging.getLogger(__name__)


class OdooTextSearch(OdooBase):
    """
    Advanced text search for Odoo projects and tasks
    
    Features:
    - Search in project/task names and descriptions
    - Search in log messages (mail.message)
    - Time-based filtering with human-readable dates
    - Efficient querying to avoid server overload
    """

    def __init__(self, verbose=False):
        """Initialize with .env configuration"""
        super().__init__(verbose=verbose)
        
        # Add attachments model for file search
        self.attachments = self.client['ir.attachment']
        
        # Aggressive caching system
        self.user_cache = {}
        self.project_cache = {}  # Cache full project records
        self.message_cache = {}  # Cache message records (messages don't change)
        self.project_task_map = {}  # Map project_id -> [task_ids]
        self.task_project_map = {}  # Map task_id -> project_id
        self.attachment_cache = {}  # Cache attachment metadata
        
        # Cache initialization flags
        self._user_cache_built = False
        self._project_cache_built = False
        self._message_cache_built = False
        
        # Security limits
        self.max_search_length = 1000
        self.max_results_per_query = 10000

    def _sanitize_search_term(self, search_term):
        """Sanitize search term to prevent injection attacks"""
        if not search_term:
            return ""
        
        # Convert to string and limit length
        search_term = str(search_term)[:self.max_search_length]
        
        # Remove potentially dangerous characters for SQL injection
        # Keep alphanumeric, spaces, and common punctuation
        sanitized = re.sub(r'[^\w\s\-.,!?@#$%^&*()+=\[\]{}|;:\'\"<>/\\`~]', '', search_term)
        
        # Remove SQL injection patterns
        sql_patterns = [
            r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|SCRIPT)\b)',
            r'(--|/\*|\*/)',
            r'(\bOR\b.*\b=\b)',
            r'(\bAND\b.*\b=\b)',
            r'(\'.*\')',
            r'(;.*)',
        ]
        
        for pattern in sql_patterns:
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
        
        # Trim whitespace
        sanitized = sanitized.strip()
        
        if len(sanitized) != len(search_term):
            logger.warning("Search term was sanitized for security")
        
        return sanitized
    
    def _parse_time_reference(self, time_ref):
        """
        Parse human-readable time references in English and Dutch with input validation
        """
        if not time_ref:
            return None

        # Sanitize input
        time_ref = str(time_ref).lower().strip()[:50]  # Limit length
        
        # Only allow safe characters
        if not re.match(r'^[a-z0-9\s]+$', time_ref):
            logger.warning(f"Invalid characters in time reference: {time_ref}")
            return None
        
        # Pattern: number + unit (English and Dutch)
        pattern = r'^(\d{1,3})\s*(day|days|dag|dagen|week|weeks|weken|month|months|maand|maanden|year|years|jaar|jaren)$'
        match = re.match(pattern, time_ref)
        
        if not match:
            logger.warning(f"Invalid time reference format: {time_ref}")
            return None
        
        number = int(match.group(1))
        unit = match.group(2)
        
        # Validate reasonable limits
        if number > 999:
            logger.warning(f"Time reference number too large: {number}")
            return None
        
        now = datetime.now()
        
        # English and Dutch day units
        if unit in ['day', 'days', 'dag', 'dagen']:
            if number > 365:  # Max 1 year in days
                number = 365
            return now - timedelta(days=number)
        # English and Dutch week units
        elif unit in ['week', 'weeks', 'weken']:
            if number > 52:  # Max 1 year in weeks
                number = 52
            return now - timedelta(weeks=number)
        # English and Dutch month units
        elif unit in ['month', 'months', 'maand', 'maanden']:
            if number > 12:  # Max 1 year in months
                number = 12
            return now - timedelta(days=number * 30)  # Approximate
        # English and Dutch year units
        elif unit in ['year', 'years', 'jaar', 'jaren']:
            if number > 10:  # Max 10 years
                number = 10
            return now - timedelta(days=number * 365)  # Approximate
        
        return None

    def search_projects(self, search_term, since=None, include_descriptions=True, limit=None):
        """
        Search in project names and descriptions using safe database queries
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            include_descriptions: Whether to search in descriptions
            limit: Maximum number of results to return
        """
        # Sanitize search term
        sanitized_term = self._sanitize_search_term(search_term)
        if not sanitized_term:
            logger.warning("Empty search term after sanitization")
            return []
        
        # Apply security limits
        if limit is None or limit > self.max_results_per_query:
            limit = self.max_results_per_query
        
        if self.verbose:
            print(f"🔍 Searching projects for: '{sanitized_term[:50]}...'")
        else:
            print(f"🔍 Searching projects...", end="", flush=True)
        
        try:
            # Build simple, safe domain
            domain = []
            
            # Text search - use simple structure
            if include_descriptions:
                domain = ['|', ('name', 'ilike', sanitized_term), ('description', 'ilike', sanitized_term)]
            else:
                domain = [('name', 'ilike', sanitized_term)]
            
            # Add time filter if specified
            if since:
                date_condition = ('write_date', '>=', since.strftime('%Y-%m-%d %H:%M:%S'))
                if domain:
                    domain = ['&'] + domain + [date_condition]
                else:
                    domain = [date_condition]
            
            if self.verbose:
                print(f"🔧 Project domain: {domain}")
            
            # Search with safe parameters
            search_kwargs = {
                'limit': min(limit, 1000),  # Hard limit to prevent server overload
                'order': 'write_date desc'
            }
            
            projects = self.projects.search_records(domain, **search_kwargs)
            
            if self.verbose:
                print(f"📂 Found {len(projects)} matching projects")
            else:
                print(f" {len(projects)} found", flush=True)
            
            # Process projects with safe field access
            enriched_projects = []
            for project in projects:
                try:
                    # Safe field access with fallbacks
                    project_data = {
                        'id': project.id,
                        'name': getattr(project, 'name', f'Project {project.id}'),
                        'description': '',
                        'partner_id': None,
                        'partner_name': 'No client',
                        'user_id': None,
                        'user_name': 'Unassigned',
                        'create_date': '',
                        'write_date': '',
                        'stage_id': None
                    }
                    
                    # Safe description access
                    try:
                        raw_description = getattr(project, 'description', '') or ''
                        project_data['description'] = self.html_to_markdown(raw_description) if raw_description else ''
                    except Exception:
                        project_data['description'] = ''
                    
                    # Safe partner access
                    try:
                        if hasattr(project, 'partner_id') and project.partner_id:
                            project_data['partner_id'] = project.partner_id.id if hasattr(project.partner_id, 'id') else None
                            project_data['partner_name'] = project.partner_id.name if hasattr(project.partner_id, 'name') else 'No client'
                    except Exception:
                        pass
                    
                    # Safe user access
                    try:
                        if hasattr(project, 'user_id') and project.user_id:
                            project_data['user_id'] = project.user_id.id if hasattr(project.user_id, 'id') else None
                            project_data['user_name'] = project.user_id.name if hasattr(project.user_id, 'name') else 'Unassigned'
                    except Exception:
                        pass
                    
                    # Safe date access
                    try:
                        project_data['create_date'] = str(project.create_date) if hasattr(project, 'create_date') and project.create_date else ''
                        project_data['write_date'] = str(project.write_date) if hasattr(project, 'write_date') and project.write_date else ''
                    except Exception:
                        pass
                    
                    # Safe stage access
                    try:
                        project_data['stage_id'] = getattr(project, 'stage_id', None)
                    except Exception:
                        pass
                    
                    # Cache this project for future lookups
                    self.project_cache[project.id] = project_data
                    
                    # Create enriched result
                    enriched_project = {
                        'id': project_data['id'],
                        'name': project_data['name'],
                        'description': project_data['description'],
                        'partner': project_data['partner_name'],
                        'stage': project_data['stage_id'],
                        'user': project_data['user_name'],
                        'create_date': project_data['create_date'],
                        'write_date': project_data['write_date'],
                        'type': 'project',
                        'search_term': search_term,
                        'match_in_name': search_term.lower() in project_data['name'].lower(),
                        'match_in_description': search_term.lower() in project_data['description'].lower()
                    }
                    enriched_projects.append(enriched_project)
                    
                except Exception as project_error:
                    if self.verbose:
                        print(f"⚠️ Error processing project {getattr(project, 'id', 'unknown')}: {project_error}")
                    continue
            
            return enriched_projects
            
        except Exception as e:
            from .odoo_base import ErrorHandler
            return ErrorHandler.handle_search_error("project search", e, self.verbose)

    def search_tasks(self, search_term, since=None, include_descriptions=True, project_ids=None, limit=None):
        """
        Search in task names and descriptions using direct database queries
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            include_descriptions: Whether to search in descriptions
            project_ids: Limit to specific projects
            limit: Maximum number of results to return
        """
        if self.verbose:
            print(f"🔍 Searching tasks for: '{search_term}'")
        else:
            print(f"🔍 Searching tasks...", end="", flush=True)
        
        try:
            # Build domain using DomainBuilder
            from .odoo_base import DomainBuilder
            
            domain_parts = []
            
            # Time filter
            if since:
                domain_parts.append(DomainBuilder.date_filter_domain(since))
            
            # Project filter
            if project_ids:
                domain_parts.append([('project_id', 'in', project_ids)])
            
            # Text search
            text_fields = ['name', 'description'] if include_descriptions else ['name']
            text_domain = DomainBuilder.text_search_domain(search_term, text_fields, include_descriptions)
            
            # Combine all domains
            final_domain = text_domain
            for domain_part in domain_parts:
                if domain_part:
                    final_domain = DomainBuilder.combine_with_and(final_domain, *domain_part)
            
            if self.verbose:
                print(f"🔧 Task domain: {final_domain}")
            
            # Apply limit at database level
            search_kwargs = {}
            if limit:
                search_kwargs['limit'] = limit
                search_kwargs['order'] = 'write_date desc'
            
            tasks = self.tasks.search_records(final_domain, **search_kwargs)
            
            if self.verbose:
                print(f"📋 Found {len(tasks)} matching tasks")
            else:
                print(f" {len(tasks)} found", flush=True)
            
            # Use unified task enrichment
            enriched_tasks = []
            for task in tasks:
                enriched_task = self.enrich_task_data(task, search_term)
                
                # Build project-task mapping (but don't cache task data since it changes frequently)
                if enriched_task['project_id']:
                    if enriched_task['project_id'] not in self.project_task_map:
                        self.project_task_map[enriched_task['project_id']] = []
                    if task.id not in self.project_task_map[enriched_task['project_id']]:
                        self.project_task_map[enriched_task['project_id']].append(task.id)
                    self.task_project_map[task.id] = enriched_task['project_id']
                
                enriched_tasks.append(enriched_task)
            
            return enriched_tasks
            
        except Exception as e:
            from .odoo_base import ErrorHandler
            return ErrorHandler.handle_search_error("task search", e, self.verbose)

    def search_messages(self, search_term, since=None, model_type='both', limit=None):
        """
        Search in mail messages (logs) for projects and tasks using cached data
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            model_type: 'projects', 'tasks', or 'both'
            limit: Maximum number of results to return
        """
        if self.verbose:
            print(f"🔍 Searching messages for: '{search_term}'")
        else:
            print(f"🔍 Searching messages...", end="", flush=True)
        
        try:
            # Ensure message cache is initialized
            if not self._message_cache_built:
                self._build_message_cache()
            
            # Build domain for message search
            domain = []
            
            # Time filter
            if since:
                domain.append(('date', '>=', since.strftime('%Y-%m-%d %H:%M:%S')))
            
            # Model filter
            model_conditions = []
            if model_type in ['projects', 'both']:
                model_conditions.append(('model', '=', 'project.project'))
            if model_type in ['tasks', 'both']:
                model_conditions.append(('model', '=', 'project.task'))
            
            if len(model_conditions) == 2:
                model_domain = ['|'] + model_conditions
            else:
                model_domain = model_conditions
            
            # Text search in message body
            text_domain = [('body', 'ilike', search_term)]
            
            # Combine all domains
            if domain and model_domain:
                final_domain = ['&'] + domain + ['&'] + model_domain + text_domain
            elif domain:
                final_domain = ['&'] + domain + text_domain
            elif model_domain:
                final_domain = ['&'] + model_domain + text_domain
            else:
                final_domain = text_domain
            
            if self.verbose:
                print(f"🔧 Message domain: {final_domain}")
            
            # Apply limit at database level
            search_kwargs = {}
            if limit:
                search_kwargs['limit'] = limit
                search_kwargs['order'] = 'date desc'
            
            messages = self.messages.search_records(final_domain, **search_kwargs)
            
            if self.verbose:
                print(f"💬 Found {len(messages)} matching messages")
            else:
                print(f" {len(messages)} found", flush=True)
            
            # Cache found messages for future use
            matching_messages = []
            for message in messages:
                # Convert body to markdown
                raw_body = getattr(message, 'body', '') or ''
                markdown_body = self.html_to_markdown(raw_body) if raw_body else ''
                
                message_data = {
                    'id': message.id,
                    'subject': getattr(message, 'subject', '') or 'No subject',
                    'body': markdown_body,
                    'author': message.author_id.name if message.author_id else 'System',
                    'date': str(message.date) if message.date else '',
                    'model': message.model,
                    'res_id': message.res_id
                }
                # Cache this message for future searches
                self.message_cache[message.id] = message_data
                matching_messages.append(message_data)
            
            # Enrich messages with related record info
            enriched_messages = []
            
            # Collect all unique task IDs that we need to look up
            task_ids_needed = set()
            for message_data in matching_messages:
                if message_data['model'] == 'project.task' and message_data['res_id']:
                    task_ids_needed.add(message_data['res_id'])
            
            # Batch lookup all needed tasks at once
            task_name_cache = {}
            if task_ids_needed:
                try:
                    task_records = self.tasks.search_records([('id', 'in', list(task_ids_needed))])
                    for task in task_records:
                        task_name_cache[task.id] = task.name
                except Exception as e:
                    if self.verbose:
                        print(f"⚠️ Could not batch lookup tasks: {e}")
            
            for message_data in matching_messages:
                # Get related record info with caching
                related_name = "Unknown"
                related_type = message_data['model']
                
                if message_data['model'] == 'project.project' and message_data['res_id']:
                    project_data = self._get_cached_project(message_data['res_id'])
                    if project_data:
                        related_name = project_data['name']
                    else:
                        related_name = f"Project {message_data['res_id']}"
                        
                elif message_data['model'] == 'project.task' and message_data['res_id']:
                    # Use batch-loaded task names
                    if message_data['res_id'] in task_name_cache:
                        related_name = task_name_cache[message_data['res_id']]
                    else:
                        related_name = f"Task {message_data['res_id']}"
                
                enriched_message = {
                    'id': message_data['id'],
                    'subject': message_data['subject'],
                    'body': message_data['body'],
                    'author': message_data['author'],
                    'date': message_data['date'],
                    'model': message_data['model'],
                    'res_id': message_data['res_id'],
                    'related_name': related_name,
                    'related_type': related_type,
                    'type': 'message',
                    'search_term': search_term
                }
                enriched_messages.append(enriched_message)
            
            return enriched_messages
            
        except Exception as e:
            print(f"❌ Error searching messages: {e}")
            return []

    def search_files(self, search_term, since=None, file_types=None, model_type='both', limit=None):
        """
        Search in file names and metadata for all attachments with optimized queries
        
        Args:
            search_term: Text to search for in filenames
            since: Datetime to limit search from
            file_types: List of file extensions to filter by (e.g., ['pdf', 'docx'])
            model_type: 'projects', 'tasks', 'both', or 'all' (all includes any model)
            limit: Maximum number of results to return
        """
        if self.verbose:
            print(f"🔍 Searching files for: '{search_term}'")
        else:
            print(f"🔍 Searching files...", end="", flush=True)
        
        try:
            # Build domain for file search
            domain = []
            
            # Time filter
            if since:
                domain.append(('create_date', '>=', since.strftime('%Y-%m-%d %H:%M:%S')))
            
            # Model filter - get IDs from database for efficiency
            if model_type != 'all':
                # Get all project and task IDs directly from database
                all_projects = self.projects.search_records([])
                all_tasks = self.tasks.search_records([])
                
                project_ids = [p.id for p in all_projects]
                task_ids = [t.id for t in all_tasks]
                
                model_conditions = []
                if model_type in ['projects', 'both'] and project_ids:
                    model_conditions.append(['&', ('res_model', '=', 'project.project'), ('res_id', 'in', project_ids)])
                if model_type in ['tasks', 'both'] and task_ids:
                    model_conditions.append(['&', ('res_model', '=', 'project.task'), ('res_id', 'in', task_ids)])
                
                if len(model_conditions) == 2:
                    model_domain = ['|'] + model_conditions[0] + model_conditions[1]
                elif len(model_conditions) == 1:
                    model_domain = model_conditions[0]
                else:
                    model_domain = []
            else:
                # Search all attachments regardless of model
                model_domain = []
            
            # Text search in filename
            text_domain = [('name', 'ilike', search_term)]
            
            # File type filter
            if file_types:
                type_conditions = []
                for file_type in file_types:
                    # Handle both with and without dot
                    ext = file_type.lower().lstrip('.')
                    type_conditions.append(('name', 'ilike', f'.{ext}'))
                
                if len(type_conditions) > 1:
                    type_domain = ['|'] * (len(type_conditions) - 1) + type_conditions
                else:
                    type_domain = type_conditions
            else:
                type_domain = []
            
            # Combine all domains
            final_domain = []
            if domain:
                final_domain.extend(domain)
            if model_domain:
                if final_domain:
                    final_domain = ['&'] + final_domain + model_domain
                else:
                    final_domain = model_domain
            if text_domain:
                if final_domain:
                    final_domain = ['&'] + final_domain + text_domain
                else:
                    final_domain = text_domain
            if type_domain:
                if final_domain:
                    final_domain = ['&'] + final_domain + type_domain
                else:
                    final_domain = type_domain
            
            if self.verbose:
                print(f"🔧 File domain: {final_domain}")
            
            # Apply limit at database level
            search_kwargs = {}
            if limit:
                search_kwargs['limit'] = limit
                search_kwargs['order'] = 'create_date desc'
            
            # Fetch files
            files = self.attachments.search_records(final_domain, **search_kwargs)
            
            if self.verbose:
                print(f"📁 Found {len(files)} matching files")
            else:
                print(f" {len(files)} found", flush=True)
            
            return self._enrich_files_optimized(files, search_term)
            
        except Exception as e:
            print(f"❌ Error searching files: {e}")
            return []

    def _build_user_cache(self):
        """Build a cache of all users for efficient lookup"""
        if self._user_cache_built:
            return
            
        if self.verbose:
            print("👥 Building user cache...")
        
        try:
            # Get all users
            users = self.client['res.users'].search_records([])
            self.user_cache = {user.id: user.name for user in users}
            self._user_cache_built = True
            
            if self.verbose:
                print(f"👥 Cached {len(self.user_cache)} users")
                
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not build user cache: {e}")
            self.user_cache = {}

    def _build_project_cache(self):
        """Build a cache of all projects for efficient lookup"""
        if self._project_cache_built:
            return
            
        if self.verbose:
            print("📂 Building project cache...")
        
        try:
            # Get all projects with limited fields for efficiency
            projects = self.projects.search_records([])
            
            for project in projects:
                project_data = {
                    'id': project.id,
                    'name': project.name,
                    'description': getattr(project, 'description', '') or '',
                    'partner_id': project.partner_id.id if project.partner_id else None,
                    'partner_name': project.partner_id.name if project.partner_id else 'No client',
                    'user_id': project.user_id.id if project.user_id else None,
                    'user_name': project.user_id.name if project.user_id else 'Unassigned',
                    'create_date': str(project.create_date) if project.create_date else '',
                    'write_date': str(project.write_date) if project.write_date else '',
                    'stage_id': getattr(project, 'stage_id', None)
                }
                self.project_cache[project.id] = project_data
            
            self._project_cache_built = True
            
            if self.verbose:
                print(f"📂 Cached {len(self.project_cache)} projects")
                
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not build project cache: {e}")
            self.project_cache = {}

    def _build_message_cache(self):
        """Initialize empty message cache - messages will be cached on-demand during searches"""
        if self._message_cache_built:
            return
            
        if self.verbose:
            print("💬 Initializing message cache (on-demand)...")
        
        # Initialize empty cache - messages will be added as they're found during searches
        self.message_cache = {}
        self._message_cache_built = True
        
        if self.verbose:
            print(f"💬 Message cache initialized (will populate during searches)")
    
    
    def _get_cached_project(self, project_id):
        """Get project from cache, with fallback to direct lookup"""
        if not self._project_cache_built:
            self._build_project_cache()
        
        if project_id in self.project_cache:
            return self.project_cache[project_id]
        
        # Fallback: direct lookup and cache
        try:
            project_records = self.projects.search_records([('id', '=', project_id)])
            if project_records:
                project = project_records[0]
                project_data = {
                    'id': project.id,
                    'name': project.name,
                    'description': getattr(project, 'description', '') or '',
                    'partner_id': project.partner_id.id if project.partner_id else None,
                    'partner_name': project.partner_id.name if project.partner_id else 'No client',
                    'user_id': project.user_id.id if project.user_id else None,
                    'user_name': project.user_id.name if project.user_id else 'Unassigned',
                    'create_date': str(project.create_date) if project.create_date else '',
                    'write_date': str(project.write_date) if project.write_date else '',
                    'stage_id': getattr(project, 'stage_id', None)
                }
                self.project_cache[project_id] = project_data
                return project_data
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not fetch project {project_id}: {e}")
        
        return None
    
    def _get_cached_message(self, message_id):
        """Get message from cache, with fallback to direct lookup"""
        if not self._message_cache_built:
            self._build_message_cache()
        
        if message_id in self.message_cache:
            return self.message_cache[message_id]
        
        # Fallback: direct lookup and cache
        try:
            message_records = self.messages.search_records([('id', '=', message_id)])
            if message_records:
                message = message_records[0]
                
                message_data = {
                    'id': message.id,
                    'subject': getattr(message, 'subject', '') or 'No subject',
                    'body': getattr(message, 'body', '') or '',
                    'author': message.author_id.name if message.author_id else 'System',
                    'date': str(message.date) if message.date else '',
                    'model': message.model,
                    'res_id': message.res_id
                }
                
                self.message_cache[message_id] = message_data
                return message_data
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not fetch message {message_id}: {e}")
        
        return None


    def _get_user_name(self, user_id):
        """Get user name from cache, with fallback"""
        if not user_id:
            return 'Unassigned'
        
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        
        # Fallback: try to get user directly
        try:
            user_records = self.client['res.users'].search_records([('id', '=', user_id)])
            if user_records:
                user_name = user_records[0].name
                # Cache for future use
                self.user_cache[user_id] = user_name
                return user_name
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Could not get user {user_id}: {e}")
        
        return f'User {user_id} (not found)'

    def full_text_search(self, search_term, since=None, search_type='all', include_descriptions=True, include_logs=True, include_files=True, file_types=None, limit=None):
        """
        Comprehensive text search across projects, tasks, logs, and files
        
        Args:
            search_term: Text to search for
            since: Time reference string (e.g., "1 week", "3 days")
            search_type: 'all', 'projects', 'tasks', 'logs', 'files'
            include_descriptions: Search in descriptions
            include_logs: Search in log messages (default: True)
            include_files: Search in file names and metadata (default: True)
            file_types: List of file extensions to filter by
            limit: Maximum number of results per category
        """
        # Validate search type
        valid_types = ['all', 'projects', 'tasks', 'logs', 'files']
        if search_type not in valid_types:
            raise ValueError(f"Invalid search type '{search_type}'. Valid types are: {', '.join(valid_types)}")
        
        if self.verbose:
            print(f"\n🚀 FULL TEXT SEARCH")
            print(f"=" * 60)
            print(f"🔍 Search term: '{search_term}'")
            
            # Parse time reference
            since_date = None
            if since:
                since_date = self._parse_time_reference(since)
                print(f"📅 Since: {since} ({since_date.strftime('%Y-%m-%d %H:%M:%S') if since_date else 'Invalid'})")
            
            print(f"🎯 Type: {search_type}")
            print(f"📝 Include descriptions: {include_descriptions}")
            print(f"💬 Include logs: {include_logs}")
            print(f"📁 Include files: {include_files}")
            if file_types:
                print(f"📄 File types: {', '.join(file_types)}")
            if limit:
                print(f"🔢 Limit per category: {limit}")
            print()
        else:
            # Parse time reference
            since_date = None
            if since:
                since_date = self._parse_time_reference(since)
        
        # Build user cache upfront and initialize message cache (messages cached on-demand)
        self._build_user_cache()
        self._build_message_cache()
        # Projects will be cached on-demand, tasks are not cached (they change frequently)
        
        results = {
            'projects': [],
            'tasks': [],
            'messages': [],
            'files': []
        }
        
        try:
            # Search projects
            if search_type in ['all', 'projects']:
                results['projects'] = self.search_projects(search_term, since_date, include_descriptions, limit)
            
            if self.verbose:
                print()  # Add white line between searches
            
            # Search tasks
            if search_type in ['all', 'tasks']:
                results['tasks'] = self.search_tasks(search_term, since_date, include_descriptions, None, limit)
            
            # Search messages/logs
            if include_logs and search_type in ['all', 'logs']:
                model_type = 'both' if search_type == 'all' else search_type
                results['messages'] = self.search_messages(search_term, since_date, model_type, limit)
            
            # Search files
            if include_files or search_type == 'files':
                # Use 'all' for comprehensive file search when searching all or files specifically
                model_type = 'all' if search_type in ['all', 'files'] else search_type
                results['files'] = self.search_files(search_term, since_date, file_types, model_type, limit)
            
            return results
            
        except Exception as e:
            print(f"❌ Error in full text search: {e}")
            return results

    def _enrich_projects(self, projects, search_term):
        """Enrich project results with cached data - this method is now only used for message-related projects"""
        enriched = []
        
        for project in projects:
            try:
                # Get project data from cache if available
                project_data = self._get_cached_project(project.id)
                if project_data:
                    enriched_project = {
                        'id': project_data['id'],
                        'name': project_data['name'],
                        'description': project_data['description'],
                        'partner': project_data['partner_name'],
                        'stage': project_data['stage_id'],
                        'user': project_data['user_name'],
                        'create_date': project_data['create_date'],
                        'write_date': project_data['write_date'],
                        'type': 'project',
                        'search_term': search_term,
                        'match_in_name': search_term.lower() in project_data['name'].lower(),
                        'match_in_description': search_term.lower() in project_data['description'].lower()
                    }
                    enriched.append(enriched_project)
                else:
                    # Fallback to original method for uncached projects
                    enriched_project = {
                        'id': project.id,
                        'name': project.name,
                        'description': getattr(project, 'description', '') or '',
                        'partner': project.partner_id.name if project.partner_id else 'No client',
                        'stage': getattr(project, 'stage_id', None),
                        'user': project.user_id.name if project.user_id else 'Unassigned',
                        'create_date': str(project.create_date) if project.create_date else '',
                        'write_date': str(project.write_date) if project.write_date else '',
                        'type': 'project',
                        'search_term': search_term,
                        'match_in_name': search_term.lower() in project.name.lower(),
                        'match_in_description': search_term.lower() in (getattr(project, 'description', '') or '').lower()
                    }
                    enriched.append(enriched_project)
                
            except Exception as e:
                print(f"⚠️ Error enriching project {project.id}: {e}")
                continue
        
        return enriched

    def _enrich_files_optimized(self, files, search_term):
        """Enrich file results with cached data for optimal performance"""
        enriched = []
        
        for file in files:
            try:
                enriched_file = {
                    'id': file.id,
                    'name': file.name,
                    'mimetype': getattr(file, 'mimetype', '') or 'Unknown',
                    'file_size': getattr(file, 'file_size', 0) or 0,
                    'file_size_human': self.format_file_size(getattr(file, 'file_size', 0) or 0),
                    'create_date': str(file.create_date) if file.create_date else '',
                    'write_date': str(file.write_date) if file.write_date else '',
                    'public': getattr(file, 'public', False),
                    'res_model': file.res_model,
                    'res_id': file.res_id,
                    'type': 'file',
                    'search_term': search_term
                }
                
                # Add model-specific information using cached data
                if file.res_model == 'project.project':
                    project_data = self._get_cached_project(file.res_id)
                    if project_data:
                        enriched_file.update({
                            'related_type': 'Project',
                            'related_name': project_data['name'],
                            'related_id': project_data['id'],
                            'project_name': project_data['name'],
                            'project_id': project_data['id'],
                            'client': project_data['partner_name']
                        })
                    else:
                        enriched_file.update({
                            'related_type': 'Project',
                            'related_name': f'Project {file.res_id}',
                            'related_id': file.res_id,
                            'error': 'Project record not found'
                        })
                
                elif file.res_model == 'project.task':
                    # Don't use cached task data since tasks change frequently
                    try:
                        task_records = self.tasks.search_records([('id', '=', file.res_id)])
                        if task_records:
                            task = task_records[0]
                            
                            # Extract user ID safely
                            user_name = 'Unassigned'
                            if hasattr(task, 'user_ids') and task.user_ids:
                                try:
                                    if hasattr(task.user_ids, '__len__') and len(task.user_ids) > 0:
                                        first_user = task.user_ids[0]
                                        if hasattr(first_user, 'name'):
                                            user_name = first_user.name
                                except:
                                    pass
                            
                            enriched_file.update({
                                'related_type': 'Task',
                                'related_name': task.name,
                                'related_id': task.id,
                                'task_name': task.name,
                                'task_id': task.id,
                                'project_name': task.project_id.name if task.project_id else 'No project',
                                'project_id': task.project_id.id if task.project_id else None,
                                'assigned_user': user_name
                            })
                        else:
                            enriched_file.update({
                                'related_type': 'Task',
                                'related_name': f'Task {file.res_id}',
                                'related_id': file.res_id,
                                'error': 'Task record not found'
                            })
                    except Exception as e:
                        enriched_file.update({
                            'related_type': 'Task',
                            'related_name': f'Task {file.res_id}',
                            'related_id': file.res_id,
                            'error': f'Task lookup failed: {e}'
                        })
                
                else:
                    # Handle other models
                    enriched_file.update({
                        'related_type': file.res_model or 'Unknown',
                        'related_name': f'{file.res_model} {file.res_id}' if file.res_model and file.res_id else 'No relation',
                        'related_id': file.res_id,
                        'model_name': file.res_model or 'Unknown'
                    })
                
                enriched.append(enriched_file)
                
            except Exception as e:
                print(f"⚠️ Error enriching file {file.id}: {e}")
                continue
        
        return enriched

    def _enrich_files(self, files, search_term):
        """Enrich file results with additional info"""
        enriched = []
        
        for file in files:
            try:
                enriched_file = {
                    'id': file.id,
                    'name': file.name,
                    'mimetype': getattr(file, 'mimetype', '') or 'Unknown',
                    'file_size': getattr(file, 'file_size', 0) or 0,
                    'file_size_human': self.format_file_size(getattr(file, 'file_size', 0) or 0),
                    'create_date': str(file.create_date) if file.create_date else '',
                    'write_date': str(file.write_date) if file.write_date else '',
                    'public': getattr(file, 'public', False),
                    'res_model': file.res_model,
                    'res_id': file.res_id,
                    'type': 'file',
                    'search_term': search_term
                }
                
                # Add model-specific information
                if file.res_model == 'project.project':
                    try:
                        # First search for the project record to ensure we get a proper record
                        project_records = self.projects.search_records([('id', '=', file.res_id)])
                        if project_records:
                            project = project_records[0]
                            
                            # Safely get project attributes
                            project_name = getattr(project, 'name', f'Project {file.res_id}')
                            
                            # Handle client relationship safely
                            client_name = 'No client'
                            if hasattr(project, 'partner_id') and project.partner_id:
                                try:
                                    if hasattr(project.partner_id, 'name'):
                                        client_name = project.partner_id.name
                                    else:
                                        client_name = f'Client {project.partner_id}'
                                except:
                                    client_name = 'Client (unavailable)'
                            
                            enriched_file.update({
                                'related_type': 'Project',
                                'related_name': project_name,
                                'related_id': project.id,
                                'project_name': project_name,
                                'project_id': project.id,
                                'client': client_name
                            })
                        else:
                            enriched_file.update({
                                'related_type': 'Project',
                                'related_name': f'Project {file.res_id}',
                                'related_id': file.res_id,
                                'error': 'Project record not found'
                            })
                    except Exception as e:
                        enriched_file.update({
                            'related_type': 'Project',
                            'related_name': f'Project {file.res_id}',
                            'related_id': file.res_id,
                            'error': f'Project info not available: {e}'
                        })
                
                elif file.res_model == 'project.task':
                    try:
                        # First search for the task record to ensure we get a proper record
                        task_records = self.tasks.search_records([('id', '=', file.res_id)])
                        if task_records:
                            task = task_records[0]
                            
                            # Safely get task attributes
                            task_name = getattr(task, 'name', f'Task {file.res_id}')
                            
                            # Handle project relationship safely
                            project_name = 'No project'
                            project_id = None
                            if hasattr(task, 'project_id') and task.project_id:
                                try:
                                    if hasattr(task.project_id, 'name'):
                                        project_name = task.project_id.name
                                        project_id = task.project_id.id
                                    else:
                                        # project_id might be just an ID
                                        project_id = task.project_id
                                        project_name = f'Project {project_id}'
                                except:
                                    project_name = 'Project (unavailable)'
                            
                            # Use shared user extraction method
                            user_id, assigned_user = self.extract_user_from_task(task)
                            
                            enriched_file.update({
                                'related_type': 'Task',
                                'related_name': task_name,
                                'related_id': task.id,
                                'task_name': task_name,
                                'task_id': task.id,
                                'project_name': project_name,
                                'project_id': project_id,
                                'assigned_user': assigned_user
                            })
                        else:
                            enriched_file.update({
                                'related_type': 'Task',
                                'related_name': f'Task {file.res_id}',
                                'related_id': file.res_id,
                                'error': 'Task record not found'
                            })
                    except Exception as e:
                        enriched_file.update({
                            'related_type': 'Task',
                            'related_name': f'Task {file.res_id}',
                            'related_id': file.res_id,
                            'error': f'Task info not available: {e}'
                        })
                
                else:
                    # Handle other models (mail.message, res.partner, etc.)
                    enriched_file.update({
                        'related_type': file.res_model or 'Unknown',
                        'related_name': f'{file.res_model} {file.res_id}' if file.res_model and file.res_id else 'No relation',
                        'related_id': file.res_id,
                        'model_name': file.res_model or 'Unknown'
                    })
                
                enriched.append(enriched_file)
                
            except Exception as e:
                print(f"⚠️ Error enriching file {file.id}: {e}")
                continue
        
        return enriched

    def _enrich_tasks(self, tasks, search_term):
        """Enrich task results with cached data - this method is now only used for message-related tasks"""
        enriched = []
        
        for task in tasks:
            try:
                # Use unified task enrichment method
                enriched_task = self.enrich_task_data(task, search_term)
                enriched.append(enriched_task)
                
            except Exception as e:
                print(f"⚠️ Error enriching task {getattr(task, 'id', 'unknown')}: {e}")
                continue
        
        return enriched

    def _enrich_messages(self, messages, search_term):
        """Enrich message results with additional info"""
        enriched = []
        
        for message in messages:
            try:
                # Get related record info
                related_name = "Unknown"
                related_type = message.model
                
                if message.model == 'project.project' and message.res_id:
                    try:
                        project = self.projects.browse(message.res_id)
                        related_name = project.name
                    except:
                        related_name = f"Project {message.res_id}"
                        
                elif message.model == 'project.task' and message.res_id:
                    try:
                        task = self.tasks.browse(message.res_id)
                        related_name = task.name
                    except:
                        related_name = f"Task {message.res_id}"
                
                enriched_message = {
                    'id': message.id,
                    'subject': getattr(message, 'subject', '') or 'No subject',
                    'body': getattr(message, 'body', '') or '',
                    'author': message.author_id.name if message.author_id else 'System',
                    'date': str(message.date) if message.date else '',
                    'model': message.model,
                    'res_id': message.res_id,
                    'related_name': related_name,
                    'related_type': related_type,
                    'type': 'message',
                    'search_term': search_term
                }
                enriched.append(enriched_message)
                
            except Exception as e:
                print(f"⚠️ Error enriching message {message.id}: {e}")
                continue
        
        return enriched

    def print_results(self, results, limit=None):
        """Print search results in a tree-like hierarchical format"""
        total_found = len(results.get('projects', [])) + len(results.get('tasks', [])) + len(results.get('messages', [])) + len(results.get('files', []))
        
        if total_found == 0:
            # Clear the search progress line
            if not self.verbose:
                print("\r" + " " * 80 + "\r", end="")
            print("📭 No results found.")
            return
        
        # Clear the search progress line and show results
        if not self.verbose:
            print("\r" + " " * 80 + "\r", end="")
        
        print(f"📊 SEARCH RESULTS SUMMARY")
        print(f"=" * 50)
        print(f"📂 Projects: {len(results.get('projects', []))}")
        print(f"📋 Tasks: {len(results.get('tasks', []))}")
        print(f"💬 Messages: {len(results.get('messages', []))}")
        print(f"📁 Files: {len(results.get('files', []))}")
        print(f"📊 Total: {total_found}")
        
        # Build hierarchical structure
        hierarchy = self._build_hierarchy(results, limit)
        
        # Print hierarchical results
        self._print_hierarchy(hierarchy)

    def _build_hierarchy(self, results, limit=None):
        """Build a hierarchical structure of results organized by projects"""
        hierarchy = {
            'projects': {},  # project_id -> project data + children
            'orphaned_tasks': [],  # tasks without projects
            'orphaned_messages': [],  # messages not linked to found projects/tasks
            'orphaned_files': []  # files not linked to found projects/tasks
        }
        
        # Sort all results by date descending
        for result_type in ['projects', 'tasks', 'messages', 'files']:
            if results.get(result_type):
                date_field = 'date' if result_type == 'messages' else ('create_date' if result_type == 'files' else 'write_date')
                results[result_type].sort(key=lambda x: x.get(date_field, ''), reverse=True)
        
        # First, organize projects
        for project in results.get('projects', []):
            project_id = project['id']
            hierarchy['projects'][project_id] = {
                'project': project,
                'tasks': [],
                'messages': [],
                'files': []
            }
        
        # Organize tasks
        for task in results.get('tasks', []):
            project_id = task.get('project_id')
            if project_id and project_id in hierarchy['projects']:
                hierarchy['projects'][project_id]['tasks'].append(task)
            else:
                hierarchy['orphaned_tasks'].append(task)
        
        # Organize messages
        for message in results.get('messages', []):
            placed = False
            
            # Try to place under project
            if message.get('related_type') == 'project.project' and message.get('res_id'):
                project_id = message['res_id']
                if project_id in hierarchy['projects']:
                    hierarchy['projects'][project_id]['messages'].append(message)
                    placed = True
            
            # Try to place under task's project
            elif message.get('related_type') == 'project.task' and message.get('res_id'):
                task_id = message['res_id']
                
                # First check if the task is in our found tasks and get its project
                task_project_id = None
                for task in results.get('tasks', []):
                    if task['id'] == task_id:
                        task_project_id = task.get('project_id')
                        break
                
                # If we found the task's project in our results, place the message there
                if task_project_id and task_project_id in hierarchy['projects']:
                    hierarchy['projects'][task_project_id]['messages'].append(message)
                    placed = True
                else:
                    # Fallback: search through all projects' tasks that are already grouped
                    for project_id, project_data in hierarchy['projects'].items():
                        for task in project_data['tasks']:
                            if task['id'] == task_id:
                                hierarchy['projects'][project_id]['messages'].append(message)
                                placed = True
                                break
                        if placed:
                            break
                    
                    # If still not placed, try to get the task from database to find its project
                    if not placed:
                        try:
                            # Look up the task directly to get its project
                            task_records = self.tasks.search_records([('id', '=', task_id)])
                            if task_records:
                                task = task_records[0]
                                if hasattr(task, 'project_id') and task.project_id:
                                    task_project_id = task.project_id.id if hasattr(task.project_id, 'id') else task.project_id
                                    if task_project_id in hierarchy['projects']:
                                        hierarchy['projects'][task_project_id]['messages'].append(message)
                                        placed = True
                        except Exception as e:
                            if self.verbose:
                                print(f"⚠️ Could not lookup task {task_id} for message placement: {e}")
            
            if not placed:
                hierarchy['orphaned_messages'].append(message)
        
        # Organize files
        for file in results.get('files', []):
            placed = False
            
            # Try to place under project
            if file.get('related_type') == 'Project' and file.get('related_id'):
                project_id = file['related_id']
                if project_id in hierarchy['projects']:
                    hierarchy['projects'][project_id]['files'].append(file)
                    placed = True
            
            # Try to place under task's project
            elif file.get('related_type') == 'Task' and file.get('related_id'):
                task_id = file['related_id']
                # Find which project this task belongs to
                for project_id, project_data in hierarchy['projects'].items():
                    for task in project_data['tasks']:
                        if task['id'] == task_id:
                            hierarchy['projects'][project_id]['files'].append(file)
                            placed = True
                            break
                    if placed:
                        break
            
            if not placed:
                hierarchy['orphaned_files'].append(file)
        
        return hierarchy

    def _print_hierarchy(self, hierarchy):
        """Print the hierarchical results"""
        project_count = 0
        
        # Print projects with their children
        for project_id, project_data in hierarchy['projects'].items():
            project_count += 1
            project = project_data['project']
            
            print(f"\n📂 PROJECT: {self._format_project_header(project)}")
            
            # Print project details
            self._print_project_details(project, indent="   ")
            
            # Determine what sections we have and their order
            sections = []
            if project_data['tasks']:
                sections.append(('tasks', f"📋 TASKS ({len(project_data['tasks'])})", project_data['tasks']))
            if project_data['messages']:
                sections.append(('messages', f"💬 MESSAGES ({len(project_data['messages'])})", project_data['messages']))
            if project_data['files']:
                sections.append(('files', f"📁 FILES ({len(project_data['files'])})", project_data['files']))
            
            # Print sections with proper tree structure
            for section_idx, (section_type, section_title, section_items) in enumerate(sections):
                is_last_section = section_idx == len(sections) - 1
                section_prefix = "   └──" if is_last_section else "   ├──"
                print(f"{section_prefix} {section_title}")
                
                for item_idx, item in enumerate(section_items):
                    is_last_item = item_idx == len(section_items) - 1
                    
                    if is_last_section and is_last_item:
                        # Last item in last section
                        item_prefix = "      └──"
                        item_indent = "         "
                    elif is_last_item:
                        # Last item in non-last section
                        item_prefix = "   │  └──"
                        item_indent = "   │     "
                    elif is_last_section:
                        # Non-last item in last section
                        item_prefix = "      ├──"
                        item_indent = "      │  "
                    else:
                        # Non-last item in non-last section
                        item_prefix = "   │  ├──"
                        item_indent = "   │  │  "
                    
                    if section_type == 'tasks':
                        self._print_task_item(item, item_prefix, item_indent)
                    elif section_type == 'messages':
                        self._print_message_item(item, item_prefix, item_indent)
                    elif section_type == 'files':
                        self._print_file_item(item, item_prefix, item_indent)
        
        # Print orphaned items
        if hierarchy['orphaned_tasks']:
            print(f"\n📋 TASKS WITHOUT PROJECTS ({len(hierarchy['orphaned_tasks'])})")
            print("-" * 40)
            for i, task in enumerate(hierarchy['orphaned_tasks'], 1):
                self._print_task_standalone(task, i)
        
        if hierarchy['orphaned_messages']:
            print(f"\n💬 STANDALONE MESSAGES ({len(hierarchy['orphaned_messages'])})")
            print("-" * 40)
            for i, message in enumerate(hierarchy['orphaned_messages'], 1):
                self._print_message_standalone(message, i)
        
        if hierarchy['orphaned_files']:
            print(f"\n📁 STANDALONE FILES ({len(hierarchy['orphaned_files'])})")
            print("-" * 40)
            for i, file in enumerate(hierarchy['orphaned_files'], 1):
                self._print_file_standalone(file, i)

    def _format_project_header(self, project):
        """Format project header with link"""
        project_url = self.get_project_url(project['id'])
        project_link = self.create_terminal_link(project_url, project['name'])
        return f"{project_link} (ID: {project['id']})"

    def _print_project_details(self, project, indent=""):
        """Print project details with proper indentation"""
        # Only show non-empty fields or when verbose
        if self.verbose or (project['partner'] and project['partner'] != 'No client'):
            print(f"{indent}🏢 {project['partner']}")
        if self.verbose or (project['user'] and project['user'] != 'Unassigned'):
            print(f"{indent}👤 {project['user']}")
        
        # Only show match indicators when verbose
        if self.verbose:
            if project['match_in_name']:
                print(f"{indent}✅ Match in name")
            if project['match_in_description'] and project['description']:
                print(f"{indent}✅ Match in description")
        
        # Show description if there's a match
        if project['match_in_description'] and project['description']:
            desc_snippet = project['description'][:400] + "..." if len(project['description']) > 400 else project['description']
            desc_snippet = desc_snippet.replace('\n', ' ').strip()
            print(f"{indent}📝 Description:")
            print(self._format_wrapped_text(desc_snippet, indent + "   "))
        
        print(f"{indent}📅 {project['write_date']}")

    def _print_task_item(self, task, prefix, indent):
        """Print a task item in the hierarchy"""
        task_url = self.get_task_url(task['id'])
        task_link = self.create_terminal_link(task_url, task['name'])
        print(f"{prefix} {task_link} (ID: {task['id']})")
        
        # Show task details with proper indentation
        if self.verbose or (task['user'] and task['user'] != 'Unassigned'):
            print(f"{indent}👤 {task['user']}")
        if self.verbose or (task['stage'] and task['stage'] != 'No stage'):
            print(f"{indent}📊 {task['stage']}")
        if self.verbose or (task['priority'] and task['priority'] != '0'):
            print(f"{indent}🔥 {task['priority']}")
        
        if self.verbose:
            if task['match_in_name']:
                print(f"{indent}✅ Match in name")
            if task['match_in_description'] and task['description']:
                print(f"{indent}✅ Match in description")
        
        if task['match_in_description'] and task['description']:
            desc_snippet = task['description'][:400] + "..." if len(task['description']) > 400 else task['description']
            desc_snippet = desc_snippet.replace('\n', ' ').strip()
            print(f"{indent}📝 Description:")
            print(self._format_wrapped_text(desc_snippet, indent + "   "))
        
        print(f"{indent}📅 {task['write_date']}")

    def _print_message_item(self, message, prefix, indent):
        """Print a message item in the hierarchy"""
        message_url = self.get_message_url(message['id'])
        message_link = self.create_terminal_link(message_url, message['subject'])
        print(f"{prefix} {message_link} (ID: {message['id']})")
        
        # Show message details with proper indentation
        if self.verbose or (message['author'] and message['author'] != 'System'):
            print(f"{indent}👤 {message['author']}")
        print(f"{indent}📅 {message['date']}")
        
        if message['body']:
            body_snippet = message['body'][:400] + "..." if len(message['body']) > 400 else message['body']
            body_snippet = body_snippet.replace('\n', ' ').strip()
            print(f"{indent}💬 Message:")
            print(self._format_wrapped_text(body_snippet, indent + "   "))

    def _print_file_item(self, file, prefix, indent):
        """Print a file item in the hierarchy"""
        file_url = self.get_file_url(file['id'])
        file_link = self.create_terminal_link(file_url, file['name'])
        print(f"{prefix} {file_link} (ID: {file['id']})")
        
        # Show file details with proper indentation
        if self.verbose or (file['mimetype'] and file['mimetype'] != 'Unknown'):
            print(f"{indent}📊 {file['mimetype']}")
        if self.verbose or file.get('file_size', 0) > 0:
            print(f"{indent}📏 {file['file_size_human']}")
        print(f"{indent}📅 {file['create_date']}")

    def _print_task_standalone(self, task, index):
        """Print a standalone task (not under a project)"""
        task_url = self.get_task_url(task['id'])
        task_link = self.create_terminal_link(task_url, task['name'])
        print(f"\n{index}. 📋 {task_link} (ID: {task['id']})")
        
        if self.verbose or (task['project_name'] and task['project_name'] != 'No project'):
            if task.get('project_id'):
                project_url = self.get_project_url(task['project_id'])
                project_link = self.create_terminal_link(project_url, task['project_name'])
                print(f"   📂 {project_link}")
            else:
                print(f"   📂 {task['project_name']}")
        if self.verbose or (task['user'] and task['user'] != 'Unassigned'):
            print(f"   👤 {task['user']}")
        if self.verbose or (task['stage'] and task['stage'] != 'No stage'):
            print(f"   📊 {task['stage']}")
        if self.verbose or (task['priority'] and task['priority'] != '0'):
            print(f"   🔥 {task['priority']}")
        
        if self.verbose:
            if task['match_in_name']:
                print(f"   ✅ Match in name")
            if task['match_in_description'] and task['description']:
                print(f"   ✅ Match in description")
        
        if task['match_in_description'] and task['description']:
            desc_snippet = task['description'][:400] + "..." if len(task['description']) > 400 else task['description']
            desc_snippet = desc_snippet.replace('\n', ' ').strip()
            print(f"   📝 Description:")
            print(self._format_wrapped_text(desc_snippet, "      "))
        
        print(f"   📅 {task['write_date']}")

    def _print_message_standalone(self, message, index):
        """Print a standalone message"""
        message_url = self.get_message_url(message['id'])
        message_link = self.create_terminal_link(message_url, message['subject'])
        print(f"\n{index}. 💬 {message_link} (ID: {message['id']})")
        
        # Create link for related record
        related_link = message['related_name']
        if message['related_type'] == 'project.project' and message['res_id']:
            related_url = self.get_project_url(message['res_id'])
            related_link = self.create_terminal_link(related_url, message['related_name'])
        elif message['related_type'] == 'project.task' and message['res_id']:
            related_url = self.get_task_url(message['res_id'])
            related_link = self.create_terminal_link(related_url, message['related_name'])
        
        print(f"   📎 {related_link} ({message['related_type']})")
        
        if self.verbose or (message['author'] and message['author'] != 'System'):
            print(f"   👤 {message['author']}")
        print(f"   📅 {message['date']}")
        
        if message['body']:
            body_snippet = message['body'][:400] + "..." if len(message['body']) > 400 else message['body']
            body_snippet = body_snippet.replace('\n', ' ').strip()
            print(f"   💬 Message:")
            print(self._format_wrapped_text(body_snippet, "      "))

    def _print_file_standalone(self, file, index):
        """Print a standalone file"""
        file_url = self.get_file_url(file['id'])
        file_link = self.create_terminal_link(file_url, file['name'])
        print(f"\n{index}. 📄 {file_link} (ID: {file['id']})")
        
        if self.verbose or (file['mimetype'] and file['mimetype'] != 'Unknown'):
            print(f"   📊 {file['mimetype']}")
        if self.verbose or file.get('file_size', 0) > 0:
            print(f"   📏 {file['file_size_human']}")
        
        # Create link for related record
        if file.get('related_type') and file.get('related_name'):
            related_link = file['related_name']
            if file['related_type'] == 'Project' and file.get('related_id'):
                related_url = self.get_project_url(file['related_id'])
                related_link = self.create_terminal_link(related_url, file['related_name'])
            elif file['related_type'] == 'Task' and file.get('related_id'):
                related_url = self.get_task_url(file['related_id'])
                related_link = self.create_terminal_link(related_url, file['related_name'])
            
            print(f"   📎 {related_link} ({file['related_type']})")
        
        if file.get('project_name') and file['related_type'] == 'Task':
            project_link = file['project_name']
            if file.get('project_id'):
                project_url = self.get_project_url(file['project_id'])
                project_link = self.create_terminal_link(project_url, file['project_name'])
            print(f"   📂 {project_link}")
        
        if file.get('assigned_user') and not str(file['assigned_user']).startswith('functools.partial'):
            if self.verbose or (file['assigned_user'] != 'Unassigned'):
                print(f"   👤 {file['assigned_user']}")
        
        if file.get('client'):
            if self.verbose or (file['client'] != 'No client'):
                print(f"   🏢 {file['client']}")
        
        print(f"   📅 {file['create_date']}")
        
        if self.verbose or file.get('public'):
            print(f"   🔗 {'Yes' if file.get('public') else 'No'}")
        
        if file.get('error'):
            print(f"   ⚠️ Error: {file['error']}")


    def _format_wrapped_text(self, text, indent, width=80, prefix="│ "):
        """
        Format text with proper wrapping and indentation with a vertical line indicator
        
        Args:
            text: Text to format
            indent: Base indentation string
            width: Maximum line width
            prefix: Prefix for each line (vertical line indicator)
            
        Returns:
            Formatted text with proper wrapping and indentation
        """
        if not text:
            return ""
        
        # Calculate available width for text (subtract indent and prefix)
        available_width = width - len(indent) - len(prefix)
        if available_width < 20:  # Minimum reasonable width
            available_width = 40
        
        # Wrap the text
        wrapped_lines = textwrap.wrap(text, width=available_width)
        
        # Format each line with indent and prefix
        formatted_lines = []
        for line in wrapped_lines:
            formatted_lines.append(f"{indent}{prefix}{line}")
        
        return "\n".join(formatted_lines)

    def download_file(self, file_id, output_path):
        """
        Download a file to local disk - uses shared download method
        
        Args:
            file_id: ID of the attachment to download
            output_path: Local path where to save the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.download_attachment(file_id, output_path)

    def get_file_statistics(self, files):
        """
        Generate statistics about files
        
        Args:
            files: List of enriched file results
            
        Returns:
            dict: Statistics about the files
        """
        if not files:
            return {}
        
        stats = {
            'total_files': len(files),
            'total_size': 0,
            'by_type': {},
            'by_project': {},
            'by_extension': {}
        }
        
        for file in files:
            # Total size
            stats['total_size'] += file.get('file_size', 0)
            
            # By MIME type
            mime_type = file.get('mimetype', 'Unknown')
            if mime_type in stats['by_type']:
                stats['by_type'][mime_type]['count'] += 1
                stats['by_type'][mime_type]['size'] += file.get('file_size', 0)
            else:
                stats['by_type'][mime_type] = {
                    'count': 1,
                    'size': file.get('file_size', 0)
                }
            
            # By project
            project_name = file.get('project_name', 'No project')
            if project_name in stats['by_project']:
                stats['by_project'][project_name] += 1
            else:
                stats['by_project'][project_name] = 1
            
            # By file extension
            filename = file.get('name', '')
            if '.' in filename:
                extension = filename.split('.')[-1].lower()
                if extension in stats['by_extension']:
                    stats['by_extension'][extension] += 1
                else:
                    stats['by_extension'][extension] = 1
        
        return stats

    def print_file_statistics(self, files):
        """Print file statistics in a nice format"""
        stats = self.get_file_statistics(files)
        
        if not stats:
            print("📊 No file statistics available")
            return
        
        print(f"\n📊 FILE STATISTICS")
        print(f"=" * 40)
        print(f"📁 Total files: {stats['total_files']}")
        print(f"💾 Total size: {self.format_file_size(stats['total_size'])}")
        
        # Top file types
        if stats['by_type']:
            print(f"\n📈 Top file types:")
            sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1]['count'], reverse=True)
            for i, (mime_type, type_stats) in enumerate(sorted_types[:5], 1):
                percentage = (type_stats['count'] / stats['total_files']) * 100
                size_human = self.format_file_size(type_stats['size'])
                print(f"   {i}. {mime_type:<25} {type_stats['count']:3} files ({percentage:4.1f}%) - {size_human}")
        
        # Top projects
        if stats['by_project']:
            print(f"\n📂 Files by project:")
            sorted_projects = sorted(stats['by_project'].items(), key=lambda x: x[1], reverse=True)
            for i, (project_name, count) in enumerate(sorted_projects[:5], 1):
                percentage = (count / stats['total_files']) * 100
                print(f"   {i}. {project_name:<30} {count:3} files ({percentage:4.1f}%)")
        
        # Top extensions
        if stats['by_extension']:
            print(f"\n📄 Top file extensions:")
            sorted_extensions = sorted(stats['by_extension'].items(), key=lambda x: x[1], reverse=True)
            for i, (extension, count) in enumerate(sorted_extensions[:5], 1):
                percentage = (count / stats['total_files']) * 100
                print(f"   {i}. .{extension:<10} {count:3} files ({percentage:4.1f}%)")

    def export_results(self, results, filename='text_search_results.csv'):
        """Export search results to CSV"""
        all_results = []
        
        # Combine all results
        for project in results.get('projects', []):
            all_results.append(project)
        for task in results.get('tasks', []):
            all_results.append(task)
        for message in results.get('messages', []):
            all_results.append(message)
        for file in results.get('files', []):
            all_results.append(file)
        
        if not all_results:
            print("❌ No results to export")
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                # Get all possible fieldnames
                fieldnames = set()
                for result in all_results:
                    fieldnames.update(result.keys())
                
                writer = csv.DictWriter(csvfile, fieldnames=sorted(fieldnames))
                writer.writeheader()
                
                for result in all_results:
                    # Convert all values to strings for CSV
                    csv_row = {k: str(v) if v is not None else '' for k, v in result.items()}
                    writer.writerow(csv_row)
            
            print(f"✅ {len(all_results)} results exported to {filename}")
            
        except Exception as e:
            print(f"❌ Export failed: {e}")


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(
        description='Odoo Project Text Search - Search through projects, tasks, and logs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python text_search.py "bug fix" --since "1 week"
  python text_search.py "client meeting" --since "3 days" --type projects
  python text_search.py "error" --since "2 weeks" --no-logs
  python text_search.py "urgent" --type tasks --no-descriptions
  python text_search.py "report" --include-files --file-types pdf docx
  python text_search.py "screenshot" --files-only --file-types png jpg
  python text_search.py "document" --include-files --stats
  python text_search.py "zoekterm" --since "3 dagen"
  python text_search.py "vergadering" --since "2 weken" --type projects
  
Download files:
  python text_search.py "report" --files-only --file-types pdf
  python text_search.py --download 12345 --download-path ./my_files/
        """
    )
    
    parser.add_argument('search_term', nargs='?', help='Text to search for (optional when using --download)')
    parser.add_argument('--since', help='Time reference (e.g., "1 week", "3 days", "2 months")')
    parser.add_argument('--type', choices=['all', 'projects', 'tasks', 'logs', 'files'], default='all',
                       help='What to search in (default: all). Use "files" to search ALL attachments regardless of model.')
    parser.add_argument('--no-logs', action='store_true',
                       help='Exclude search in log messages (logs included by default)')
    parser.add_argument('--no-files', action='store_true',
                       help='Exclude search in file names and metadata (files included by default)')
    parser.add_argument('--files-only', action='store_true',
                       help='Search only in files (equivalent to --type files)')
    parser.add_argument('--file-types', nargs='+', 
                       help='Filter by file types/extensions (e.g., pdf docx png)')
    parser.add_argument('--no-descriptions', action='store_true',
                       help='Do not search in descriptions, only names/subjects')
    parser.add_argument('--limit', type=int, help='Limit number of results to display')
    parser.add_argument('--export', help='Export results to CSV file')
    parser.add_argument('--download', type=int, metavar='FILE_ID',
                       help='Download file by ID (use with search results)')
    parser.add_argument('--download-path', default='./downloads/',
                       help='Directory to download files to (default: ./downloads/)')
    parser.add_argument('--stats', action='store_true',
                       help='Show file statistics (when files are included)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed search information and debug output')
    
    args = parser.parse_args()
    
    # Handle files-only flag
    if args.files_only:
        args.type = 'files'
        args.no_files = False
    
    # Handle download request
    if args.download:
        try:
            searcher = OdooTextSearch(verbose=args.verbose)
            filename = f"file_{args.download}"
            output_path = os.path.join(args.download_path, filename)
            success = searcher.download_file(args.download, output_path)
            if success:
                print(f"✅ Download completed!")
            return
        except Exception as e:
            print(f"❌ Download error: {e}")
            return
    
    # Check if search_term is provided when not downloading
    if not args.search_term:
        parser.error("search_term is required unless using --download")
    
    if args.verbose:
        print("🚀 Odoo Project Text Search")
        print("=" * 50)
    
    try:
        # Initialize searcher
        searcher = OdooTextSearch(verbose=args.verbose)
        
        # Perform search
        results = searcher.full_text_search(
            search_term=args.search_term,
            since=args.since,
            search_type=args.type,
            include_descriptions=not args.no_descriptions,
            include_logs=not args.no_logs,
            include_files=not args.no_files or args.type == 'files',
            file_types=args.file_types,
            limit=args.limit
        )
        
        # Print results
        searcher.print_results(results, limit=args.limit)
        
        # Show file statistics if requested and files are included
        if args.stats and results.get('files'):
            searcher.print_file_statistics(results['files'])
        
        # Export if requested
        if args.export:
            searcher.export_results(results, args.export)
        
        print(f"\n✅ Search completed successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()
