# example_python_dashboard.py
"""Example Python-backed custom page with a Jinja template and backend API."""

import os
from datetime import datetime, timezone

from flask import jsonify, render_template_string, url_for

from custom_page_extension import CustomPageExtension


EXAMPLE_REQUEST_COUNT = 0


class ExamplePythonDashboard(CustomPageExtension):
    """Render a Jinja-backed example page and serve a small backend API."""

    metadata = {
        "slug": "example-python-dashboard",
        "title": "Python API Dashboard Example",
        "description": "A trusted Python-backed page that renders Jinja and calls a backend API.",
        "entry_type": "python",
        "nav_label": "Python API",
        "nav_icon": "bi-terminal",
        "nav_order": 30,
        "show_in_nav": True,
        "enabled": True,
        "html_file": "example-python-dashboard.html",
        "css_files": ["example-python-dashboard.css"],
        "js_files": ["example-python-dashboard.js"],
    }

    def render(self, context):
        """Render the Jinja template from the deployed custom_pages/html folder."""
        template_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "html", "example-python-dashboard.html")
        )
        with open(template_path, "r", encoding="utf-8") as template_handle:
            template_source = template_handle.read()

        user = context.get("user", {}) if isinstance(context, dict) else {}
        user_name = user.get("name") or user.get("preferred_username") or "Signed-in user"
        slug = self.metadata["slug"]

        return render_template_string(
            template_source,
            page_title=self.metadata["title"],
            user_name=user_name,
            api_status_url=url_for("custom_page_api", slug=slug, operation="status"),
            stylesheet_url=url_for(
                "custom_page_asset",
                slug=slug,
                folder="css",
                filename="example-python-dashboard.css",
            ),
            script_url=url_for(
                "custom_page_asset",
                slug=slug,
                folder="js",
                filename="example-python-dashboard.js",
            ),
        )

    def handle_api(self, operation, context):
        """Handle API calls dispatched through /api/custom/example-python-dashboard/<operation>."""
        global EXAMPLE_REQUEST_COUNT

        if operation != "status":
            raise NotImplementedError("Unsupported example operation.")

        user = context.get("user", {}) if isinstance(context, dict) else {}
        EXAMPLE_REQUEST_COUNT += 1

        return jsonify({
            "healthy": True,
            "operation": operation,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "user_name": user.get("name") or user.get("preferred_username") or "Signed-in user",
            "request_count": EXAMPLE_REQUEST_COUNT,
        })