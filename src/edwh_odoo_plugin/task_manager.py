#!/usr/bin/env python3
"""
Task Manager - Subtask Moving and Hierarchy Management
=====================================================

Provides functionality for:
- Moving subtasks between parent tasks
- Promoting subtasks to main tasks
- Bulk operations on multiple subtasks
- Interactive task moving with search
- Task hierarchy visualization

Author: Based on odoo_base.py
Date: December 2024
"""

import re
import time
from .odoo_base import OdooBase
from .text_search import OdooTextSearch


class TaskManager(OdooBase):
    """
    Task management functionality for moving subtasks and managing hierarchy
    """

    def __init__(self, verbose=False, verbosity_level=None):
        """Initialize with .env configuration"""
        # Handle both old verbose boolean and new verbosity_level
        if verbosity_level is not None:
            self.verbosity_level = verbosity_level
            verbose = verbosity_level > 0
        else:
            self.verbosity_level = 1 if verbose else 0
        
        super().__init__(verbose=verbose)
        self.searcher = OdooTextSearch(verbose=(verbosity_level > 0 if verbosity_level is not None else verbose))
        # Cache for task names to avoid repeated RPCs during hierarchy printing
        self._task_name_cache = {}

    def move_subtask(self, subtask_id, new_parent_id, target_project_id=None):
        """
        Move a subtask to a new parent task, optionally changing project
        
        Args:
            subtask_id: ID of the subtask to move
            new_parent_id: ID of the new parent task
            target_project_id: Optional project ID to move to
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Validate input IDs
            try:
                subtask_id = int(subtask_id)
                new_parent_id = int(new_parent_id)
                if target_project_id is not None:
                    target_project_id = int(target_project_id)
            except (ValueError, TypeError):
                return {
                    'success': False,
                    'error': 'Invalid ID format provided'
                }
            
            # Safe batch validation: get both tasks with error handling
            try:
                task_ids = [subtask_id, new_parent_id]
                task_records = self.tasks.search_records([('id', 'in', task_ids)])
            except Exception as search_error:
                return {
                    'success': False,
                    'error': f'Failed to search for tasks: {search_error}'
                }
            
            # Create lookup dict for found tasks with safe access
            found_tasks = {}
            for task in task_records:
                try:
                    found_tasks[task.id] = task
                except AttributeError:
                    continue
            
            # Validate subtask exists
            if subtask_id not in found_tasks:
                return {
                    'success': False,
                    'error': f'Subtask with ID {subtask_id} not found'
                }
            
            subtask = found_tasks[subtask_id]
            
            # Validate new parent exists
            if new_parent_id not in found_tasks:
                return {
                    'success': False,
                    'error': f'Parent task with ID {new_parent_id} not found'
                }
            
            new_parent = found_tasks[new_parent_id]
            
            # Validate project if specified - with safe access
            project_name = None
            if target_project_id:
                try:
                    project_records = self.projects.search_records([('id', '=', target_project_id)])
                    if not project_records:
                        return {
                            'success': False,
                            'error': f'Project with ID {target_project_id} not found'
                        }
                    project_name = getattr(project_records[0], 'name', f'Project {target_project_id}')
                except Exception as project_error:
                    return {
                        'success': False,
                        'error': f'Failed to validate project: {project_error}'
                    }
            
            # Check for circular dependency with error handling
            try:
                if self._would_create_circular_dependency(subtask_id, new_parent_id):
                    return {
                        'success': False,
                        'error': 'Cannot move task: would create circular dependency'
                    }
            except Exception as circular_error:
                if self.verbose:
                    print(f"⚠️ Could not check circular dependency: {circular_error}")
                # Continue anyway - better to allow the move than block it
            
            # Prepare update values
            vals = {"parent_id": new_parent_id}
            if target_project_id is not None:
                vals["project_id"] = target_project_id
            
            if self.verbose:
                print(f"🔄 Moving subtask {subtask_id} to parent {new_parent_id}")
                if target_project_id:
                    print(f"   Also moving to project {target_project_id}")
            
            # Perform the move with error handling
            try:
                success = self.tasks.write([subtask_id], vals)
            except Exception as write_error:
                return {
                    'success': False,
                    'error': f'Write operation failed: {write_error}'
                }
            
            if success:
                # Safe name access
                subtask_name = getattr(subtask, 'name', f'Task {subtask_id}')
                new_parent_name = getattr(new_parent, 'name', f'Task {new_parent_id}')
                
                return {
                    'success': True,
                    'subtask_name': subtask_name,
                    'new_parent_name': new_parent_name,
                    'project_name': project_name
                }
            else:
                return {
                    'success': False,
                    'error': 'Write operation returned False'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)[:200]}'  # Limit error message length
            }

    def promote_task(self, task_id):
        """
        Promote a subtask to a main task (remove parent relationship)
        
        Args:
            task_id: ID of the task to promote
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Validate task exists
            task_records = self.tasks.search_records([('id', '=', int(task_id))])
            if not task_records:
                return {
                    'success': False,
                    'error': f'Task with ID {task_id} not found'
                }
            
            task = task_records[0]
            
            # Check if task has a parent
            if not hasattr(task, 'parent_id') or not task.parent_id:
                return {
                    'success': False,
                    'error': 'Task is already a main task (no parent)'
                }
            
            former_parent_name = task.parent_id.name if hasattr(task.parent_id, 'name') else 'Unknown'
            
            if self.verbose:
                print(f"⬆️ Promoting task {task_id} to main task")
                print(f"   Removing parent: {former_parent_name}")
            
            # Remove parent relationship
            success = self.tasks.write([int(task_id)], {"parent_id": False})
            
            if success:
                return {
                    'success': True,
                    'task_name': task.name,
                    'former_parent_name': former_parent_name
                }
            else:
                return {
                    'success': False,
                    'error': 'Write operation failed'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def move_multiple_subtasks(self, subtask_ids, new_parent_id, target_project_id=None):
        """
        Move multiple subtasks to a new parent task
        
        Args:
            subtask_ids: List of subtask IDs to move
            new_parent_id: ID of the new parent task
            target_project_id: Optional project ID to move to
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Convert all IDs to integers
            int_subtask_ids = [int(sid) for sid in subtask_ids]
            int_parent_id = int(new_parent_id)
            int_project_id = int(target_project_id) if target_project_id else None
            
            # Batch validation: get parent and all subtasks in a single query
            all_task_ids = int_subtask_ids + [int_parent_id]
            task_records = self.tasks.search_records([('id', 'in', all_task_ids)])
            found_tasks = {task.id: task for task in task_records}
            
            # Validate new parent exists
            if int_parent_id not in found_tasks:
                return {
                    'success': False,
                    'error': f'Parent task with ID {new_parent_id} not found'
                }
            
            new_parent = found_tasks[int_parent_id]
            
            # Validate project if specified
            if int_project_id:
                project_records = self.projects.search_records([('id', '=', int_project_id)])
                if not project_records:
                    return {
                        'success': False,
                        'error': f'Project with ID {target_project_id} not found'
                    }
            
            moved_count = 0
            failed_count = 0
            errors = []
            
            for subtask_id in int_subtask_ids:
                try:
                    # Check for circular dependency
                    if self._would_create_circular_dependency(subtask_id, int_parent_id):
                        errors.append(f'Task {subtask_id}: would create circular dependency')
                        failed_count += 1
                        continue
                    
                    # Validate subtask exists (already fetched in batch)
                    if subtask_id not in found_tasks:
                        errors.append(f'Task {subtask_id}: not found')
                        failed_count += 1
                        continue
                    
                    # Prepare update values
                    vals = {"parent_id": int_parent_id}
                    if int_project_id is not None:
                        vals["project_id"] = int_project_id
                    
                    # Perform the move
                    success = self.tasks.write([subtask_id], vals)
                    
                    if success:
                        moved_count += 1
                        if self.verbose:
                            print(f"✅ Moved task {subtask_id}")
                    else:
                        errors.append(f'Task {subtask_id}: write operation failed')
                        failed_count += 1
                        
                except Exception as e:
                    errors.append(f'Task {subtask_id}: {str(e)}')
                    failed_count += 1
            
            return {
                'success': moved_count > 0,
                'moved_count': moved_count,
                'failed_count': failed_count,
                'errors': errors,
                'new_parent_name': new_parent.name
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def interactive_move(self, search_term=None):
        """
        Interactive task moving with search functionality
        
        Args:
            search_term: Optional initial search term
            
        Returns:
            dict: Result with success status
        """
        try:
            print("🔍 Interactive Task Mover")
            print("=" * 40)
            
            # Step 1: Find subtask to move
            if search_term:
                print(f"Searching for tasks with: '{search_term}'")
                results = self.searcher.search_tasks(search_term, limit=10)
            else:
                search_input = input("Enter search term to find subtask to move: ").strip()
                if not search_input:
                    return {'success': False, 'error': 'No search term provided'}
                results = self.searcher.search_tasks(search_input, limit=10)
            
            if not results:
                print("❌ No tasks found")
                return {'success': False, 'error': 'No tasks found'}
            
            # Display found tasks
            print(f"\n📋 Found {len(results)} tasks:")
            for i, task in enumerate(results, 1):
                parent_info = ""
                if task.get('parent_id'):
                    parent_info = f" (parent: {task.get('parent_name', 'Unknown')})"
                print(f"  {i}. {task['name']} (ID: {task['id']}){parent_info}")
            
            # Select subtask
            while True:
                try:
                    choice = input(f"\nSelect subtask to move (1-{len(results)}): ").strip()
                    if not choice:
                        return {'success': False, 'error': 'No selection made'}
                    
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(results):
                        selected_task = results[choice_idx]
                        break
                    else:
                        print(f"❌ Please enter a number between 1 and {len(results)}")
                except ValueError:
                    print("❌ Please enter a valid number")
            
            # Step 2: Find new parent
            parent_search = input(f"\nEnter search term to find new parent task: ").strip()
            if not parent_search:
                return {'success': False, 'error': 'No parent search term provided'}
            
            parent_results = self.searcher.search_tasks(parent_search, limit=10)
            if not parent_results:
                print("❌ No parent tasks found")
                return {'success': False, 'error': 'No parent tasks found'}
            
            # Display potential parents
            print(f"\n📋 Found {len(parent_results)} potential parent tasks:")
            for i, task in enumerate(parent_results, 1):
                print(f"  {i}. {task['name']} (ID: {task['id']})")
            
            # Select parent
            while True:
                try:
                    choice = input(f"\nSelect new parent task (1-{len(parent_results)}): ").strip()
                    if not choice:
                        return {'success': False, 'error': 'No parent selection made'}
                    
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(parent_results):
                        selected_parent = parent_results[choice_idx]
                        break
                    else:
                        print(f"❌ Please enter a number between 1 and {len(parent_results)}")
                except ValueError:
                    print("❌ Please enter a valid number")
            
            # Step 3: Optional project change
            project_id = None
            change_project = input(f"\nChange project? (y/N): ").strip().lower()
            if change_project in ['y', 'yes']:
                project_search = input("Enter search term to find project: ").strip()
                if project_search:
                    project_results = self.searcher.search_projects(project_search, limit=10)
                    if project_results:
                        print(f"\n📂 Found {len(project_results)} projects:")
                        for i, project in enumerate(project_results, 1):
                            print(f"  {i}. {project['name']} (ID: {project['id']})")
                        
                        while True:
                            try:
                                choice = input(f"\nSelect project (1-{len(project_results)}): ").strip()
                                if not choice:
                                    break
                                
                                choice_idx = int(choice) - 1
                                if 0 <= choice_idx < len(project_results):
                                    project_id = project_results[choice_idx]['id']
                                    break
                                else:
                                    print(f"❌ Please enter a number between 1 and {len(project_results)}")
                            except ValueError:
                                print("❌ Please enter a valid number")
            
            # Step 4: Confirm and execute
            print(f"\n📋 MOVE CONFIRMATION")
            print(f"   Subtask: {selected_task['name']} (ID: {selected_task['id']})")
            print(f"   New parent: {selected_parent['name']} (ID: {selected_parent['id']})")
            if project_id:
                project_name = next(p['name'] for p in project_results if p['id'] == project_id)
                print(f"   New project: {project_name} (ID: {project_id})")
            
            confirm = input(f"\nProceed with move? (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                return {'success': False, 'error': 'Move cancelled by user'}
            
            # Execute the move
            result = self.move_subtask(selected_task['id'], selected_parent['id'], project_id)
            
            if result['success']:
                print(f"\n✅ Task moved successfully!")
            else:
                print(f"\n❌ Move failed: {result['error']}")
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def show_hierarchy(self, task_id, max_depth=3):
        """
        Show task hierarchy for a given task
        
        Args:
            task_id: ID of the task to show hierarchy for
            max_depth: Maximum depth to traverse
            
        Returns:
            dict: Result with hierarchy data
        """
        try:
            # Get the main task
            task_records = self.tasks.search_records([('id', '=', int(task_id))])
            if not task_records:
                return {
                    'success': False,
                    'error': f'Task with ID {task_id} not found'
                }
            
            main_task = task_records[0]
            
            # Build hierarchy
            hierarchy = {
                'main_task': self._task_to_dict(main_task),
                'parents': self._get_parent_chain(task_id),
                'children': self._get_children_recursive(task_id, max_depth)
            }
            
            return {
                'success': True,
                'hierarchy': hierarchy
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def print_hierarchy(self, hierarchy):
        """Print task hierarchy in a tree format"""
        # Print parent chain
        if hierarchy['parents']:
            print("📈 PARENT CHAIN:")
            for i, parent in enumerate(hierarchy['parents']):
                indent = "  " * i
                print(f"{indent}└── {parent['name']} (ID: {parent['id']})")
        
        # Print main task
        print(f"\n🎯 MAIN TASK:")
        main = hierarchy['main_task']
        print(f"└── {main['name']} (ID: {main['id']})")
        if main.get('project_name'):
            print(f"    📂 Project: {main['project_name']}")
        if main.get('user'):
            print(f"    👤 Assigned: {main['user']}")
        
        # Print children
        if hierarchy['children']:
            print(f"\n📉 SUBTASKS:")
            self._print_children_recursive(hierarchy['children'], "")

    def _print_children_recursive(self, children, indent):
        """Recursively print children with proper indentation and clickable links"""
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            current_indent = "└──" if is_last else "├──"
            
            # Create clickable link for child task with bold name
            task_url = self.get_task_url(child['id'])
            task_link = self.create_terminal_link(task_url, f"\033[1m{child['name']}\033[0m")
            print(f"{indent}{current_indent} {task_link} (ID: {child['id']})")
            
            # Print detailed task information for child on separate line
            detail_indent = indent + ("   " if is_last else "│  ")
            self._print_task_details(child, detail_indent)
            
            if child.get('children'):
                next_indent = indent + ("   " if is_last else "│  ")
                self._print_children_recursive(child['children'], next_indent)

    def _would_create_circular_dependency(self, subtask_id, new_parent_id):
        """Check if moving subtask would create circular dependency"""
        if subtask_id == new_parent_id:
            return True
        
        # Check if new_parent_id is a descendant of subtask_id
        return self._is_descendant(subtask_id, new_parent_id)

    def _is_descendant(self, ancestor_id, potential_descendant_id):
        """Check if potential_descendant_id is a descendant of ancestor_id"""
        try:
            current_id = potential_descendant_id
            visited = set()
            
            while current_id and current_id not in visited:
                visited.add(current_id)
                
                task_records = self.tasks.search_records([('id', '=', current_id)])
                if not task_records:
                    break
                
                task = task_records[0]
                if hasattr(task, 'parent_id') and task.parent_id:
                    parent_id = task.parent_id.id if hasattr(task.parent_id, 'id') else task.parent_id
                    if parent_id == ancestor_id:
                        return True
                    current_id = parent_id
                else:
                    break
            
            return False
            
        except Exception:
            return False

    def _get_parent_chain(self, task_id):
        """Get chain of parent tasks"""
        parents = []
        current_id = task_id
        visited = set()
        
        try:
            while current_id and current_id not in visited:
                visited.add(current_id)
                
                task_records = self.tasks.search_records([('id', '=', current_id)])
                if not task_records:
                    break
                
                task = task_records[0]
                if hasattr(task, 'parent_id') and task.parent_id:
                    parent_id = task.parent_id.id if hasattr(task.parent_id, 'id') else task.parent_id
                    parent_records = self.tasks.search_records([('id', '=', parent_id)])
                    if parent_records:
                        parents.insert(0, self._task_to_dict(parent_records[0]))
                        current_id = parent_id
                    else:
                        break
                else:
                    break
                    
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Error getting parent chain: {e}")
        
        return parents

    def _get_children_recursive(self, task_id, max_depth, current_depth=0):
        """Get children recursively up to max_depth"""
        if current_depth >= max_depth:
            return []

        children = []

        try:
            if self.verbosity_level >= 3:
                print(f"🔍 Looking for children of task {task_id} at depth {current_depth}")

            # Use the working method: Direct parent_id search with integer task_id
            child_records = self.tasks.search_records([('parent_id', '=', int(task_id))])
            
            if self.verbosity_level >= 2:
                print(f"   Found {len(child_records)} children for task {task_id}")
            elif self.verbosity_level >= 3:
                print(f"   Method 1 (parent_id = {task_id}): Found {len(child_records)} children")
                if child_records:
                    for child in child_records:
                        print(f"     Child: {child.name} (ID: {child.id})")

            # Process found children
            for child in child_records:
                child_dict = self._task_to_dict(child)

                # Get grandchildren recursively
                if current_depth + 1 < max_depth:
                    child_dict['children'] = self._get_children_recursive(
                        child.id, max_depth, current_depth + 1
                    )

                children.append(child_dict)

        except Exception as e:
            if self.verbosity_level >= 2:
                print(f"⚠️ Error getting children for task {task_id}: {e}")

        if self.verbosity_level >= 3:
            print(f"   Final result: {len(children)} children for task {task_id}")

        return children

    def show_project_hierarchy(self, project_id, max_depth=3):
        """
        Show complete project hierarchy with all tasks and their subtasks.
        Single-fetch implementation that builds the tree in-memory to avoid N+1 RPCs.
        
        Args:
            project_id: ID of the project to show hierarchy for
            max_depth: Maximum depth to traverse for task subtasks (>=1)
            
        Returns:
            dict: Result with project hierarchy data
        """
        try:
            t_total_start = time.time()
            # Progress indicators based on verbosity level
            if self.verbosity_level == 0:
                print("🔍 Loading project hierarchy...", end="", flush=True)

            # Normalize inputs
            project_id_int = int(project_id)
            depth_limit = max(1, int(max_depth) if max_depth is not None else 3)
            
            # Get the project
            t_proj_start = time.time()
            project_records = self.projects.search_records([('id', '=', project_id_int)])
            t_proj_ms = int((time.time() - t_proj_start) * 1000)
            if not project_records:
                return {
                    'success': False,
                    'error': f'Project with ID {project_id} not found'
                }
            project = project_records[0]

            if self.verbosity_level >= 2:
                print(f"🔍 Searching for tasks in project {project_id_int} ('{getattr(project, 'name', 'Unknown Project')}')")
            elif self.verbosity_level == 0:
                print("\r🔍 Loading tasks...", end="", flush=True)

            # Get all tasks in this project once
            t_tasks_start = time.time()
            all_tasks = self.tasks.search_records([('project_id', '=', project_id_int)])
            t_tasks_ms = int((time.time() - t_tasks_start) * 1000)

            if self.verbosity_level >= 2:
                print(f"🔍 Found {len(all_tasks)} tasks in project {project_id_int}")
                print(f"⏱ Project fetch: {t_proj_ms} ms, Tasks fetch: {t_tasks_ms} ms")
            elif self.verbosity_level == 0:
                print(f"\r🔍 Processing {len(all_tasks)} tasks...", end="", flush=True)

            if not all_tasks:
                t_total_ms = int((time.time() - t_total_start) * 1000)
                # No tasks: return empty hierarchy but valid project info
                return {
                    'success': True,
                    'hierarchy': {
                        'project': self._project_to_dict(project),
                        'main_tasks': [],
                        'total_tasks': 0,
                        'main_task_count': 0,
                        'timings': {
                            'project_fetch_ms': t_proj_ms,
                            'tasks_fetch_ms': t_tasks_ms,
                            'index_build_ms': 0,
                            'assembly_ms': 0,
                            'total_ms': t_total_ms,
                        }
                    }
                }

            # If verbosity >= 1, switch to a rich single-batch read to avoid per-node RPCs
            rich_path = self.verbosity_level >= 1

            if not rich_path:
                # Original lightweight index build using record objects
                t_index_start = time.time()
                def get_id(value):
                    # Handles both many2one-like objects and raw ints
                    try:
                        if hasattr(value, 'id'):
                            return value.id
                        return int(value) if value else None
                    except Exception:
                        return None

                by_id = {}
                children_by_parent = {}

                for t in all_tasks:
                    by_id[t.id] = t
                    pid = get_id(getattr(t, 'parent_id', None))
                    children_by_parent.setdefault(pid, []).append(t)
                t_index_ms = int((time.time() - t_index_start) * 1000)

                # Determine main tasks (no parent)
                main_tasks = children_by_parent.get(None, []) + children_by_parent.get(False, [])
                # Deduplicate in case both None and False keys contain same tasks
                seen_main = set()
                main_tasks = [x for x in main_tasks if not (x.id in seen_main or seen_main.add(x.id))]

                if self.verbosity_level >= 2:
                    print(f"🔍 Found {len(main_tasks)} main tasks (without parents)")
                    print(f"⏱ Index build: {t_index_ms} ms")
                elif self.verbosity_level == 0:
                    print("\r🔍 Building hierarchy...", end="", flush=True)

                # Depth-limited recursive assembly using in-memory index
                def build_node(task, depth):
                    # Performance: build a lightweight node during assembly to avoid
                    # triggering relational dereferencing and extra RPCs. Full details
                    # (user, stage, etc.) can be resolved on-demand at print time.
                    node = {
                        'id': task.id,
                        'name': getattr(task, 'name', f'Task {task.id}'),
                    }
                    if depth >= depth_limit:
                        node['children'] = []
                        return node
                    child_nodes = []
                    for c in children_by_parent.get(task.id, []):
                        child_nodes.append(build_node(c, depth + 1))
                    node['children'] = child_nodes
                    return node

                t_assembly_start = time.time()
                project_hierarchy = {
                    'project': self._project_to_dict(project),
                    'main_tasks': [],
                    'total_tasks': len(all_tasks),
                    'main_task_count': len(main_tasks),
                }

                for i, main_task in enumerate(main_tasks):
                    if self.verbosity_level == 0:
                        print(f"\r🔍 Processing task {i+1}/{len(main_tasks)}...", end="", flush=True)
                    project_hierarchy['main_tasks'].append(build_node(main_task, 1))

                t_assembly_ms = int((time.time() - t_assembly_start) * 1000)
                t_total_ms = int((time.time() - t_total_start) * 1000)

                project_hierarchy['timings'] = {
                    'project_fetch_ms': t_proj_ms,
                    'tasks_fetch_ms': t_tasks_ms,
                    'index_build_ms': t_index_ms,
                    'assembly_ms': t_assembly_ms,
                    'total_ms': t_total_ms,
                }

                if self.verbosity_level >= 2:
                    print(f"⏱ Assembly: {t_assembly_ms} ms, Total: {t_total_ms} ms")

                if self.verbosity_level == 0:
                    print("\r" + " " * 50 + "\r", end="")  # Clear progress line

                return {
                    'success': True,
                    'hierarchy': project_hierarchy,
                }
            else:
                # Rich path: single bulk read of all needed fields, then pure in-memory assembly
                if self.verbosity_level >= 2:
                    print("🔍 Fetching rich task fields in bulk for verbose output...")
                t_index_start = time.time()

                # Gather task IDs from already fetched records
                all_ids = [t.id for t in all_tasks]
                # Fields to request in one go
                fields = [
                    'id', 'name', 'parent_id',
                    'user_id', 'stage_id', 'priority', 'state', 'kanban_state',
                    'date_deadline', 'create_date', 'write_date',
                    'depend_on_ids', 'blocking_task_ids', 'predecessor_ids', 'successor_ids',
                    'dependency_ids', 'blocked_by_ids', 'blocking_ids'
                ]
                try:
                    task_dicts = self.tasks.read(all_ids, fields)
                except Exception as e:
                    # Fallback: if read with (ids, fields) fails due to signature, try keyword arg
                    try:
                        task_dicts = self.tasks.read(all_ids, fields=fields)
                    except Exception as e2:
                        if self.verbose:
                            print(f"⚠️ Bulk read failed, falling back to lightweight mode: {e2}")
                        # Fall back to the lightweight path by re-running that branch
                        rich_path = False
                        # Recursively call but with same parameters; ensure no infinite loop
                        return self.show_project_hierarchy(project_id, max_depth)

                # Helper to normalize many2one to (id, name)
                def m2o_id(val):
                    try:
                        if val is None or val is False:
                            return None
                        if isinstance(val, (list, tuple)) and len(val) >= 1:
                            # Odoo typical: [id, name]
                            return val[0] if isinstance(val[0], int) else None
                        if isinstance(val, dict):
                            return val.get('id')
                        if isinstance(val, int):
                            return val
                    except Exception:
                        return None
                    return None

                # Index by ID and parent
                by_id = {d['id']: d for d in task_dicts}
                children_by_parent = {}
                for d in task_dicts:
                    pid = m2o_id(d.get('parent_id'))
                    children_by_parent.setdefault(pid, []).append(d)

                # Prefill task name cache for fast dependency name lookups
                try:
                    for tid, td in by_id.items():
                        name = td.get('name') or f'Task {tid}'
                        self._task_name_cache[tid] = name
                except Exception:
                    pass

                # Build dependency relations once per task
                def aggregate_rel(d):
                    def ids_from(key):
                        val = d.get(key)
                        if not val:
                            return []
                        # Many2many might be list of ints or list of [id, name]
                        out = []
                        try:
                            for item in val:
                                if isinstance(item, int):
                                    out.append(item)
                                elif isinstance(item, (list, tuple)) and item and isinstance(item[0], int):
                                    out.append(item[0])
                                elif isinstance(item, dict) and 'id' in item:
                                    out.append(item['id'])
                        except Exception:
                            pass
                        return out
                    blocked_by = set(ids_from('depend_on_ids') + ids_from('predecessor_ids') + ids_from('blocked_by_ids') + ids_from('dependency_ids'))
                    blocking = set(ids_from('blocking_task_ids') + ids_from('successor_ids') + ids_from('blocking_ids'))
                    # Remove self references just in case
                    tid = d.get('id')
                    blocked_by.discard(tid)
                    blocking.discard(tid)
                    return sorted(blocked_by), sorted(blocking)

                t_index_ms = int((time.time() - t_index_start) * 1000)

                # Determine main tasks (no parent)
                main_tasks = children_by_parent.get(None, []) + children_by_parent.get(False, [])
                # No need to deduplicate by object equality here; IDs are unique
                seen_main = set()
                main_tasks = [x for x in main_tasks if not (x['id'] in seen_main or seen_main.add(x['id']))]

                if self.verbosity_level >= 2:
                    print(f"🔍 Found {len(main_tasks)} main tasks (without parents)")
                    print(f"⏱ Index build: {t_index_ms} ms")

                # Node builder for dicts
                def build_node_dict(d, depth):
                    uid = m2o_id(d.get('user_id'))
                    sid = m2o_id(d.get('stage_id'))
                    blocked_by, blocking = aggregate_rel(d)
                    node = {
                        'id': d['id'],
                        'name': d.get('name') or f"Task {d['id']}",
                        'user_id': uid,
                        'user': None,  # name may be absent, printer tolerates None
                        'stage_id': sid,
                        'stage_name': None,
                        'priority': str(d.get('priority', '0')),
                        'state': d.get('state') or 'draft',
                        'kanban_state': d.get('kanban_state') or 'normal',
                        'deadline': d.get('date_deadline') or None,
                        'create_date': str(d.get('create_date') or ''),
                        'write_date': str(d.get('write_date') or ''),
                        'blocked_by': blocked_by,
                        'blocking': blocking,
                    }
                    # Try to capture many2one display names if present in value forms
                    try:
                        # If user_id is [id, name]
                        uval = d.get('user_id')
                        if isinstance(uval, (list, tuple)) and len(uval) >= 2:
                            node['user'] = uval[1]
                        # If stage_id is [id, name]
                        sval = d.get('stage_id')
                        if isinstance(sval, (list, tuple)) and len(sval) >= 2:
                            node['stage_name'] = sval[1]
                    except Exception:
                        pass

                    if depth >= depth_limit:
                        node['children'] = []
                        return node
                    node['children'] = [build_node_dict(c, depth + 1) for c in children_by_parent.get(d['id'], [])]
                    return node

                t_assembly_start = time.time()
                project_hierarchy = {
                    'project': self._project_to_dict(project),
                    'main_tasks': [],
                    'total_tasks': len(task_dicts),
                    'main_task_count': len(main_tasks),
                }

                for i, main_task in enumerate(main_tasks):
                    project_hierarchy['main_tasks'].append(build_node_dict(main_task, 1))

                t_assembly_ms = int((time.time() - t_assembly_start) * 1000)
                t_total_ms = int((time.time() - t_total_start) * 1000)

                project_hierarchy['timings'] = {
                    'project_fetch_ms': t_proj_ms,
                    'tasks_fetch_ms': t_tasks_ms,
                    'index_build_ms': t_index_ms,
                    'assembly_ms': t_assembly_ms,
                    'total_ms': t_total_ms,
                }

                if self.verbosity_level >= 2:
                    print(f"⏱ Assembly: {t_assembly_ms} ms, Total: {t_total_ms} ms")

                return {
                    'success': True,
                    'hierarchy': project_hierarchy,
                }

        except Exception as e:
            if not self.verbose:
                print("\r" + " " * 50 + "\r", end="")  # Clear progress line
            return {
                'success': False,
                'error': str(e),
            }

    def print_project_hierarchy(self, hierarchy):
        """Print project hierarchy as one unified tree with clickable links"""
        project = hierarchy['project']
        
        # Print project as root of the tree with clickable link and bold name
        project_url = self.get_project_url(project['id'])
        project_link = self.create_terminal_link(project_url, f"\033[1m{project['name']}\033[0m")
        print(f"📂 {project_link} (ID: {project['id']})")
        
        # Print project details based on verbosity level
        if self.verbosity_level >= 1:
            if project.get('description'):
                desc = project['description'][:100] + '...' if len(project['description']) > 100 else project['description']
                print(f"│  📝 {desc}")
            if project.get('partner_name'):
                print(f"│  🏢 Client: {project['partner_name']}")
        
        if project.get('user_name'):
            print(f"│  👤 Manager: {project['user_name']}")
        
        if self.verbosity_level >= 1 and project.get('stage_name'):
            print(f"│  📊 Stage: {project['stage_name']}")
        
        # Print summary - always show but adjust detail level
        if self.verbosity_level >= 1:
            print(f"│  📊 Summary: {hierarchy['total_tasks']} tasks ({hierarchy['main_task_count']} main, {hierarchy['total_tasks'] - hierarchy['main_task_count']} subtasks)")
        else:
            print(f"│  📊 {hierarchy['total_tasks']} tasks ({hierarchy['main_task_count']} main, {hierarchy['total_tasks'] - hierarchy['main_task_count']} subtasks)")

        # Print timing information if available
        timings = hierarchy.get('timings') or {}
        if timings:
            if self.verbosity_level >= 2:
                print("│  ⏱ Timings:")
                print(f"│    • Project fetch: {timings.get('project_fetch_ms', '?')} ms")
                print(f"│    • Tasks fetch:   {timings.get('tasks_fetch_ms', '?')} ms")
                print(f"│    • Index build:   {timings.get('index_build_ms', '?')} ms")
                print(f"│    • Assembly:      {timings.get('assembly_ms', '?')} ms")
                print(f"│    • Total:         {timings.get('total_ms', '?')} ms")
            else:
                total = timings.get('total_ms')
                if total is not None:
                    print(f"│  ⏱ Total time: {total} ms")

        # Print main tasks and their hierarchies as part of the project tree
        if hierarchy['main_tasks']:
            for i, main_task in enumerate(hierarchy['main_tasks']):
                is_last_main = i == len(hierarchy['main_tasks']) - 1
                main_prefix = "└──" if is_last_main else "├──"
                
                # Create clickable link for main task with bold name
                task_url = self.get_task_url(main_task['id'])
                task_link = self.create_terminal_link(task_url, f"\033[1m{main_task['name']}\033[0m")
                print(f"{main_prefix} {task_link} (ID: {main_task['id']})")
                
                # Print detailed task information on separate line
                indent = "   " if is_last_main else "│  "
                self._print_task_details(main_task, indent)
                
                # Print children
                if main_task.get('children'):
                    child_indent = "   " if is_last_main else "│  "
                    self._print_children_recursive(main_task['children'], child_indent)
        else:
            print(f"└── 📭 No tasks found in this project")

    def _project_to_dict(self, project):
        """Convert project record to dictionary"""
        project_dict = {
            'id': project.id,
            'name': getattr(project, 'name', f'Project {project.id}'),
        }
        
        # Add description
        if hasattr(project, 'description') and project.description:
            project_dict['description'] = project.description
        
        # Add partner info
        if hasattr(project, 'partner_id') and project.partner_id:
            try:
                project_dict['partner_name'] = project.partner_id.name if hasattr(project.partner_id, 'name') else 'Unknown'
                project_dict['partner_id'] = project.partner_id.id if hasattr(project.partner_id, 'id') else project.partner_id
            except:
                pass
        
        # Add user info
        if hasattr(project, 'user_id') and project.user_id:
            try:
                project_dict['user_name'] = project.user_id.name if hasattr(project.user_id, 'name') else 'Unknown'
                project_dict['user_id'] = project.user_id.id if hasattr(project.user_id, 'id') else project.user_id
            except:
                pass
        
        # Add stage info
        if hasattr(project, 'stage_id') and project.stage_id:
            try:
                project_dict['stage_name'] = project.stage_id.name if hasattr(project.stage_id, 'name') else 'Unknown'
                project_dict['stage_id'] = project.stage_id.id if hasattr(project.stage_id, 'id') else project.stage_id
            except:
                pass
        
        return project_dict

    def _task_to_dict(self, task):
        """Convert task record to dictionary"""
        task_dict = {
            'id': task.id,
            'name': getattr(task, 'name', f'Task {task.id}'),
        }
        
        # Add project info
        if hasattr(task, 'project_id') and task.project_id:
            try:
                task_dict['project_name'] = task.project_id.name if hasattr(task.project_id, 'name') else 'Unknown'
                task_dict['project_id'] = task.project_id.id if hasattr(task.project_id, 'id') else task.project_id
            except:
                pass
        
        # Add user info - suppress warnings unless debug level
        old_verbose = self.verbose
        if self.verbosity_level < 3:
            self.verbose = False
        
        user_id, user_name = self.extract_user_from_task(task)
        task_dict['user'] = user_name
        task_dict['user_id'] = user_id
        
        self.verbose = old_verbose
        
        # Add stage info - try multiple approaches
        task_dict['stage_name'] = 'No stage'
        task_dict['stage_id'] = None
        
        # Try stage_id field
        if hasattr(task, 'stage_id') and task.stage_id:
            try:
                stage_value = task.stage_id
                if hasattr(stage_value, 'name'):
                    task_dict['stage_name'] = stage_value.name
                    task_dict['stage_id'] = stage_value.id if hasattr(stage_value, 'id') else stage_value
                elif str(stage_value).startswith('functools.partial'):
                    # Handle partial objects
                    try:
                        actual_stage = stage_value()
                        if hasattr(actual_stage, 'name'):
                            task_dict['stage_name'] = actual_stage.name
                            task_dict['stage_id'] = actual_stage.id
                        else:
                            task_dict['stage_name'] = str(actual_stage)
                    except:
                        task_dict['stage_name'] = 'Unknown'
                else:
                    task_dict['stage_name'] = str(stage_value)
            except Exception as stage_error:
                if self.verbose:
                    print(f"⚠️ Error getting stage for task {task.id}: {stage_error}")
                task_dict['stage_name'] = 'Unknown'
        
        # Try alternative stage field names
        for stage_field in ['task_stage_id', 'project_task_stage_id', 'kanban_stage_id']:
            if task_dict['stage_name'] in ['No stage', 'Unknown'] and hasattr(task, stage_field):
                try:
                    stage_value = getattr(task, stage_field)
                    if stage_value and hasattr(stage_value, 'name'):
                        task_dict['stage_name'] = stage_value.name
                        task_dict['stage_id'] = stage_value.id if hasattr(stage_value, 'id') else stage_value
                        break
                except:
                    continue
        
        # Add priority
        priority_value = getattr(task, 'priority', '0')
        if str(priority_value).startswith('functools.partial'):
            try:
                task_dict['priority'] = str(priority_value())
            except:
                task_dict['priority'] = '0'
        else:
            task_dict['priority'] = str(priority_value)
        
        # Add state/status info
        if hasattr(task, 'state'):
            state_value = getattr(task, 'state', 'draft')
            if str(state_value).startswith('functools.partial'):
                try:
                    task_dict['state'] = str(state_value())
                except:
                    task_dict['state'] = 'draft'
            else:
                task_dict['state'] = str(state_value)
        else:
            task_dict['state'] = 'draft'
        
        # Add kanban state (if available)
        if hasattr(task, 'kanban_state'):
            kanban_value = getattr(task, 'kanban_state', 'normal')
            if str(kanban_value).startswith('functools.partial'):
                try:
                    task_dict['kanban_state'] = str(kanban_value())
                except:
                    task_dict['kanban_state'] = 'normal'
            else:
                task_dict['kanban_state'] = str(kanban_value)
        else:
            task_dict['kanban_state'] = 'normal'
        
        # Add date information
        if hasattr(task, 'date_deadline') and task.date_deadline:
            deadline_value = task.date_deadline
            if str(deadline_value).startswith('functools.partial'):
                try:
                    task_dict['deadline'] = str(deadline_value())
                except:
                    task_dict['deadline'] = None
            else:
                task_dict['deadline'] = str(deadline_value)
        
        # Add description
        if hasattr(task, 'description') and task.description:
            desc_value = task.description
            if str(desc_value).startswith('functools.partial'):
                try:
                    task_dict['description'] = str(desc_value())
                except:
                    task_dict['description'] = ''
            else:
                task_dict['description'] = str(desc_value)
        
        return task_dict

    def _print_task_details(self, task, indent):
        """Print detailed task information with proper indentation based on verbosity level"""
        
        # Get blocking info lazily: skip at default verbosity (0) to speed up printing
        # For verbosity >=1, prefer precomputed relations on the task node; fall back to RPC if missing
        blocking_info = {'blocked_by': [], 'blocking': []}
        if self.verbosity_level >= 1:
            if 'blocked_by' in task or 'blocking' in task:
                blocking_info['blocked_by'] = task.get('blocked_by', []) or []
                blocking_info['blocking'] = task.get('blocking', []) or []
            else:
                blocking_info = self._get_blocking_info(task['id'])
        
        # Level 0 (default): Essential info with icons on one line
        if self.verbosity_level == 0:
            status_parts = []
            
            # Blocking relationships - ALWAYS show these FIRST as they're critical
            if blocking_info['blocked_by']:
                blocked_by_links = []
                for task_id in blocking_info['blocked_by']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocked_by_links.append(f"{task_id} ({task_link})")
                status_parts.append(f"⛔ {', '.join(blocked_by_links)}")
            
            if blocking_info['blocking']:
                blocking_links = []
                for task_id in blocking_info['blocking']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocking_links.append(f"{task_id} ({task_link})")
                status_parts.append(f"🚫 {', '.join(blocking_links)}")
            
            # Essential info with icons only (no labels)
            if task.get('user') and task['user'] != 'Unassigned':
                status_parts.append(f"👤 {task['user']}")
            
            if task.get('stage_name') and task['stage_name'] not in ['Unknown', 'No stage']:
                status_parts.append(f"📊 {task['stage_name']}")
            
            priority_value = task.get('priority', '0')
            if priority_value and priority_value != '0':
                priority_stars = self._convert_priority_to_stars(priority_value)
                status_parts.append(priority_stars)  # Just stars, no label
            
            # State with icon only
            state_value = task.get('state', 'draft')
            if state_value and state_value not in ['draft', 'normal']:
                if state_value.startswith('01_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                elif state_value.startswith('04_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                else:
                    state_display = state_value.replace('_', ' ').title()
                status_parts.append(f"🏷️ {state_display}")
            
            # Deadline with icon only
            if task.get('deadline'):
                status_parts.append(f"📅 {task['deadline']}")
            
            # Print all status info on one line
            if status_parts:
                print(f"{indent}{' • '.join(status_parts)}")
        
        # Level 1 (-v): Show more task details with labels
        elif self.verbosity_level == 1:
            # Blocking relationships - show first as they're critical
            if blocking_info['blocked_by']:
                blocked_by_links = []
                for task_id in blocking_info['blocked_by']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocked_by_links.append(f"{task_id} ({task_link})")
                print(f"{indent}⛔ Blocked by: {', '.join(blocked_by_links)}")
            
            if blocking_info['blocking']:
                blocking_links = []
                for task_id in blocking_info['blocking']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocking_links.append(f"{task_id} ({task_link})")
                print(f"{indent}🚫 Blocking: {', '.join(blocking_links)}")
            
            # Task details with labels
            if task.get('user') and task['user'] != 'Unassigned':
                print(f"{indent}👤 Assigned: {task['user']}")
            
            if task.get('stage_name') and task['stage_name'] not in ['Unknown', 'No stage']:
                print(f"{indent}📊 Stage: {task['stage_name']}")
            
            priority_value = task.get('priority', '0')
            if priority_value and priority_value != '0':
                priority_stars = self._convert_priority_to_stars(priority_value)
                print(f"{indent}🔥 Priority: {priority_stars}")
            
            if task.get('deadline'):
                print(f"{indent}📅 Deadline: {task['deadline']}")
            
            state_value = task.get('state', 'draft')
            if state_value and state_value not in ['draft']:
                if state_value.startswith('01_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                elif state_value.startswith('04_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                else:
                    state_display = state_value.replace('_', ' ').title()
                print(f"{indent}🏷️ State: {state_display}")
            
            if task.get('write_date'):
                print(f"{indent}📅 Modified: {task['write_date']}")
        
        # Level 2 (-vv): Add IDs and more details
        elif self.verbosity_level == 2:
            # Blocking relationships first
            if blocking_info['blocked_by']:
                blocked_by_links = []
                for task_id in blocking_info['blocked_by']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocked_by_links.append(f"{task_id} ({task_link})")
                print(f"{indent}⛔ Blocked by: {', '.join(blocked_by_links)}")
            
            if blocking_info['blocking']:
                blocking_links = []
                for task_id in blocking_info['blocking']:
                    task_name = self._get_task_name(task_id)
                    task_url = self.get_task_url(task_id)
                    task_link = self.create_terminal_link(task_url, task_name)
                    blocking_links.append(f"{task_id} ({task_link})")
                print(f"{indent}🚫 Blocking: {', '.join(blocking_links)}")
            
            # Task details with IDs
            if task.get('user') and task['user'] != 'Unassigned':
                user_id_info = f" (ID: {task['user_id']})" if task.get('user_id') else ""
                print(f"{indent}👤 Assigned: {task['user']}{user_id_info}")
            
            if task.get('stage_name') and task['stage_name'] not in ['Unknown', 'No stage']:
                stage_id_info = f" (ID: {task['stage_id']})" if task.get('stage_id') else ""
                print(f"{indent}📊 Stage: {task['stage_name']}{stage_id_info}")
            
            priority_value = task.get('priority', '0')
            if priority_value and priority_value != '0':
                priority_stars = self._convert_priority_to_stars(priority_value)
                print(f"{indent}🔥 Priority: {priority_stars} (Raw: {priority_value})")
            
            if task.get('deadline'):
                print(f"{indent}📅 Deadline: {task['deadline']}")
            
            state_value = task.get('state', 'draft')
            if state_value:
                if state_value.startswith('01_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                elif state_value.startswith('04_'):
                    state_display = state_value[3:].replace('_', ' ').title()
                else:
                    state_display = state_value.replace('_', ' ').title()
                print(f"{indent}🏷️ State: {state_display} (Raw: {state_value})")
            
            if task.get('write_date'):
                print(f"{indent}📅 Modified: {task['write_date']}")
            if task.get('create_date'):
                print(f"{indent}📅 Created: {task['create_date']}")
        
        # Level 3 (-vvv/debug): Show all debug info
        elif self.verbosity_level >= 3:
            # Blocking relationships first (even in debug mode)
            if blocking_info['blocked_by']:
                print(f"{indent}⛔ Blocked by: {', '.join(map(str, blocking_info['blocked_by']))}")
            if blocking_info['blocking']:
                print(f"{indent}🚫 Blocking: {', '.join(map(str, blocking_info['blocking']))}")
            
            # Show all available task data
            print(f"{indent}🔍 DEBUG - All task data:")
            for key, value in sorted(task.items()):
                if key not in ['id', 'name', 'children']:
                    print(f"{indent}   {key}: {repr(value)}")
            
            # Show blocking info debug
            print(f"{indent}🔍 DEBUG - Blocking info:")
            print(f"{indent}   blocked_by: {blocking_info['blocked_by']}")
            print(f"{indent}   blocking: {blocking_info['blocking']}")

    def _convert_priority_to_stars(self, priority_value):
        """Convert Odoo priority to 3-star system"""
        try:
            priority = int(priority_value)
            if priority == 0:
                return "☆☆☆ (Normal)"
            elif priority == 1:
                return "★☆☆ (High)"
            elif priority == 2:
                return "★★☆ (Urgent)"
            elif priority >= 3:
                return "★★★ (Critical)"
            else:
                return f"☆☆☆ ({priority})"
        except (ValueError, TypeError):
            return f"☆☆☆ ({priority_value})"

    def _get_task_name(self, task_id):
        """Get task name by ID for blocking relationships with simple cache"""
        try:
            # Use cache if available
            cache = getattr(self, '_task_name_cache', None)
            if isinstance(cache, dict):
                cached = cache.get(task_id)
                if cached:
                    return cached
            
            task_records = self.tasks.search_records([('id', '=', task_id)])
            if task_records:
                name = getattr(task_records[0], 'name', f'Task {task_id}')
                # Store in cache
                try:
                    if isinstance(cache, dict):
                        cache[task_id] = name
                except Exception:
                    pass
                return name
            else:
                return f'Task {task_id}'
        except Exception:
            return f'Task {task_id}'

    def _get_blocking_info(self, task_id):
        """Get blocking and blocked-by relationships for a task"""
        blocking_info = {
            'blocking': [],
            'blocked_by': []
        }
        
        try:
            # Get the task record to check for dependency fields
            task_records = self.tasks.search_records([('id', '=', task_id)])
            if not task_records:
                return blocking_info
            
            task = task_records[0]
            
            # Check for common dependency field names
            dependency_fields = [
                'depend_on_ids',  # Tasks this task depends on (blocked by)
                'blocking_task_ids',  # Tasks this task is blocking
                'predecessor_ids',  # Predecessors (blocked by)
                'successor_ids',  # Successors (blocking)
                'dependency_ids',  # General dependencies
                'blocked_by_ids',  # Explicitly blocked by
                'blocking_ids'  # Explicitly blocking
            ]
            
            for field_name in dependency_fields:
                if hasattr(task, field_name):
                    try:
                        field_value = getattr(task, field_name)
                        if field_value:
                            # Extract IDs from the field
                            ids = []
                            if hasattr(field_value, '__iter__'):
                                for item in field_value:
                                    if hasattr(item, 'id'):
                                        ids.append(item.id)
                                    elif isinstance(item, int):
                                        ids.append(item)
                            elif hasattr(field_value, 'id'):
                                ids.append(field_value.id)
                            elif isinstance(field_value, int):
                                ids.append(field_value)
                            
                            # Categorize based on field name
                            if 'depend' in field_name or 'predecessor' in field_name or 'blocked_by' in field_name:
                                blocking_info['blocked_by'].extend(ids)
                            elif 'blocking' in field_name or 'successor' in field_name:
                                blocking_info['blocking'].extend(ids)
                            
                            if self.verbosity_level >= 3 and ids:
                                print(f"   Found {field_name}: {ids}")
                                
                    except Exception as field_error:
                        if self.verbosity_level >= 3:
                            print(f"   Error accessing {field_name}: {field_error}")
            
            # Remove duplicates
            blocking_info['blocking'] = list(set(blocking_info['blocking']))
            blocking_info['blocked_by'] = list(set(blocking_info['blocked_by']))
            
        except Exception as e:
            if self.verbosity_level >= 3:  # Only show on debug level
                print(f"⚠️ Error getting blocking info for task {task_id}: {e}")
        
        return blocking_info
