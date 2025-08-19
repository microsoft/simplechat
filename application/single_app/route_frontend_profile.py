# route_frontend_profile.py

from config import *
from functions_authentication import *

def register_route_frontend_profile(app):
    @app.route('/profile')
    @login_required
    def profile():
        user = session.get('user')
        return render_template('profile.html', user=user)
    
    @app.route('/api/profile/image/refresh', methods=['POST'])
    @login_required
    @user_required
    def refresh_profile_image():
        """
        Fetches the user's profile image from Microsoft Graph and saves it to user settings.
        """
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "Unable to identify user"}), 401
            
            # Fetch profile image from Microsoft Graph
            profile_image_data = get_user_profile_image()
            
            if profile_image_data:
                # Save the profile image to user settings
                success = update_user_settings(user_id, {'profileImage': profile_image_data})
                
                if success:
                    return jsonify({
                        "success": True,
                        "message": "Profile image updated successfully",
                        "profileImage": profile_image_data
                    }), 200
                else:
                    return jsonify({"error": "Failed to save profile image"}), 500
            else:
                # No profile image found, remove any existing one
                success = update_user_settings(user_id, {'profileImage': None})
                
                if success:
                    return jsonify({
                        "success": True,
                        "message": "No profile image found",
                        "profileImage": None
                    }), 200
                else:
                    return jsonify({"error": "Failed to update profile image settings"}), 500
                    
        except Exception as e:
            print(f"Error refreshing profile image for user {user_id}: {e}")
            return jsonify({"error": "Internal server error"}), 500