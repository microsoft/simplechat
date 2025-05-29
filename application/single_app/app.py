# app.py

from config import *

from functions_authentication import *
from functions_content import *
from functions_documents import *
from functions_search import *
from functions_settings import *

from route_frontend_authentication import *
from route_frontend_profile import *
from route_frontend_admin_settings import *
from route_frontend_workspace import *
from route_frontend_chats import *
from route_frontend_conversations import *
from route_frontend_groups import *
from route_frontend_group_workspaces import *
from route_frontend_safety import *
from route_frontend_feedback import *
from route_frontend_public_workspaces import *

from route_backend_chats import *
from route_backend_conversations import *
from route_backend_documents import *
from route_backend_groups import *
from route_backend_users import *
from route_backend_group_documents import *
from route_backend_models import *
from route_backend_safety import *
from route_backend_feedback import *
from route_backend_settings import *
from route_backend_prompts import *
from route_backend_group_prompts import *
from route_backend_public_workspaces import *

# =================== Helper Functions ===================
@app.before_first_request
def before_first_request():
    settings = get_settings()
    initialize_clients(settings)
    ensure_custom_logo_file_exists(app, settings)

@app.context_processor
def inject_settings():
    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)
    # No change needed if you already return app_settings=public_settings
    return dict(app_settings=public_settings)

@app.template_filter('to_datetime')
def to_datetime_filter(value):
    return datetime.fromisoformat(value)

@app.template_filter('format_datetime')
def format_datetime_filter(value):
    return value.strftime('%Y-%m-%d %H:%M')

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# Register a custom Jinja filter for Markdown
def markdown_filter(text):
    if not text:
        text = ""

    # Convert Markdown to HTML
    html = markdown2.markdown(text)

    # Add target="_blank" to all <a> links
    html = re.sub(r'(<a\s+href=["\'](https?://.*?)["\'])', r'\1 target="_blank" rel="noopener noreferrer"', html)

    return Markup(html)

# Add the filter to the Jinja environment
app.jinja_env.filters['markdown'] = markdown_filter

# =================== Default Routes =====================
@app.route('/')
def index():
    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)

    # Ensure landing_page_text is always a valid string
    landing_text = settings.get("landing_page_text", "Click the button below to start chatting with the AI assistant. You agree to our [acceptable user policy by using this service](acceptable_use_policy.html).")

    # Convert Markdown to HTML safely
    landing_html = markdown_filter(landing_text)

    return render_template('index.html', app_settings=public_settings, landing_html=landing_html)

@app.route('/robots933456.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/acceptable_use_policy.html')
def acceptable_use_policy():
    return render_template('acceptable_use_policy.html')


# =================== Front End Routes ===================
# ------------------- User Authentication Routes ---------
register_route_frontend_authentication(app)

# ------------------- User Profile Routes ----------------
register_route_frontend_profile(app)

# ------------------- Admin Settings Routes --------------
register_route_frontend_admin_settings(app)

# ------------------- Chats Routes -----------------------
register_route_frontend_chats(app)

# ------------------- Conversations Routes ---------------
register_route_frontend_conversations(app)

# ------------------- Documents Routes -------------------
register_route_frontend_workspace(app)

# ------------------- Groups Routes ----------------------
register_route_frontend_groups(app)

# ------------------- Group Documents Routes -------------
register_route_frontend_group_workspaces(app)

# ------------------- Safety Routes ----------------------
register_route_frontend_safety(app)

# ------------------- Feedback Routes -------------------
register_route_frontend_feedback(app)

# ------------------- Public Workspaces Routes ----------
register_route_frontend_public_workspaces(app)

# =================== Back End Routes ====================
# ------------------- API Chat Routes --------------------
register_route_backend_chats(app)

# ------------------- API Conversation Routes ------------
register_route_backend_conversations(app)

# ------------------- API Documents Routes ---------------
register_route_backend_documents(app)

# ------------------- API Groups Routes ------------------
register_route_backend_groups(app)

# ------------------- API User Routes --------------------
register_route_backend_users(app)

# ------------------- API Group Documents Routes ---------
register_route_backend_group_documents(app)

# ------------------- API Model Routes -------------------
register_route_backend_models(app)

# ------------------- API Safety Logs Routes -------------
register_route_backend_safety(app)

# ------------------- API Feedback Routes ---------------
register_route_backend_feedback(app)

# ------------------- API Settings Routes ---------------
register_route_backend_settings(app)

# ------------------- API Prompts Routes ----------------
register_route_backend_prompts(app)

# ------------------- API Group Prompts Routes ----------
register_route_backend_group_prompts(app)

# ------------------- API Public Workspaces Routes ------
register_route_backend_public_workspaces(app)

if __name__ == '__main__':
    settings = get_settings()
    initialize_clients(settings)
    app.run(debug=False)