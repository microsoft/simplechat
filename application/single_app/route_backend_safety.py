# route_backend_safety.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_safety(app):
    @app.route('/api/safety/logs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_content_safety")
    def get_safety_logs():
        """
        Returns safety logs with server-side pagination and filtering.
        Query Parameters:
            page (int): The page number to retrieve (default: 1).
            page_size (int): The number of items per page (default: 10).
            status (str): Filter logs by status.
            action (str): Filter logs by action.
        """
        try:
            # --- Pagination Parameters ---
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            if page < 1: page = 1
            if page_size < 1: page_size = 10
            # Azure Cosmos DB Python SDK uses 0-based index for OFFSET
            offset = (page - 1) * page_size

            # --- Filtering Parameters ---
            filter_status = request.args.get('status', None)
            filter_action = request.args.get('action', None)

            # --- Build Query ---
            query_conditions = []
            parameters = []

            if filter_status:
                query_conditions.append("c.status = @status")
                parameters.append({"name": "@status", "value": filter_status})

            if filter_action:
                query_conditions.append("c.action = @action")
                parameters.append({"name": "@action", "value": filter_action})

            # Base query
            query = "SELECT * FROM c"
            count_query = "SELECT VALUE COUNT(1) FROM c" # Query to count total matching items

            if query_conditions:
                query += " WHERE " + " AND ".join(query_conditions)
                count_query += " WHERE " + " AND ".join(query_conditions)

            # Order by creation date (descending) for consistent results
            query += " ORDER BY c.created_at DESC" # Or last_updated DESC

            # Add pagination (OFFSET/LIMIT) - NOTE: Cosmos DB SQL doesn't directly support OFFSET/LIMIT in the same way as SQL Server.
            # We need to fetch filtered results and paginate in Python OR use continuation tokens for very large datasets.
            # For simplicity with moderate data sizes, we'll fetch filtered items and slice.
            # If performance becomes an issue with huge logs, switch to continuation tokens.

            # --- Execute Queries ---
            # 1. Get total count of items matching filters
            count_results = list(cosmos_safety_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            total_count = count_results[0] if count_results else 0

            # 2. Get the paginated items matching filters
            # Fetch items matching the filter, ordered
            all_matching_items = list(cosmos_safety_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))

            # Apply pagination slicing in Python
            paginated_items = all_matching_items[offset : offset + page_size]

            return jsonify({
                "logs": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": total_count
            }), 200

        except Exception as e:
            print(f"Error in get_safety_logs: {str(e)}") # Log the error server-side
            # Consider using Flask's logging mechanism
            return jsonify({"error": f"An error occurred while fetching safety logs: {str(e)}"}), 500

    @app.route('/api/safety/logs/<string:log_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_content_safety")
    def update_safety_log(log_id):
        """
        Updates status, action, and notes on a safety log.
        Also sets timestamps (created_at if missing, and last_updated).
        """
        data = request.json
        status = data.get("status")
        action = data.get("action")
        notes = data.get("notes")
        
        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            if status:
                item["status"] = status
            if action:
                item["action"] = action

            if notes is not None:
                item["notes"] = notes

            item["last_updated"] = datetime.utcnow().isoformat()

            cosmos_safety_container.upsert_item(item)

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosHttpResponseError as e:
            return jsonify({"error": str(e)}), 404
        
    @app.route('/api/safety/logs/my', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def get_my_safety_logs():
        """
        Returns the current user's safety logs with server-side pagination and filtering.
        Query Parameters:
            page (int): The page number to retrieve (default: 1).
            page_size (int): The number of items per page (default: 10).
            status (str): Filter logs by status.
            action (str): Filter logs by action.
        """
        user_id = None
        if "user" in session:
            user_id = session["user"].get("oid") or session["user"].get("sub")
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            # --- Pagination Parameters ---
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            if page < 1: page = 1
            if page_size < 1: page_size = 10
            offset = (page - 1) * page_size

            # --- Filtering Parameters ---
            filter_status = request.args.get('status', None)
            filter_action = request.args.get('action', None)

            # --- Build Query ---
            query_conditions = ["c.user_id = @user_id"] # Start with user_id condition
            parameters = [{"name": "@user_id", "value": user_id}]

            if filter_status:
                query_conditions.append("c.status = @status")
                parameters.append({"name": "@status", "value": filter_status})

            if filter_action:
                query_conditions.append("c.action = @action")
                parameters.append({"name": "@action", "value": filter_action})

            # Base query
            where_clause = " WHERE " + " AND ".join(query_conditions)
            query = f"SELECT * FROM c {where_clause} ORDER BY c.created_at DESC" # Or last_updated DESC
            count_query = f"SELECT VALUE COUNT(1) FROM c {where_clause}" # Query to count total matching items

            # --- Execute Queries ---
            # 1. Get total count of items matching filters for this user
            count_results = list(cosmos_safety_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True # May be needed depending on partition key
            ))
            total_count = count_results[0] if count_results else 0

            # 2. Get the paginated items matching filters for this user
            # Fetch all matching items first, then slice (suitable for moderate user data volume)
            all_matching_items = list(cosmos_safety_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))

            # Apply pagination slicing in Python
            paginated_items = all_matching_items[offset : offset + page_size]

            return jsonify({
                "logs": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": total_count
            }), 200

        except Exception as e:
            print(f"Error in get_my_safety_logs: {str(e)}")
            return jsonify({"error": f"An error occurred while fetching your safety logs: {str(e)}"}), 500

    @app.route('/api/safety/logs/my/<string:log_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def update_my_safety_log(log_id):
        """
        Allows the user to update only their own safety log, 
        specifically the user_notes field (separate from admin notes).
        """
        data = request.json
        user_notes = data.get("user_notes")

        user_id = None
        if "user" in session:
            user_id = session["user"].get("oid") or session["user"].get("sub")
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)

            if item.get("user_id") != user_id:
                return jsonify({"error": "You do not have permission to update this record."}), 403

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            if user_notes is not None:
                item["user_notes"] = user_notes

            item["last_updated"] = datetime.utcnow().isoformat()
            cosmos_safety_container.upsert_item(item)

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosHttpResponseError as e:
            return jsonify({"error": str(e)}), 404