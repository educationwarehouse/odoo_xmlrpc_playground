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
from odoo_base import OdooBase


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

    def _parse_time_reference(self, time_ref):
        """
        Parse human-readable time references in English and Dutch:
        English: "1 week", "2 weeks", "3 days", "1 day", "1 month", "2 months", "1 year"
        Dutch: "1 week", "2 weken", "3 dagen", "1 dag", "1 maand", "2 maanden", "1 jaar"
        """
        if not time_ref:
            return None

        time_ref = time_ref.lower().strip()
        
        # Pattern: number + unit (English and Dutch)
        pattern = r'(\d+)\s*(day|days|dag|dagen|week|weeks|weken|month|months|maand|maanden|year|years|jaar|jaren)'
        match = re.match(pattern, time_ref)
        
        if not match:
            raise ValueError(f"Invalid time reference: {time_ref}. Use format like '1 week'/'1 week', '3 days'/'3 dagen', '2 months'/'2 maanden'")
        
        number = int(match.group(1))
        unit = match.group(2)
        
        now = datetime.now()
        
        # English and Dutch day units
        if unit in ['day', 'days', 'dag', 'dagen']:
            return now - timedelta(days=number)
        # English and Dutch week units
        elif unit in ['week', 'weeks', 'weken']:
            return now - timedelta(weeks=number)
        # English and Dutch month units
        elif unit in ['month', 'months', 'maand', 'maanden']:
            return now - timedelta(days=number * 30)  # Approximate
        # English and Dutch year units
        elif unit in ['year', 'years', 'jaar', 'jaren']:
            return now - timedelta(days=number * 365)  # Approximate
        
        return None

    def search_projects(self, search_term, since=None, include_descriptions=True):
        """
        Search in project names and descriptions
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            include_descriptions: Whether to search in descriptions
        """
        if self.verbose:
            print(f"🔍 Searching projects for: '{search_term}'")
        else:
            print(f"🔍 Searching projects...", end="", flush=True)
        
        try:
            # Build domain for project search
            domain = []
            
            # Time filter
            if since:
                domain.append(('write_date', '>=', since.strftime('%Y-%m-%d %H:%M:%S')))
            
            # Text search in name
            name_domain = [('name', 'ilike', search_term)]
            
            if include_descriptions:
                # Search in both name and description
                text_domain = ['|', ('name', 'ilike', search_term), ('description', 'ilike', search_term)]
            else:
                text_domain = name_domain
            
            # Combine domains
            if domain:
                final_domain = ['&'] + domain + text_domain
            else:
                final_domain = text_domain
            
            if self.verbose:
                print(f"🔧 Project domain: {final_domain}")
            
            projects = self.projects.search_records(final_domain)
            
            if self.verbose:
                print(f"📂 Found {len(projects)} matching projects")
            else:
                print(f" {len(projects)} found", flush=True)
            
            return self._enrich_projects(projects, search_term)
            
        except Exception as e:
            print(f"❌ Error searching projects: {e}")
            return []

    def search_tasks(self, search_term, since=None, include_descriptions=True, project_ids=None):
        """
        Search in task names and descriptions
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            include_descriptions: Whether to search in descriptions
            project_ids: Limit to specific projects
        """
        if self.verbose:
            print(f"🔍 Searching tasks for: '{search_term}'")
        else:
            print(f"🔍 Searching tasks...", end="", flush=True)
        
        try:
            # Build domain for task search
            domain = []
            
            # Time filter
            if since:
                domain.append(('write_date', '>=', since.strftime('%Y-%m-%d %H:%M:%S')))
            
            # Project filter
            if project_ids:
                domain.append(('project_id', 'in', project_ids))
            
            # Text search
            if include_descriptions:
                text_domain = ['|', ('name', 'ilike', search_term), ('description', 'ilike', search_term)]
            else:
                text_domain = [('name', 'ilike', search_term)]
            
            # Combine domains
            if domain:
                final_domain = domain + ['&'] + text_domain if len(domain) == 1 else domain + text_domain
                # Properly structure the domain
                if len(domain) == 1:
                    final_domain = ['&'] + domain + text_domain
                else:
                    # Multiple conditions - build properly
                    final_domain = domain[:]
                    for condition in text_domain:
                        final_domain = ['&'] + final_domain + [condition] if isinstance(condition, tuple) else final_domain + [condition]
            else:
                final_domain = text_domain
            
            if self.verbose:
                print(f"🔧 Task domain: {final_domain}")
            
            tasks = self.tasks.search_records(final_domain)
            
            if self.verbose:
                print(f"📋 Found {len(tasks)} matching tasks")
            else:
                print(f" {len(tasks)} found", flush=True)
            
            return self._enrich_tasks(tasks, search_term)
            
        except Exception as e:
            print(f"❌ Error searching tasks: {e}")
            return []

    def search_messages(self, search_term, since=None, model_type='both'):
        """
        Search in mail messages (logs) for projects and tasks
        
        Args:
            search_term: Text to search for
            since: Datetime to limit search from
            model_type: 'projects', 'tasks', or 'both'
        """
        if self.verbose:
            print(f"🔍 Searching messages for: '{search_term}'")
        else:
            print(f"🔍 Searching messages...", end="", flush=True)
        
        try:
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
            
            messages = self.messages.search_records(final_domain)
            
            if self.verbose:
                print(f"💬 Found {len(messages)} matching messages")
            else:
                print(f" {len(messages)} found", flush=True)
            
            return self._enrich_messages(messages, search_term)
            
        except Exception as e:
            print(f"❌ Error searching messages: {e}")
            return []

    def search_files(self, search_term, since=None, file_types=None, model_type='both'):
        """
        Search in file names and metadata for all attachments
        
        Args:
            search_term: Text to search for in filenames
            since: Datetime to limit search from
            file_types: List of file extensions to filter by (e.g., ['pdf', 'docx'])
            model_type: 'projects', 'tasks', 'both', or 'all' (all includes any model)
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
            
            # Model filter - files attached to specific models or all
            if model_type != 'all':
                # Get all project and task IDs first
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
            
            files = self.attachments.search_records(final_domain)
            
            if self.verbose:
                print(f"📁 Found {len(files)} matching files")
            else:
                print(f" {len(files)} found", flush=True)
            
            return self._enrich_files(files, search_term)
            
        except Exception as e:
            print(f"❌ Error searching files: {e}")
            return []

    def full_text_search(self, search_term, since=None, search_type='all', include_descriptions=True, include_logs=True, include_files=True, file_types=None):
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
        """
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
            print()
        else:
            # Parse time reference
            since_date = None
            if since:
                since_date = self._parse_time_reference(since)
        
        results = {
            'projects': [],
            'tasks': [],
            'messages': [],
            'files': []
        }
        
        try:
            # Search projects
            if search_type in ['all', 'projects']:
                results['projects'] = self.search_projects(search_term, since_date, include_descriptions)
            
            if self.verbose:
                print()  # Add white line between searches
            
            # Search tasks
            if search_type in ['all', 'tasks']:
                results['tasks'] = self.search_tasks(search_term, since_date, include_descriptions)
            
            # Search messages/logs
            if include_logs and search_type in ['all', 'logs']:
                model_type = 'both' if search_type == 'all' else search_type
                results['messages'] = self.search_messages(search_term, since_date, model_type)
            
            # Search files
            if include_files or search_type == 'files':
                # Use 'all' for comprehensive file search when searching all or files specifically
                model_type = 'all' if search_type in ['all', 'files'] else search_type
                results['files'] = self.search_files(search_term, since_date, file_types, model_type)
            
            return results
            
        except Exception as e:
            print(f"❌ Error in full text search: {e}")
            return results

    def _enrich_projects(self, projects, search_term):
        """Enrich project results with additional info"""
        enriched = []
        
        for project in projects:
            try:
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
                            
                            # Handle user relationship safely
                            assigned_user = 'Unassigned'
                            if hasattr(task, 'user_id') and task.user_id:
                                try:
                                    # Try direct access first
                                    if hasattr(task.user_id, 'name') and task.user_id.name:
                                        assigned_user = task.user_id.name
                                    else:
                                        # Get the actual user ID value from the partial object
                                        try:
                                            # For partial objects, we need to get the actual ID value
                                            if hasattr(task.user_id, 'id'):
                                                user_id = task.user_id.id
                                            elif str(task.user_id).startswith('functools.partial'):
                                                # Try to call the partial object to get the actual value
                                                try:
                                                    user_id = task.user_id()
                                                    if self.verbose:
                                                        print(f"🔍 Partial object resolved to user ID: {user_id}")
                                                except Exception as partial_error:
                                                    if self.verbose:
                                                        print(f"⚠️ Could not resolve partial object: {partial_error}")
                                                    # Fallback to regex extraction
                                                    partial_str = str(task.user_id)
                                                    import re
                                                    id_match = re.search(r'\[(\d+)\]', partial_str)
                                                    if id_match:
                                                        user_id = int(id_match.group(1))
                                                    else:
                                                        assigned_user = 'User (partial object error)'
                                                        continue
                                            else:
                                                user_id = task.user_id
                                            
                                            if self.verbose:
                                                print(f"🔍 Looking up user ID {user_id} for file {file.id}")
                                            
                                            # Use search_records instead of browse for better error handling
                                            user_records = self.client['res.users'].search_records([('id', '=', user_id)])
                                            if user_records:
                                                assigned_user = user_records[0].name
                                            else:
                                                assigned_user = f'User {user_id} (not found)'
                                        except Exception as user_error:
                                            if self.verbose:
                                                print(f"⚠️ Error extracting user ID: {user_error}")
                                            assigned_user = 'User (ID extraction failed)'
                                except Exception as e:
                                    if self.verbose:
                                        print(f"⚠️ Could not get user info for file {file.id}: {e}")
                                    assigned_user = 'User (unavailable)'
                            
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
        """Enrich task results with additional info"""
        enriched = []
        
        for task in tasks:
            try:
                # Handle functools.partial objects by browsing the record properly
                if hasattr(task, 'id') and not hasattr(task, 'name'):
                    # This is likely a partial object, browse it properly
                    task = self.tasks.browse(task.id)
                
                # Safely get attributes with fallbacks
                task_name = getattr(task, 'name', f'Task {task.id}')
                task_description = getattr(task, 'description', '') or ''
                
                # Handle project relationship
                project_name = 'No project'
                project_id = None
                if hasattr(task, 'project_id') and task.project_id:
                    try:
                        project_name = task.project_id.name if hasattr(task.project_id, 'name') else f'Project {task.project_id.id}'
                        project_id = task.project_id.id if hasattr(task.project_id, 'id') else task.project_id
                    except:
                        project_name = 'Project (unavailable)'
                
                # Handle user relationship
                user_name = 'Unassigned'
                if hasattr(task, 'user_id') and task.user_id:
                    try:
                        # Try direct access first
                        if hasattr(task.user_id, 'name') and task.user_id.name:
                            user_name = task.user_id.name
                        else:
                            # Get the actual user ID value from the partial object
                            try:
                                # For partial objects, we need to get the actual ID value
                                if hasattr(task.user_id, 'id'):
                                    user_id = task.user_id.id
                                elif str(task.user_id).startswith('functools.partial'):
                                    # Try to call the partial object to get the actual value
                                    try:
                                        user_id = task.user_id()
                                        if self.verbose:
                                            print(f"🔍 Partial object resolved to user ID: {user_id}")
                                    except Exception as partial_error:
                                        if self.verbose:
                                            print(f"⚠️ Could not resolve partial object: {partial_error}")
                                        # Fallback to regex extraction
                                        partial_str = str(task.user_id)
                                        import re
                                        id_match = re.search(r'\[(\d+)\]', partial_str)
                                        if id_match:
                                            user_id = int(id_match.group(1))
                                        else:
                                            user_name = 'User (partial object error)'
                                            continue
                                else:
                                    user_id = task.user_id
                                
                                if self.verbose:
                                    print(f"🔍 Looking up user ID {user_id} for task {task.id}")
                                
                                # Use search_records instead of browse for better error handling
                                user_records = self.client['res.users'].search_records([('id', '=', user_id)])
                                if user_records:
                                    user_name = user_records[0].name
                                else:
                                    user_name = f'User {user_id} (not found)'
                            except Exception as user_error:
                                if self.verbose:
                                    print(f"⚠️ Error extracting user ID: {user_error}")
                                user_name = 'User (ID extraction failed)'
                    except Exception as e:
                        if self.verbose:
                            print(f"⚠️ Could not get user info for task {task.id}: {e}")
                        user_name = 'User (unavailable)'
                
                enriched_task = {
                    'id': task.id,
                    'name': task_name,
                    'description': task_description,
                    'project_name': project_name,
                    'project_id': project_id,
                    'stage': getattr(task, 'stage_id', None),
                    'user': user_name,
                    'priority': getattr(task, 'priority', '0'),
                    'create_date': str(getattr(task, 'create_date', '')) if getattr(task, 'create_date', None) else '',
                    'write_date': str(getattr(task, 'write_date', '')) if getattr(task, 'write_date', None) else '',
                    'type': 'task',
                    'search_term': search_term,
                    'match_in_name': search_term.lower() in task_name.lower(),
                    'match_in_description': search_term.lower() in task_description.lower()
                }
                enriched.append(enriched_task)
                
            except Exception as e:
                print(f"⚠️ Error enriching task {getattr(task, 'id', 'unknown')}: {e}")
                # Add minimal info even if enrichment fails
                try:
                    enriched.append({
                        'id': getattr(task, 'id', 'unknown'),
                        'name': f'Task {getattr(task, "id", "unknown")} (error)',
                        'description': '',
                        'project_name': 'Unknown',
                        'project_id': None,
                        'stage': None,
                        'user': 'Unknown',
                        'priority': '0',
                        'create_date': '',
                        'write_date': '',
                        'type': 'task',
                        'search_term': search_term,
                        'match_in_name': False,
                        'match_in_description': False,
                        'error': str(e)
                    })
                except:
                    pass
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
        """Print search results in a nice format"""
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
        
        # Sort all results by date descending
        for result_type in ['projects', 'tasks', 'messages', 'files']:
            if results.get(result_type):
                # Sort by write_date for projects/tasks, date for messages, create_date for files
                date_field = 'date' if result_type == 'messages' else ('create_date' if result_type == 'files' else 'write_date')
                results[result_type].sort(key=lambda x: x.get(date_field, ''), reverse=True)
        
        # Print projects
        if results.get('projects'):
            print(f"\n📂 PROJECTS ({len(results['projects'])})")
            print("-" * 40)
            for i, project in enumerate(results['projects'][:limit] if limit else results['projects'], 1):
                project_url = self.get_project_url(project['id'])
                project_link = self.create_terminal_link(project_url, project['name'])
                print(f"\n{i}. 📂 {project_link} (ID: {project['id']})")
                print(f"   🏢 Client: {project['partner']}")
                print(f"   👤 Manager: {project['user']}")
                if project['match_in_name']:
                    print(f"   ✅ Match in name")
                if project['match_in_description'] and project['description']:
                    print(f"   ✅ Match in description")
                    # Convert HTML to markdown and show snippet
                    markdown_desc = self._html_to_markdown(project['description'])
                    desc_snippet = markdown_desc[:200] + "..." if len(markdown_desc) > 200 else markdown_desc
                    # Replace newlines with spaces for compact display
                    desc_snippet = desc_snippet.replace('\n', ' ').strip()
                    print(f"   📝 Description: {desc_snippet}")
                print(f"   📅 Modified: {project['write_date']}")
        
        # Print tasks
        if results.get('tasks'):
            print(f"\n📋 TASKS ({len(results['tasks'])})")
            print("-" * 40)
            for i, task in enumerate(results['tasks'][:limit] if limit else results['tasks'], 1):
                task_url = self.get_task_url(task['id'])
                task_link = self.create_terminal_link(task_url, task['name'])
                print(f"\n{i}. 📋 {task_link} (ID: {task['id']})")
                print(f"   📂 Project: {task['project_name']}")
                print(f"   👤 Assigned: {task['user']}")
                print(f"   🔥 Priority: {task['priority']}")
                if task['match_in_name']:
                    print(f"   ✅ Match in name")
                if task['match_in_description'] and task['description']:
                    print(f"   ✅ Match in description")
                    # Convert HTML to markdown and show snippet
                    markdown_desc = self._html_to_markdown(task['description'])
                    desc_snippet = markdown_desc[:200] + "..." if len(markdown_desc) > 200 else markdown_desc
                    # Replace newlines with spaces for compact display
                    desc_snippet = desc_snippet.replace('\n', ' ').strip()
                    print(f"   📝 Description: {desc_snippet}")
                print(f"   📅 Modified: {task['write_date']}")
        
        # Print messages
        if results.get('messages'):
            print(f"\n💬 MESSAGES ({len(results['messages'])})")
            print("-" * 40)
            for i, message in enumerate(results['messages'][:limit] if limit else results['messages'], 1):
                message_url = self.get_message_url(message['id'])
                message_link = self.create_terminal_link(message_url, message['subject'])
                print(f"\n{i}. 💬 {message_link} (ID: {message['id']})")
                
                # Create link for related record
                related_link = message['related_name']
                if message['related_type'] == 'project.project' and message['res_id']:
                    related_url = self.get_project_url(message['res_id'])
                    related_link = self.create_terminal_link(related_url, message['related_name'])
                elif message['related_type'] == 'project.task' and message['res_id']:
                    related_url = self.get_task_url(message['res_id'])
                    related_link = self.create_terminal_link(related_url, message['related_name'])
                
                print(f"   📎 Related: {related_link} ({message['related_type']})")
                print(f"   👤 Author: {message['author']}")
                print(f"   📅 Date: {message['date']}")
                # Show snippet of body
                if message['body']:
                    # Convert HTML to markdown for better readability
                    markdown_body = self._html_to_markdown(message['body'])
                    body_snippet = markdown_body[:200] + "..." if len(markdown_body) > 200 else markdown_body
                    # Replace newlines with spaces for compact display
                    body_snippet = body_snippet.replace('\n', ' ').strip()
                    print(f"   💬 Message: {body_snippet}")
        
        # Print files
        if results.get('files'):
            print(f"\n📁 FILES ({len(results['files'])})")
            print("-" * 40)
            for i, file in enumerate(results['files'][:limit] if limit else results['files'], 1):
                file_url = self.get_file_url(file['id'])
                file_link = self.create_terminal_link(file_url, file['name'])
                print(f"\n{i}. 📄 {file_link} (ID: {file['id']})")
                print(f"   📊 Type: {file['mimetype']}")
                print(f"   📏 Size: {file['file_size_human']}")
                
                # Create link for related record
                if file.get('related_type') and file.get('related_name'):
                    related_link = file['related_name']
                    if file['related_type'] == 'Project' and file.get('related_id'):
                        related_url = self.get_project_url(file['related_id'])
                        related_link = self.create_terminal_link(related_url, file['related_name'])
                    elif file['related_type'] == 'Task' and file.get('related_id'):
                        related_url = self.get_task_url(file['related_id'])
                        related_link = self.create_terminal_link(related_url, file['related_name'])
                    
                    print(f"   📎 Attached to: {related_link} ({file['related_type']})")
                
                if file.get('project_name') and file['related_type'] == 'Task':
                    project_link = file['project_name']
                    if file.get('project_id'):
                        project_url = self.get_project_url(file['project_id'])
                        project_link = self.create_terminal_link(project_url, file['project_name'])
                    print(f"   📂 Project: {project_link}")
                
                if file.get('assigned_user') and not str(file['assigned_user']).startswith('functools.partial'):
                    print(f"   👤 Assigned: {file['assigned_user']}")
                
                if file.get('client'):
                    print(f"   🏢 Client: {file['client']}")
                
                print(f"   📅 Created: {file['create_date']}")
                print(f"   🔗 Public: {'Yes' if file.get('public') else 'No'}")
                
                if file.get('error'):
                    print(f"   ⚠️ Error: {file['error']}")

    def _html_to_markdown(self, html_content):
        """
        Convert HTML content to readable markdown-like text
        
        Args:
            html_content: HTML string to convert
            
        Returns:
            Cleaned markdown-like text
        """
        if not html_content:
            return ""
        
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

    def download_file(self, file_id, output_path):
        """
        Download a file to local disk
        
        Args:
            file_id: ID of the attachment to download
            output_path: Local path where to save the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # First get the attachment record with proper field access
            attachment_records = self.attachments.search_records([('id', '=', file_id)])
            
            if not attachment_records:
                print(f"❌ File with ID {file_id} not found")
                return False
            
            attachment = attachment_records[0]
            
            # Get the file name
            file_name = getattr(attachment, 'name', f'file_{file_id}')
            
            # Check if we have data
            if not hasattr(attachment, 'datas'):
                print(f"❌ No data field available for file {file_name}")
                return False
            
            # Get the data - handle both direct access and partial objects
            try:
                file_data_b64 = attachment.datas
                if hasattr(file_data_b64, '__call__'):
                    # It's a partial/callable, try to call it
                    file_data_b64 = file_data_b64()
                
                if not file_data_b64:
                    print(f"❌ No data available for file {file_name}")
                    return False
                
                # Decode base64 data
                file_data = base64.b64decode(file_data_b64)
                
            except Exception as data_error:
                print(f"❌ Error accessing file data: {data_error}")
                return False
            
            # Use original filename if no output_path directory specified
            if output_path.endswith('/') or os.path.isdir(output_path):
                output_path = os.path.join(output_path, file_name)
            elif not os.path.basename(output_path):
                output_path = os.path.join(output_path, file_name)
            
            # Create directory if needed
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Write file
            with open(output_path, 'wb') as f:
                f.write(file_data)
            
            print(f"✅ Downloaded: {file_name}")
            print(f"   To: {output_path}")
            print(f"   Size: {len(file_data)} bytes")
            
            return True
            
        except Exception as e:
            print(f"❌ Download failed: {e}")
            import traceback
            if self.verbose:
                print(f"   Traceback: {traceback.format_exc()}")
            return False

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
  python text_search.py "error" --since "2 weeks" --exclude-logs
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
    parser.add_argument('--exclude-logs', action='store_true',
                       help='Exclude search in log messages (logs included by default)')
    parser.add_argument('--exclude-files', action='store_true',
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
        args.exclude_files = False
    
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
            include_logs=not args.exclude_logs,
            include_files=not args.exclude_files or args.type == 'files',
            file_types=args.file_types
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
