from pathlib import Path
import edwh
from edwh import improved_task as task
from invoke import Context


@task(
    help={
        'search_term': 'Required text to search for',
        'since': 'Time reference (e.g., "1 week", "3 days", "2 months")',
        'type': 'What to search in: all, projects, tasks, logs, files (default: all)',
        'no_logs': 'Exclude search in log messages (logs included by default)',
        'no_files': 'Exclude search in file names and metadata (files included by default)',
        'files_only': 'Search only in files (equivalent to --type files)',
        'file_types': 'Filter by file types/extensions (comma-separated, e.g., "pdf,docx,png")',
        'no_descriptions': 'Do not search in descriptions, only names/subjects',
        'limit': 'Limit number of results to display',
        'export': 'Export results to CSV file',
        'download': 'Download file by ID (use with search results)',
        'download_path': 'Directory to download files to (default: ./downloads/)',
        'stats': 'Show file statistics (when files are included)',
        'verbose': 'Show detailed search information and debug output'
    }, 
    positional=['search_term'],
    hookable=False
)
def search(c: Context, 
          search_term,
          since=None,
          type='all',
          no_logs=False,
          no_files=False,
          files_only=False,
          file_types=None,
          no_descriptions=False,
          limit=None,
          export=None,
          download=None,
          download_path='./downloads/',
          stats=False,
          verbose=False):
    """
    Odoo Project Text Search - Search through projects, tasks, and logs
    
    Examples:
        edwh odoo.search "bug fix" --since "1 week"
        edwh odoo.search "client meeting" --since "3 days" --type projects
        edwh odoo.search "error" --since "2 weeks" --no-logs
        edwh odoo.search "urgent" --type tasks --no-descriptions
        edwh odoo.search "report" --file-types "pdf,docx" --stats
        edwh odoo.search --download 12345 --download-path ./my_files/
    """
    from .text_search import OdooTextSearch
    import os
    
    # Validate search type
    valid_types = ['all', 'projects', 'tasks', 'logs', 'files']
    if type not in valid_types:
        print(f"❌ Error: Invalid search type '{type}'. Valid types are: {', '.join(valid_types)}")
        return
    
    # Handle files-only flag
    if files_only:
        type = 'files'
        no_files = False
    
    # Handle download request
    if download:
        try:
            searcher = OdooTextSearch(verbose=verbose)
            filename = f"file_{download}"
            output_path = os.path.join(download_path, filename)
            success = searcher.download_file(download, output_path)
            if success:
                print(f"✅ Download completed!")
            return
        except Exception as e:
            print(f"❌ Download error: {e}")
            return
    
    # Check if search_term is provided when not downloading
    if not search_term:
        print("❌ Error: search_term is required unless using --download")
        return
    
    # Parse file types if provided
    file_types_list = None
    if file_types:
        file_types_list = [ft.strip() for ft in file_types.split(',')]
    
    if verbose:
        print("🚀 Odoo Project Text Search")
        print("=" * 50)
    
    try:
        # Initialize searcher
        searcher = OdooTextSearch(verbose=verbose)
        
        # Perform search
        results = searcher.full_text_search(
            search_term=search_term,
            since=since,
            search_type=type,
            include_descriptions=not no_descriptions,
            include_logs=not no_logs,
            include_files=not no_files or type == 'files',
            file_types=file_types_list,
            limit=int(limit) if limit else None
        )
        
        # Print results
        searcher.print_results(results, limit=int(limit) if limit else None)
        
        # Show file statistics if requested and files are included
        if stats and results.get('files'):
            searcher.print_file_statistics(results['files'])
        
        # Export if requested
        if export:
            searcher.export_results(results, export)
        
        print(f"\n✅ Search completed successfully!")
        
        # Return results for potential use by other tasks (EDWH hookable pattern)
        return {
            'success': True,
            'results': results,
            'total_found': sum(len(results.get(key, [])) for key in ['projects', 'tasks', 'messages', 'files'])
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        # Return error state for hookable tasks
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'verbose': 'Show detailed setup information'
    },
    hookable=True
)
def setup(c: Context,
          verbose=False):
    """
    Setup Odoo Plugin - Create .env configuration file for Odoo connection
    
    This will interactively prompt for Odoo connection details and create
    a .env file with the necessary configuration.
    
    Examples:
        edwh odoo.setup
        edwh odoo.setup --verbose
    """

    if verbose:
        print("🚀 Setting up Odoo Plugin")
        print("=" * 50)
    
    try:
        # Only use config directory location
        config_dotenv = Path.home() / ".config/edwh/edwh_odoo_plugin.env"
        dotenv_path = config_dotenv
        
        if verbose:
            print(f"\n📁 Configuration file location: {config_dotenv.absolute()}")
        
        if config_dotenv.exists():
            if verbose:
                print(f"✅ Found existing config file")
            else:
                print(f"📁 Using config file: {config_dotenv.absolute()}")
        else:
            dotenv_path.parent.mkdir(parents=True, exist_ok=True)
            if verbose:
                print(f"📝 Will create new config file")
            else:
                print(f"📝 Will create new config file: {config_dotenv.absolute()}")

        # Check existing configuration first
        existing_config = {}
        if dotenv_path.exists():
            import os
            from dotenv import load_dotenv
            load_dotenv(dotenv_path)
            existing_config = {
                'host': os.getenv('ODOO_HOST', ''),
                'port': os.getenv('ODOO_PORT', ''),
                'protocol': os.getenv('ODOO_PROTOCOL', ''),
                'database': os.getenv('ODOO_DATABASE', ''),
                'user': os.getenv('ODOO_USER', ''),
                'password': os.getenv('ODOO_PASSWORD', '')
            }
            
            if verbose:
                print(f"🔍 Debug - Current config values:")
                for key, value in existing_config.items():
                    print(f"   {key}: '{value}' (empty: {not bool(value)})")
            
            # Check if configuration is complete (all values must be non-empty)
            config_complete = all(existing_config.values()) and all(val.strip() for val in existing_config.values())
            
            if verbose:
                print(f"🔍 Debug - Config complete: {config_complete}")
            
            if config_complete:
                print("\n✅ Configuration already up to date - nothing changed!")
                print(f"📁 Current configuration in: {dotenv_path.absolute()}")
                print("\n📋 Current settings:")
                print(f"   Host: {existing_config['host']}")
                print(f"   Port: {existing_config['port']}")
                print(f"   Protocol: {existing_config['protocol']}")
                print(f"   Database: {existing_config['database']}")
                print(f"   User: {existing_config['user']}")
                print(f"   Password: {'*' * len(existing_config['password']) if existing_config['password'] else '(not set)'}")
                
                return {
                    'success': True,
                    'message': 'Configuration already up to date',
                    'changed': False,
                    'config': {
                        'host': existing_config['host'],
                        'port': existing_config['port'],
                        'protocol': existing_config['protocol'],
                        'database': existing_config['database'],
                        'user': existing_config['user']
                    }
                }

        # Interactive setup for Odoo connection
        print("\n📋 Odoo Connection Setup")
        print("Please provide your Odoo connection details:")
        
        odoo_host = edwh.check_env(
            key="ODOO_HOST",
            default="your-odoo-instance.odoo.com",
            comment="Odoo server hostname (e.g., your-company.odoo.com)",
            env_path=dotenv_path,
        )
        
        odoo_port = edwh.check_env(
            key="ODOO_PORT",
            default="443",
            env_path=dotenv_path,
            comment="Odoo server port (443 for HTTPS, 80 for HTTP, 8069 for development)"
        )
        
        odoo_protocol = edwh.check_env(
            key="ODOO_PROTOCOL",
            default="xml-rpcs",
            comment="Odoo protocol (xml-rpcs for HTTPS, xml-rpc for HTTP)",
            env_path=dotenv_path,
            allowed_values=("xml-rpc", "xml-rpcs")
        )
        
        odoo_database = edwh.check_env(
            key="ODOO_DATABASE", 
            default="your-database-name",
            env_path=dotenv_path,
            comment="Odoo database name"
        )
        
        odoo_user = edwh.check_env(
            key="ODOO_USER",
            default="your-username@company.com",
            env_path=dotenv_path,
            comment="Odoo username/email"
        )
        
        odoo_password = edwh.check_env(
            key="ODOO_PASSWORD",
            default="",
            env_path=dotenv_path,
            comment="Odoo password"
        )
        
        if not odoo_password:
            print("❌ Error: Password is required for Odoo authentication")
            return {
                'success': False,
                'error': 'Password is required'
            }

        # New configuration
        new_config = {
            'host': odoo_host,
            'port': odoo_port,
            'protocol': odoo_protocol,
            'database': odoo_database,
            'user': odoo_user,
            'password': odoo_password
        }

        # Test connection
        if verbose:
            print("\n🔍 Testing Odoo connection...")
            
        try:
            from .odoo_base import OdooBase
            test_connection = OdooBase(verbose=verbose)
            test_connection._connect()
            print("✅ Odoo connection test successful!")
        except Exception as conn_error:
            print(f"⚠️  Connection test failed: {conn_error}")
            if not edwh.confirm("Connection test failed. Continue anyway? [yN] "):
                return {
                    'success': False,
                    'error': f'Connection test failed: {conn_error}'
                }
        
        print(f"\n✅ Odoo plugin setup completed successfully!")
        print(f"📁 Configuration saved to: {dotenv_path.absolute()}")
        print(f"\n🚀 You can now use:")
        print(f"   edwh odoo.search 'your search term'")
        print(f"   edwh odoo.web")
        
        # Return success state for hookable tasks
        return {
            'success': True,
            'message': 'Odoo plugin setup completed successfully',
            'changed': True,
            'config': {
                'host': odoo_host,
                'port': odoo_port,
                'protocol': odoo_protocol,
                'database': odoo_database,
                'user': odoo_user
            }
        }
        
    except KeyboardInterrupt:
        print(f"\n🛑 Setup cancelled by user")
        return {
            'success': False,
            'error': 'Setup cancelled by user'
        }
    except Exception as e:
        print(f"❌ Setup error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        # Return error state for hookable tasks
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'host': 'Host to bind to (default: localhost)',
        'port': 'Port to bind to (default: 1900)',
        'browser': 'Open browser automatically (default: False)',
        'verbose': 'Show detailed server information'
    },
    hookable=True
)
def web(c: Context,
        host='localhost',
        port=1900,
        browser=False,
        verbose=False):
    """
    Start Odoo Web Search Server - Web interface for Odoo text search
    
    Examples:
        edwh odoo.web
        edwh odoo.web --port 8080 --host 0.0.0.0
        edwh odoo.web --browser
    """
    from .web_search_server import WebSearchServer
    import os
    
    if verbose:
        print("🚀 Starting Odoo Web Search Server")
        print("=" * 50)
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("⚠️  No .env file found. You can configure settings through the web interface.")
        print("   Or create a .env file with your Odoo credentials.")
    
    try:
        # Start server
        server = WebSearchServer(host=host, port=int(port))
        server.start(open_browser=browser)
        
        return {
            'success': True,
            'message': 'Server started successfully',
            'host': host,
            'port': port
        }
        
    except KeyboardInterrupt:
        print(f"\n🛑 Server stopped by user")
        return {
            'success': True,
            'message': 'Server stopped by user'
        }
    except Exception as e:
        print(f"❌ Server error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'subtask_id': 'ID of the subtask to move',
        'new_parent_id': 'ID of the new parent task',
        'project_id': 'Optional: Move to different project (project ID)',
        'verbose': 'Show detailed information'
    },
    positional=['subtask_id', 'new_parent_id'],
    hookable=True
)
def move_subtask(c: Context,
                subtask_id: int,
                new_parent_id: int,
                project_id: int = None,
                verbose: bool = False):
    """
    Move a subtask to a new parent task, optionally changing project
    
    Examples:
        edwh odoo.move-subtask 123 456
        edwh odoo.move-subtask 123 456 --project-id 789
        edwh odoo.move-subtask 123 456 --verbose
    """
    from .task_manager import TaskManager
    
    if verbose:
        print("🔄 Moving Subtask")
        print("=" * 30)
    
    try:
        manager = TaskManager(verbose=verbose)
        result = manager.move_subtask(subtask_id, new_parent_id, project_id)
        
        if result['success']:
            print(f"✅ Subtask moved successfully!")
            if verbose:
                print(f"   Subtask: {result['subtask_name']} (ID: {subtask_id})")
                print(f"   New parent: {result['new_parent_name']} (ID: {new_parent_id})")
                if project_id:
                    print(f"   Project: {result['project_name']} (ID: {project_id})")
        else:
            print(f"❌ Failed to move subtask: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'task_id': 'ID of the task to promote to main task',
        'verbose': 'Show detailed information'
    },
    positional=['task_id'],
    hookable=True
)
def promote_task(c: Context,
                task_id: int,
                verbose: bool = False):
    """
    Promote a subtask to a main task (remove parent relationship)
    
    Examples:
        edwh odoo.promote-task 123
        edwh odoo.promote-task 123 --verbose
    """
    from .task_manager import TaskManager
    
    if verbose:
        print("⬆️ Promoting Task")
        print("=" * 30)
    
    try:
        manager = TaskManager(verbose=verbose)
        result = manager.promote_task(task_id)
        
        if result['success']:
            print(f"✅ Task promoted successfully!")
            if verbose:
                print(f"   Task: {result['task_name']} (ID: {task_id})")
                print(f"   Former parent: {result['former_parent_name']}")
        else:
            print(f"❌ Failed to promote task: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'subtask_ids': 'Comma-separated list of subtask IDs to move',
        'new_parent_id': 'ID of the new parent task',
        'project_id': 'Optional: Move to different project (project ID)',
        'verbose': 'Show detailed information'
    },
    positional=['subtask_ids', 'new_parent_id'],
    hookable=True
)
def move_subtasks(c: Context,
                 subtask_ids: str,
                 new_parent_id: int,
                 project_id: int = None,
                 verbose: bool = False):
    """
    Move multiple subtasks to a new parent task, optionally changing project
    
    Examples:
        edwh odoo.move-subtasks "123,124,125" 456
        edwh odoo.move-subtasks "123,124,125" 456 --project-id 789
    """
    from .task_manager import TaskManager
    
    # Parse subtask IDs
    try:
        ids = [int(id.strip()) for id in subtask_ids.split(',')]
    except ValueError:
        print("❌ Error: Invalid subtask IDs format. Use comma-separated integers.")
        return {'success': False, 'error': 'Invalid ID format'}
    
    if verbose:
        print("🔄 Moving Multiple Subtasks")
        print("=" * 40)
        print(f"   Moving {len(ids)} subtasks to parent {new_parent_id}")
    
    try:
        manager = TaskManager(verbose=verbose)
        result = manager.move_multiple_subtasks(ids, new_parent_id, project_id)
        
        if result['success']:
            print(f"✅ {result['moved_count']}/{len(ids)} subtasks moved successfully!")
            if result['failed_count'] > 0:
                print(f"⚠️ {result['failed_count']} subtasks failed to move")
                if verbose:
                    for error in result['errors']:
                        print(f"   - {error}")
        else:
            print(f"❌ Failed to move subtasks: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'search_term': 'Search term to find tasks',
        'verbose': 'Show detailed information'
    },
    hookable=True
)
def move_task_interactive(c: Context,
                         search_term: str = None,
                         verbose: bool = False):
    """
    Interactive task mover with search functionality
    
    Examples:
        edwh odoo.move-task-interactive
        edwh odoo.move-task-interactive "bug fix"
    """
    from .task_manager import TaskManager
    
    if verbose:
        print("🔍 Interactive Task Mover")
        print("=" * 40)
    
    try:
        manager = TaskManager(verbose=verbose)
        result = manager.interactive_move(search_term)
        
        return result
        
    except KeyboardInterrupt:
        print(f"\n🛑 Interactive mode cancelled by user")
        return {'success': False, 'error': 'Cancelled by user'}
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'task_id': 'ID of the task to show hierarchy for',
        'depth': 'Maximum depth to show (default: 3)',
        'verbose': 'Show detailed information'
    },
    positional=['task_id'],
    hookable=True
)
def show_task_hierarchy(c: Context,
                       task_id: int,
                       depth: int = 3,
                       verbose: bool = False):
    """
    Show task hierarchy (parent and children) for a given task
    
    Examples:
        edwh odoo.show-task-hierarchy 123
        edwh odoo.show-task-hierarchy 123 --depth 5
    """
    from .task_manager import TaskManager
    
    if verbose:
        print("🌳 Task Hierarchy")
        print("=" * 30)
    
    try:
        manager = TaskManager(verbose=verbose)
        result = manager.show_hierarchy(task_id, depth)
        
        if result['success']:
            manager.print_hierarchy(result['hierarchy'])
        else:
            print(f"❌ Failed to get hierarchy: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'project_id': 'ID of the project to show hierarchy for',
        'depth': 'Maximum depth to show for task subtasks (default: 3)',
        'verbose': 'Show detailed information (use multiple times: -v, -vv, -vvv)',
        'debug': 'Show debug information (equivalent to -vvv)'
    },
    positional=['project_id'],
    hookable=True
)
def show_project_hierarchy(c: Context,
                          project_id: int,
                          depth: int = 3,
                          verbose: bool = False,
                          debug: bool = False):
    """
    Show complete project hierarchy with all tasks and their subtasks
    
    Verbosity levels:
        (none)  - Clean, essential info only
        -v      - Add task details (assigned users, stages, priorities, dates)
        -vv     - Add connection info and processing details
        -vvv    - Add debug information and field extraction details
        --debug - Same as -vvv
    
    Examples:
        edwh odoo.show-project-hierarchy 123
        edwh odoo.show-project-hierarchy 123 --depth 5 -v
        edwh odoo.show-project-hierarchy 123 -vv
        edwh odoo.show-project-hierarchy 123 --debug
    """
    from .task_manager import TaskManager
    
    # Handle debug flag
    if debug:
        verbosity_level = 3
    else:
        # Count the number of -v flags passed
        verbosity_level = 1 if verbose else 0
        # For now, we'll use a simple boolean to int conversion
        # In the future, we could implement counting multiple -v flags
    
    if verbosity_level >= 2:
        print("🌳 Project Hierarchy")
        print("=" * 30)
    
    try:
        manager = TaskManager(verbosity_level=verbosity_level)
        result = manager.show_project_hierarchy(project_id, depth)
        
        if result['success']:
            manager.print_project_hierarchy(result['hierarchy'])
        else:
            print(f"❌ Failed to get project hierarchy: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbosity_level >= 2:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }
