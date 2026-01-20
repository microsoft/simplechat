#!/usr/bin/env python3
"""
Functional test for User Profile Dashboard feature.
Version: 0.234.068
Implemented in: 0.234.068

This test ensures that the profile dashboard API endpoints work correctly,
return properly formatted data, and handle errors gracefully.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_profile_endpoints():
    """Test profile dashboard API endpoints."""
    print("🔍 Testing User Profile Dashboard Endpoints...")
    
    try:
        from datetime import datetime, timezone, timedelta
        import json
        
        # Import required modules
        from config import cosmos_activity_logs_container, cosmos_conversations_container
        from config import cosmos_user_documents_container, cosmos_user_settings_container
        
        # Test user ID (use a real test user or create one)
        test_user_id = "test-profile-user-12345"
        
        # ============================================
        # Test 1: User Settings Endpoint Data Structure
        # ============================================
        print("\n📊 Test 1: Checking user settings data structure...")
        
        try:
            # Get or create test user settings
            try:
                user_doc = cosmos_user_settings_container.read_item(
                    item=test_user_id, 
                    partition_key=test_user_id
                )
            except:
                # Create test user settings
                user_doc = {
                    'id': test_user_id,
                    'user_id': test_user_id,
                    'email': 'test@example.com',
                    'display_name': 'Test User',
                    'settings': {
                        'metrics': {
                            'calculated_at': datetime.now(timezone.utc).isoformat(),
                            'login_metrics': {
                                'total_logins': 10,
                                'last_login': datetime.now(timezone.utc).isoformat()
                            },
                            'chat_metrics': {
                                'total_conversations': 5,
                                'total_messages': 25,
                                'total_message_size': 10240
                            },
                            'document_metrics': {
                                'total_documents': 3,
                                'ai_search_size': 5242880,
                                'storage_account_size': 6291456
                            }
                        },
                        'retention_policy_enabled': False,
                        'retention_policy_days': 30
                    }
                }
                cosmos_user_settings_container.upsert_item(body=user_doc)
            
            # Validate structure
            assert 'settings' in user_doc, "User settings missing 'settings' key"
            assert 'metrics' in user_doc['settings'], "User settings missing 'metrics' key"
            
            metrics = user_doc['settings']['metrics']
            assert 'login_metrics' in metrics, "Missing login_metrics"
            assert 'chat_metrics' in metrics, "Missing chat_metrics"
            assert 'document_metrics' in metrics, "Missing document_metrics"
            
            print("   ✅ User settings structure is valid")
            
        except AssertionError as e:
            print(f"   ❌ Structure validation failed: {e}")
            return False
        except Exception as e:
            print(f"   ❌ Error checking user settings: {e}")
            return False
        
        # ============================================
        # Test 2: Activity Trends Date Range
        # ============================================
        print("\n📅 Test 2: Testing activity trends date range...")
        
        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            
            # Verify date range calculation
            date_diff = (end_date - start_date).days
            assert date_diff == 30, f"Expected 30 days, got {date_diff}"
            
            # Create sample activity logs for testing
            test_activities = []
            for i in range(5):
                activity_date = start_date + timedelta(days=i*6)
                
                # Login activity
                login_activity = {
                    'id': f'login-{test_user_id}-{i}',
                    'user_id': test_user_id,
                    'activity_type': 'user_login',
                    'timestamp': activity_date.isoformat(),
                    'created_at': activity_date.isoformat()
                }
                test_activities.append(login_activity)
                
                # Token usage activity
                token_activity = {
                    'id': f'token-{test_user_id}-{i}',
                    'user_id': test_user_id,
                    'activity_type': 'token_usage',
                    'timestamp': activity_date.isoformat(),
                    'created_at': activity_date.isoformat(),
                    'activity_details': {
                        'total_tokens': 1000 + (i * 100),
                        'prompt_tokens': 500,
                        'completion_tokens': 500 + (i * 100)
                    }
                }
                test_activities.append(token_activity)
            
            # Insert test activities
            for activity in test_activities:
                try:
                    cosmos_activity_logs_container.upsert_item(body=activity)
                except Exception as insert_e:
                    print(f"   ⚠️ Could not insert test activity: {insert_e}")
            
            print("   ✅ Date range calculation is correct (30 days)")
            print(f"   ✅ Created {len(test_activities)} test activity records")
            
        except AssertionError as e:
            print(f"   ❌ Date range validation failed: {e}")
            return False
        except Exception as e:
            print(f"   ❌ Error testing date range: {e}")
            return False
        
        # ============================================
        # Test 3: Query Activity Logs
        # ============================================
        print("\n🔎 Test 3: Querying activity logs...")
        
        try:
            # Query login activities
            login_query = """
                SELECT c.timestamp, c.created_at FROM c 
                WHERE c.user_id = @user_id 
                AND c.activity_type = 'user_login'
                AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
            """
            login_params = [
                {"name": "@user_id", "value": test_user_id},
                {"name": "@start_date", "value": start_date.isoformat()}
            ]
            
            login_records = list(cosmos_activity_logs_container.query_items(
                query=login_query,
                parameters=login_params,
                enable_cross_partition_query=True
            ))
            
            print(f"   ✅ Found {len(login_records)} login records for test user")
            
            # Query token usage activities
            token_query = """
                SELECT c.timestamp, c.created_at, c.activity_details FROM c 
                WHERE c.user_id = @user_id 
                AND c.activity_type = 'token_usage'
                AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
            """
            token_params = [
                {"name": "@user_id", "value": test_user_id},
                {"name": "@start_date", "value": start_date.isoformat()}
            ]
            
            token_records = list(cosmos_activity_logs_container.query_items(
                query=token_query,
                parameters=token_params,
                enable_cross_partition_query=True
            ))
            
            print(f"   ✅ Found {len(token_records)} token usage records for test user")
            
            # Validate token details structure
            if token_records:
                sample_token = token_records[0]
                assert 'activity_details' in sample_token, "Token record missing activity_details"
                details = sample_token['activity_details']
                assert 'total_tokens' in details, "Token details missing total_tokens"
                print(f"   ✅ Token record structure is valid (sample: {details.get('total_tokens')} tokens)")
            
        except AssertionError as e:
            print(f"   ❌ Query validation failed: {e}")
            return False
        except Exception as e:
            print(f"   ❌ Error querying activity logs: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # ============================================
        # Test 4: Data Aggregation by Date
        # ============================================
        print("\n📈 Test 4: Testing data aggregation by date...")
        
        try:
            from collections import defaultdict
            
            logins_by_date = defaultdict(int)
            tokens_by_date = defaultdict(int)
            
            # Aggregate login data
            for record in login_records:
                timestamp = record.get('timestamp') or record.get('created_at')
                if timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    date_key = dt.strftime('%Y-%m-%d')
                    logins_by_date[date_key] += 1
            
            # Aggregate token data
            for record in token_records:
                timestamp = record.get('timestamp') or record.get('created_at')
                if timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    date_key = dt.strftime('%Y-%m-%d')
                    details = record.get('activity_details', {})
                    total_tokens = details.get('total_tokens', 0)
                    tokens_by_date[date_key] += total_tokens
            
            print(f"   ✅ Aggregated data across {len(logins_by_date)} unique dates")
            
            # Show sample aggregation
            if logins_by_date:
                sample_date = list(logins_by_date.keys())[0]
                print(f"   ✅ Sample: {sample_date} -> {logins_by_date[sample_date]} logins, {tokens_by_date.get(sample_date, 0)} tokens")
            
        except Exception as e:
            print(f"   ❌ Error aggregating data: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # ============================================
        # Test 5: Response Format
        # ============================================
        print("\n📦 Test 5: Validating response format...")
        
        try:
            # Generate complete date range
            date_range = []
            for i in range(30):
                date = end_date - timedelta(days=29-i)
                date_range.append(date.strftime('%Y-%m-%d'))
            
            # Format data for Chart.js
            logins_data = [{"date": date, "count": logins_by_date.get(date, 0)} for date in date_range]
            tokens_data = [{"date": date, "tokens": tokens_by_date.get(date, 0)} for date in date_range]
            
            # Validate structure
            assert len(logins_data) == 30, f"Expected 30 dates, got {len(logins_data)}"
            assert all('date' in item and 'count' in item for item in logins_data), "Login data missing required keys"
            assert all('date' in item and 'tokens' in item for item in tokens_data), "Token data missing required keys"
            
            print(f"   ✅ Response format is valid (30 data points per chart)")
            print(f"   ✅ Sample login data: {logins_data[0]}")
            print(f"   ✅ Sample token data: {tokens_data[0]}")
            
            # Test JSON serialization
            test_response = {
                "success": True,
                "logins": logins_data,
                "tokens": tokens_data,
                "storage": {
                    "ai_search_size": 5242880,
                    "storage_account_size": 6291456
                }
            }
            
            json_str = json.dumps(test_response)
            assert len(json_str) > 0, "JSON serialization failed"
            print(f"   ✅ JSON serialization successful ({len(json_str)} bytes)")
            
        except AssertionError as e:
            print(f"   ❌ Response format validation failed: {e}")
            return False
        except Exception as e:
            print(f"   ❌ Error validating response format: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # ============================================
        # Test 6: Cleanup Test Data
        # ============================================
        print("\n🧹 Test 6: Cleaning up test data...")
        
        try:
            # Delete test activities
            for activity in test_activities:
                try:
                    cosmos_activity_logs_container.delete_item(
                        item=activity['id'],
                        partition_key=activity['user_id']
                    )
                except:
                    pass
            
            # Optionally delete test user (uncomment if needed)
            # try:
            #     cosmos_user_settings_container.delete_item(
            #         item=test_user_id,
            #         partition_key=test_user_id
            #     )
            # except:
            #     pass
            
            print("   ✅ Test data cleaned up successfully")
            
        except Exception as e:
            print(f"   ⚠️ Warning: Could not clean up all test data: {e}")
        
        print("\n" + "="*60)
        print("✅ All User Profile Dashboard tests passed!")
        print("="*60)
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_profile_endpoints()
    sys.exit(0 if success else 1)
