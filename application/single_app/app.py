# app.py
import builtins
import logging
import pickle
import json

from semantic_kernel import Kernel
from semantic_kernel_loader import initialize_semantic_kernel

from azure.monitor.opentelemetry import configure_azure_monitor

from config import *

from functions_authentication import *
from functions_content import *
from functions_documents import *
from functions_search import *
from functions_settings import *
from functions_appinsights import *

from route_frontend_authentication import *
from route_frontend_profile import *
from route_frontend_admin_settings import *
from route_frontend_workspace import *
from route_frontend_chats import *
from route_frontend_conversations import *
from route_frontend_groups import *
from route_frontend_group_workspaces import *
from route_frontend_public_workspaces import *
from route_frontend_safety import *
from route_frontend_feedback import *

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
from route_backend_plugins import bpap as admin_plugins_bp, bpdp as dynamic_plugins_bp
from route_backend_agents import bpa as admin_agents_bp
from route_backend_public_workspaces import *
from route_backend_public_documents import *
from route_backend_public_prompts import *
from route_enhanced_citations import register_enhanced_citations_routes
from plugin_validation_endpoint import plugin_validation_bp
from route_openapi import register_openapi_routes
from route_migration import bp_migration
from route_plugin_logging import bpl as plugin_logging_bp

app = Flask(__name__)

app.config['EXECUTOR_TYPE'] = EXECUTOR_TYPE
app.config['EXECUTOR_MAX_WORKERS'] = EXECUTOR_MAX_WORKERS
executor = Executor()
executor.init_app(app)
app.config['SESSION_TYPE'] = SESSION_TYPE
app.config['VERSION'] = VERSION
app.config['SECRET_KEY'] = SECRET_KEY

Session(app)

app.register_blueprint(admin_plugins_bp)
app.register_blueprint(dynamic_plugins_bp)
app.register_blueprint(admin_agents_bp)
app.register_blueprint(plugin_validation_bp)
app.register_blueprint(bp_migration)
app.register_blueprint(plugin_logging_bp)

# Register OpenAPI routes
register_openapi_routes(app)

# Register Enhanced Citations routes
register_enhanced_citations_routes(app)

from flask import g
from flask_session import Session
from redis import Redis
from functions_settings import get_settings
from functions_authentication import get_current_user_id
from functions_global_agents import ensure_default_global_agent_exists

from route_external_health import *

configure_azure_monitor()


# =================== Helper Functions ===================
@app.before_first_request
def before_first_request():
    print("Initializing application...")
    settings = get_settings()
    print(f"DEBUG:Application settings: {settings}")
    initialize_clients(settings)
    ensure_custom_logo_file_exists(app, settings)
    # Enable Application Insights logging globally if configured
    print("Setting up Application Insights logging...")
    setup_appinsights_logging(settings)
    logging.basicConfig(level=logging.DEBUG)
    print("Application initialized.")
    ensure_default_global_agent_exists()


    # Setup session handling
    if settings.get('enable_redis_cache'):
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()

        if redis_url:
            app.config['SESSION_TYPE'] = 'redis'
            if redis_auth_type == 'managed_identity':
                print("Redis enabled using Managed Identity")
                credential = DefaultAzureCredential()
                redis_hostname = redis_url.split('.')[0]  # Extract the first part of the hostname
                token = credential.get_token(f"https://{redis_hostname}.cacheinfra.windows.net:10225/appid")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=token.token,
                    ssl=True
                )
            else:
                # Default to key-based auth
                redis_key = settings.get('redis_key', '').strip()
                print("Redis enabled using Access Key")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=redis_key,
                    ssl=True
                )
        else:
            print("Redis enabled but URL missing; falling back to filesystem.")
            app.config['SESSION_TYPE'] = 'filesystem'
    else:
        app.config['SESSION_TYPE'] = 'filesystem'

    # Initialize Semantic Kernel and plugins
    enable_semantic_kernel = settings.get('enable_semantic_kernel', False)
    per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
    if enable_semantic_kernel and not per_user_semantic_kernel:
        print("Semantic Kernel is enabled. Initializing...")
        initialize_semantic_kernel()

    Session(app)

    # Setup session handling
    if settings.get('enable_redis_cache'):
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()

        if redis_url:
            app.config['SESSION_TYPE'] = 'redis'

            if redis_auth_type == 'managed_identity':
                print("Redis enabled using Managed Identity")
                credential = DefaultAzureCredential()
                redis_hostname = redis_url.split('.')[0]  # Extract the first part of the hostname
                token = credential.get_token(f"https://{redis_hostname}.cacheinfra.windows.net:10225/appid")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=token.token,
                    ssl=True
                )
            else:
                # Default to key-based auth
                redis_key = settings.get('redis_key', '').strip()
                print("Redis enabled using Access Key")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=redis_key,
                    ssl=True
                )
        else:
            print("Redis enabled but URL missing; falling back to filesystem.")
            app.config['SESSION_TYPE'] = 'filesystem'
    else:
        app.config['SESSION_TYPE'] = 'filesystem'

    Session(app)

    # Setup session handling
    if settings.get('enable_redis_cache'):
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()

        if redis_url:
            app.config['SESSION_TYPE'] = 'redis'

            if redis_auth_type == 'managed_identity':
                print("Redis enabled using Managed Identity")
                credential = DefaultAzureCredential()
                redis_hostname = redis_url.split('.')[0]  # Extract the first part of the hostname
                token = credential.get_token(f"https://{redis_hostname}.cacheinfra.windows.net:10225/appid")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=token.token,
                    ssl=True
                )
            else:
                # Default to key-based auth
                redis_key = settings.get('redis_key', '').strip()
                print("Redis enabled using Access Key")
                app.config['SESSION_REDIS'] = Redis(
                    host=redis_url,
                    port=6380,
                    db=0,
                    password=redis_key,
                    ssl=True
                )
        else:
            print("Redis enabled but URL missing; falling back to filesystem.")
            app.config['SESSION_TYPE'] = 'filesystem'
    else:
        app.config['SESSION_TYPE'] = 'filesystem'

    Session(app)

@app.context_processor
def inject_settings():
    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)
    # Inject per-user settings if logged in
    user_settings = {}
    try:
        user_id = get_current_user_id()
        if user_id:
            from functions_settings import get_user_settings
            user_settings = get_user_settings(user_id) or {}
    except Exception as e:
        user_settings = {}
    return dict(app_settings=public_settings, user_settings=user_settings)

@app.template_filter('to_datetime')
def to_datetime_filter(value):
    return datetime.fromisoformat(value)

@app.template_filter('format_datetime')
def format_datetime_filter(value):
    return value.strftime('%Y-%m-%d %H:%M')

# =================== SK Hot Reload Handler ===================
@app.before_request
def reload_kernel_if_needed():
    if getattr(builtins, "kernel_reload_needed", False):
        debug_print(f"[SK Loader] Hot reload: re-initializing Semantic Kernel and agents due to settings change.")
        """Commneted out because hot reload is not fully supported yet.
        log_event(
            "[SK Loader] Hot reload: re-initializing Semantic Kernel and agents due to settings change.",
            level=logging.INFO
        )
        initialize_semantic_kernel()
        """
        setattr(builtins, "kernel_reload_needed", False)

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

@app.route('/static/js/<path:filename>')
def serve_js_modules(filename):
    """Serve JavaScript modules with correct MIME type."""
    from flask import send_from_directory, Response
    if filename.endswith('.mjs'):
        # Serve .mjs files with correct MIME type for ES modules
        response = send_from_directory('static/js', filename)
        response.headers['Content-Type'] = 'application/javascript'
        return response
    else:
        return send_from_directory('static/js', filename)

@app.route('/acceptable_use_policy.html')
def acceptable_use_policy():
    return render_template('acceptable_use_policy.html')

@app.route('/api/semantic-kernel/plugins')
def list_semantic_kernel_plugins():
    """Test endpoint: List loaded Semantic Kernel plugins and their functions."""
    global kernel
    if not kernel:
        return {"error": "Kernel not initialized"}, 500
    plugins = {}
    for plugin_name, plugin in kernel.plugins.items():
        plugins[plugin_name] = [func.name for func in plugin.functions.values()]
    return {"plugins": plugins}


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
register_route_frontend_public_workspaces(app)

# ------------------- Safety Routes ----------------------
register_route_frontend_safety(app)

# ------------------- Feedback Routes -------------------
register_route_frontend_feedback(app)

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

# ------------------- API Public Workspaces Routes -------
register_route_backend_public_workspaces(app)

# ------------------- API Public Documents Routes --------
register_route_backend_public_documents(app)

# ------------------- API Public Prompts Routes ----------
register_route_backend_public_prompts(app)

# ------------------- Extenral Health Routes ----------
register_route_external_health(app)

if __name__ == '__main__':
    settings = get_settings()
    initialize_clients(settings)

    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"

    if debug_mode:
        # Local development with HTTPS
        app.run(host="0.0.0.0", port=5000, debug=True, ssl_context='adhoc')
    else:
        # Production
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False)

