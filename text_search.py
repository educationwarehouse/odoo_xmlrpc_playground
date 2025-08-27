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
from dotenv import load_dotenv
from openerp_proxy import Client
from openerp_proxy.ext.all import *
import re
import csv
import html


class OdooTextSearch:
    """
    Advanced text search for Odoo projects and tasks
    
    Features:
    - Search in project/task names and descriptions
    - Search in log messages (mail.message)
    - Time-based filtering with human-readable dates
    - Efficient querying to avoid server overload
    """

    def __init__(self):
        """Initialize with .env configuration"""
        load_dotenv()

        self.host = os.getenv('ODOO_HOST')
        self.database = os.getenv('ODOO_DATABASE')
        self.user = os.getenv('ODOO_USER')
        self.password = os.getenv('ODOO_PASSWORD')

        if not all([self.host, self.database, self.user, self.password]):
            raise ValueError("❌ Configuration incomplete! Check your .env file.")

        self._connect()

    def _connect(self):
        """Connect to Odoo"""
        try:
            print(f"🔌 Connecting to Odoo...")
            print(f"   Host: {self.host}")
            print(f"   Database: {self.database}")
            print(f"   User: {self.user}")

            self.client = Client(
                host=self.host, 
                dbname=self.database, 
                user=self.user, 
                pwd=self.password, 
                port=443, 
                protocol='xml-rpcs'
            )

            print(f"✅ Connected as: {self.client.user.name} (ID: {self.client.uid})")

            # Model shortcuts
            self.projects = self.client['project.project']
            self.tasks = self.client['project.task']
            self.messages = self.client['mail.message']

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            raise

    def _parse_time_reference(self, time_ref):
        """
        Parse human-readable time references like:
        - "1 week", "2 weeks"
        - "3 days", "1 day"
        - "1 month", "2 months"
        - "1 year"
        """
        if not time_ref:
            return None

        time_ref = time_ref.lower().strip()
        
        # Pattern: number + unit
        pattern = r'(\d+)\s*(day|days|week|weeks|month|months|year|years)'
        match = re.match(pattern, time_ref)
        
        if not match:
            raise ValueError(f"Invalid time reference: {time_ref}. Use format like '1 week', '3 days', '2 months'")
        
        number = int(match.group(1))
        unit = match.group(2)
        
        now = datetime.now()
        
        if unit in ['day', 'days']:
            return now - timedelta(days=number)
        elif unit in ['week', 'weeks']:
            return now - timedelta(weeks=number)
        elif unit in ['month', 'months']:
            return now - timedelta(days=number * 30)  # Approximate
        elif unit in ['year', 'years']:
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
        print(f"🔍 Searching projects for: '{search_term}'")
        
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
            
            print(f"🔧 Project domain: {final_domain}")
            
            projects = self.projects.search_records(final_domain)
            print(f"📂 Found {len(projects)} matching projects")
            
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
        print(f"🔍 Searching tasks for: '{search_term}'")
        
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
            
            print(f"🔧 Task domain: {final_domain}")
            
            tasks = self.tasks.search_records(final_domain)
            print(f"📋 Found {len(tasks)} matching tasks")
            
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
        print(f"🔍 Searching messages for: '{search_term}'")
        
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
            
            print(f"🔧 Message domain: {final_domain}")
            
            messages = self.messages.search_records(final_domain)
            print(f"💬 Found {len(messages)} matching messages")
            
            return self._enrich_messages(messages, search_term)
            
        except Exception as e:
            print(f"❌ Error searching messages: {e}")
            return []

    def full_text_search(self, search_term, since=None, search_type='all', include_descriptions=True, include_logs=False):
        """
        Comprehensive text search across projects, tasks, and optionally logs
        
        Args:
            search_term: Text to search for
            since: Time reference string (e.g., "1 week", "3 days")
            search_type: 'all', 'projects', 'tasks', 'logs'
            include_descriptions: Search in descriptions
            include_logs: Search in log messages
        """
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
        print()
        
        results = {
            'projects': [],
            'tasks': [],
            'messages': []
        }
        
        try:
            # Search projects
            if search_type in ['all', 'projects']:
                results['projects'] = self.search_projects(search_term, since_date, include_descriptions)
            
            print()  # Add white line between searches
            
            # Search tasks
            if search_type in ['all', 'tasks']:
                results['tasks'] = self.search_tasks(search_term, since_date, include_descriptions)
            
            # Search messages/logs
            if include_logs and search_type in ['all', 'logs']:
                model_type = 'both' if search_type == 'all' else search_type
                results['messages'] = self.search_messages(search_term, since_date, model_type)
            
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
                        user_name = task.user_id.name if hasattr(task.user_id, 'name') else f'User {task.user_id.id}'
                    except:
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
        total_found = len(results.get('projects', [])) + len(results.get('tasks', [])) + len(results.get('messages', []))
        
        if total_found == 0:
            print("📭 No results found.")
            return
        
        print(f"\n📊 SEARCH RESULTS SUMMARY")
        print(f"=" * 50)
        print(f"📂 Projects: {len(results.get('projects', []))}")
        print(f"📋 Tasks: {len(results.get('tasks', []))}")
        print(f"💬 Messages: {len(results.get('messages', []))}")
        print(f"📊 Total: {total_found}")
        
        # Print projects
        if results.get('projects'):
            print(f"\n📂 PROJECTS ({len(results['projects'])})")
            print("-" * 40)
            for i, project in enumerate(results['projects'][:limit] if limit else results['projects'], 1):
                print(f"\n{i}. 📂 {project['name']} (ID: {project['id']})")
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
                print(f"\n{i}. 📋 {task['name']} (ID: {task['id']})")
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
                print(f"\n{i}. 💬 {message['subject']} (ID: {message['id']})")
                print(f"   📎 Related: {message['related_name']} ({message['related_type']})")
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
  python text_search.py "error" --since "2 weeks" --include-logs
  python text_search.py "urgent" --type tasks --no-descriptions
        """
    )
    
    parser.add_argument('search_term', help='Text to search for')
    parser.add_argument('--since', help='Time reference (e.g., "1 week", "3 days", "2 months")')
    parser.add_argument('--type', choices=['all', 'projects', 'tasks', 'logs'], default='all',
                       help='What to search in (default: all)')
    parser.add_argument('--include-logs', action='store_true',
                       help='Include search in log messages')
    parser.add_argument('--no-descriptions', action='store_true',
                       help='Do not search in descriptions, only names/subjects')
    parser.add_argument('--limit', type=int, help='Limit number of results to display')
    parser.add_argument('--export', help='Export results to CSV file')
    
    args = parser.parse_args()
    
    print("🚀 Odoo Project Text Search")
    print("=" * 50)
    
    try:
        # Initialize searcher
        searcher = OdooTextSearch()
        
        # Perform search
        results = searcher.full_text_search(
            search_term=args.search_term,
            since=args.since,
            search_type=args.type,
            include_descriptions=not args.no_descriptions,
            include_logs=args.include_logs
        )
        
        # Print results
        searcher.print_results(results, limit=args.limit)
        
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
