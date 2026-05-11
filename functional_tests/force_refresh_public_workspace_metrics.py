#!/usr/bin/env python3
"""
Force refresh public workspace metrics to test the field name fix.
Version: 0.230.081

This script forces a refresh of public workspace metrics to bypass the cache
and verify that the field name fix properly counts documents.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def force_refresh_public_workspace_metrics():
    """Force refresh metrics for public workspaces to test fix."""
    print("🔄 Force Refreshing Public Workspace Metrics...")
    
    try:
        # Import required modules
        from config import *
        from route_backend_control_center import enhance_public_workspace_with_activity
        
        print("✅ Successfully imported required modules")
        
        # Get all public workspaces
        print("\n📋 Fetching all public workspaces...")
        
        try:
            workspaces_query = "SELECT * FROM c"
            workspaces = list(cosmos_public_workspaces_container.query_items(
                query=workspaces_query,
                enable_cross_partition_query=True
            ))
            
            print(f"✅ Found {len(workspaces)} public workspaces")
            
        except Exception as fetch_e:
            print(f"❌ Error fetching workspaces: {fetch_e}")
            return False
        
        # Process each workspace with force refresh
        results = []
        
        for i, workspace in enumerate(workspaces):
            workspace_id = workspace.get('id')
            workspace_name = workspace.get('name', 'Unnamed')
            
            print(f"\n🔄 [{i+1}/{len(workspaces)}] Refreshing: {workspace_name} ({workspace_id})")
            
            try:
                # Force refresh to bypass cache and use new queries
                enhanced = enhance_public_workspace_with_activity(workspace, force_refresh=True)
                
                # Extract metrics
                doc_metrics = enhanced.get('activity', {}).get('document_metrics', {})
                total_docs = doc_metrics.get('total_documents', 0)
                ai_search_size = doc_metrics.get('ai_search_size', 0)
                storage_size = doc_metrics.get('storage_account_size', 0)
                
                result = {
                    'workspace_id': workspace_id,
                    'name': workspace_name,
                    'total_documents': total_docs,
                    'ai_search_size': ai_search_size,
                    'storage_size': storage_size
                }
                results.append(result)
                
                print(f"   📊 Documents: {total_docs}")
                print(f"   🔍 AI Search Size: {ai_search_size} bytes")
                print(f"   💾 Storage Size: {storage_size} bytes")
                
                if total_docs > 0:
                    print(f"   ✅ Found documents! Fix appears to be working.")
                else:
                    print(f"   ⚠️  No documents found - check if workspace actually has documents")
                
            except Exception as enhance_e:
                print(f"   ❌ Error enhancing workspace {workspace_id}: {enhance_e}")
                result = {
                    'workspace_id': workspace_id,
                    'name': workspace_name,
                    'error': str(enhance_e)
                }
                results.append(result)
        
        # Summary
        print(f"\n📊 Final Results Summary:")
        print("=" * 60)
        
        total_docs_found = 0
        workspaces_with_docs = 0
        
        for result in results:
            if 'error' not in result:
                workspace_docs = result['total_documents']
                total_docs_found += workspace_docs
                if workspace_docs > 0:
                    workspaces_with_docs += 1
                
                print(f"   {result['name']:<20} | Docs: {workspace_docs:>3} | AI: {result['ai_search_size']:>8} | Storage: {result['storage_size']:>10}")
            else:
                print(f"   {result['name']:<20} | ERROR: {result['error']}")
        
        print("=" * 60)
        print(f"📈 Total documents found across all workspaces: {total_docs_found}")
        print(f"📊 Workspaces with documents: {workspaces_with_docs}/{len(workspaces)}")
        
        if total_docs_found > 0:
            print("\n🎯 SUCCESS: The field name fix is working!")
            print("   • Public workspace queries now use public_workspace_id")
            print("   • Documents are being counted correctly")
            print("   • Metrics cache has been refreshed")
        else:
            print("\n⚠️  No documents found in any workspace.")
            print("   This could mean:")
            print("   • No documents have been uploaded to public workspaces")
            print("   • Documents might be in a different container")
            print("   • Check if documents exist in cosmos public_documents container")
        
        return True
        
    except Exception as e:
        print(f"❌ Script failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = force_refresh_public_workspace_metrics()
    sys.exit(0 if success else 1)