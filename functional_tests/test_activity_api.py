#!/usr/bin/env python3
# test_activity_api.py
"""
Direct test of the activity trends data function
Version: 0.261.474
Implemented in: 0.230.011
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

from datetime import datetime, timedelta

def test_activity_trends_direct():
    """Test the activity trends function directly"""
    
    print("🔍 Testing Activity Trends function directly...")
    
    try:
        # Import the function we need to test
        from application.single_app.route_backend_control_center import get_activity_trends_data
        
        # Set up test date range (last 7 days)
        end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        start_date = (end_date - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        print(f"Testing date range: {start_date} to {end_date}")
        
        # Call the function
        result = get_activity_trends_data(start_date, end_date)
        
        print(f"✅ Function executed successfully!")
        print(f"Results: {result}")
        
        # Check if we got login data
        login_data = result.get('logins', {})
        total_logins = sum(login_data.values())
        print(f"📊 Total logins found: {total_logins}")
        
        if total_logins > 0:
            print("✅ Login data found!")
            for date_key, count in login_data.items():
                if count > 0:
                    print(f"  {date_key}: {count} logins")
        else:
            print("❌ No login data found")
            
    except Exception as e:
        print(f"❌ Error testing function: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_activity_trends_direct()