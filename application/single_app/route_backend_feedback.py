# route_backend_feedback.py

import csv
import io

from flask import make_response

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security   


ALLOWED_FEEDBACK_TYPES = {"Positive", "Negative", "Neutral"}
ALLOWED_PAGE_SIZES = {10, 20, 50, 100}
FEEDBACK_TYPE_NORMALIZATION = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
}


def _authorize_feedback_conversation(user_id, conversation_id):
    """Load the target conversation and ensure the caller owns it."""
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if conversation_item.get("user_id") != user_id:
        raise PermissionError("Forbidden")

    return conversation_item


def _get_feedback_session_user_id():
    if "user" not in session:
        return None

    return session["user"].get("oid") or session["user"].get("sub")


def _normalize_feedback_page_size(page_size):
    return page_size if page_size in ALLOWED_PAGE_SIZES else 10


def _normalize_feedback_type(feedback_type):
    if not isinstance(feedback_type, str):
        return None

    return FEEDBACK_TYPE_NORMALIZATION.get(feedback_type.strip().lower())


def _parse_feedback_filters():
    filter_type = _normalize_feedback_type(request.args.get('type', None, type=str))

    filter_ack_str = request.args.get('ack', None, type=str)
    filter_ack_bool = None
    if filter_ack_str == 'true':
        filter_ack_bool = True
    elif filter_ack_str == 'false':
        filter_ack_bool = False

    return filter_type, filter_ack_bool


def _serialize_feedback_item(item):
    normalized_feedback_type = _normalize_feedback_type(item.get("feedbackType"))

    return {
        "id": item.get("id"),
        "userId": item.get("userId"),
        "prompt": item.get("prompt"),
        "aiResponse": item.get("aiResponse"),
        "feedbackType": normalized_feedback_type or item.get("feedbackType"),
        "reason": item.get("reason"),
        "timestamp": item.get("timestamp"),
        "adminReview": item.get("adminReview", {}),
    }


def _query_feedback_items(user_id=None, filter_type=None, filter_ack_bool=None):
    query = "SELECT * FROM c"
    where_clauses = []
    parameters = []

    if user_id:
        where_clauses.append("c.userId = @userId")
        parameters.append({"name": "@userId", "value": user_id})

    if filter_ack_bool is not None:
        where_clauses.append("c.adminReview.acknowledged = @ack")
        parameters.append({"name": "@ack", "value": filter_ack_bool})

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += " ORDER BY c.timestamp DESC"

    items = list(cosmos_feedback_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ))

    serialized_items = [_serialize_feedback_item(item) for item in items]

    if filter_type:
        serialized_items = [
            item for item in serialized_items
            if item.get("feedbackType") == filter_type
        ]

    return serialized_items


def _paginate_feedback_items(items, page, page_size):
    if page < 1:
        page = 1

    page_size = _normalize_feedback_page_size(page_size)
    offset = (page - 1) * page_size
    return items[offset: offset + page_size], page, page_size


def _build_feedback_stats(items):
    stats = {
        "total_count": len(items),
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "acknowledged_count": 0,
        "unacknowledged_count": 0,
        "recent_30_day_count": 0,
        "latest_timestamp": items[0].get('timestamp') if items else None,
    }

    recent_cutoff = datetime.utcnow() - timedelta(days=30)

    for item in items:
        feedback_type = _normalize_feedback_type(item.get('feedbackType')) or item.get('feedbackType')
        if feedback_type == 'Positive':
            stats['positive_count'] += 1
        elif feedback_type == 'Negative':
            stats['negative_count'] += 1
        elif feedback_type == 'Neutral':
            stats['neutral_count'] += 1

        acknowledged = bool((item.get('adminReview') or {}).get('acknowledged'))
        if acknowledged:
            stats['acknowledged_count'] += 1
        else:
            stats['unacknowledged_count'] += 1

        timestamp = item.get('timestamp')
        if timestamp:
            try:
                parsed_timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed_timestamp.replace(tzinfo=None) >= recent_cutoff:
                    stats['recent_30_day_count'] += 1
            except ValueError:
                pass

    return stats


def _build_feedback_export_response(items, filename_prefix, include_user_id=False):
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'Timestamp',
        'Feedback Type',
        'Reason',
        'Prompt',
        'AI Response',
        'Acknowledged',
        'Admin Notes',
        'Admin Response',
        'Admin Action',
    ]
    if include_user_id:
        headers.insert(1, 'User ID')

    writer.writerow(headers)

    for item in items:
        admin_review = item.get('adminReview') or {}
        row = [
            item.get('timestamp') or '',
            item.get('feedbackType') or '',
            item.get('reason') or '',
            item.get('prompt') or '',
            item.get('aiResponse') or '',
            'Yes' if admin_review.get('acknowledged') else 'No',
            admin_review.get('analysisNotes') or '',
            admin_review.get('responseToUser') or '',
            admin_review.get('actionTaken') or '',
        ]
        if include_user_id:
            row.insert(1, item.get('userId') or '')
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename={filename_prefix}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    )
    return response

def register_route_backend_feedback(app):

    @app.route("/feedback/submit", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_submit():
        """
        Endpoint to store user feedback:
          POST /feedback/submit
          JSON body: { messageId, conversationId, feedbackType, reason }
        """
        data = request.get_json() or {}
        messageId = data.get("messageId")          # This is the ID of the specific AI message
        conversationId = data.get("conversationId") # This is the ID of the conversation
        feedbackType = _normalize_feedback_type(data.get("feedbackType"))
        reason = data.get("reason", "")
        user_id = None
        if "user" in session:
            user_id = session["user"].get("oid") or session["user"].get("sub")

        if not messageId or not conversationId or not feedbackType:
            return jsonify({"error": "Missing required fields"}), 400

        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            _authorize_feedback_conversation(user_id, conversationId)
        except LookupError:
            return jsonify({"error": "Conversation not found"}), 404
        except PermissionError:
            return jsonify({"error": "Forbidden", "message": "You do not have access to this conversation"}), 403

        ai_message_text = None
        user_prompt_text = None
        all_messages = [] # Initialize an empty list for messages

        try:
            # --- CORRECTED PART ---
            # Query the cosmos_messages_container for all messages in this conversation
            # Order by timestamp to find the preceding message correctly
            query = "SELECT * FROM c WHERE c.conversation_id = @conversationId ORDER BY c.timestamp ASC"
            parameters = [{"name": "@conversationId", "value": conversationId}]

            # Execute the query against the cosmos_messages_container, specifying the partition key
            message_items = list(cosmos_messages_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=conversationId # Use the partition key for efficiency
                # enable_cross_partition_query=False # Not needed if partition_key is specified
            ))
            # --- END CORRECTED PART ---

            if not message_items:
                return jsonify({"error": "Assistant message not found"}), 404

            all_messages = message_items # Assign the query results to all_messages

            # Find the AI message corresponding to the messageId
            ai_msg_index = -1
            for i, msg in enumerate(all_messages):
                # **** IMPORTANT ASSUMPTION ****
                # Assuming the 'messageId' sent from the frontend corresponds to the 'id' field
                # of the message document in cosmos_messages_container.
                # If your message documents use a different field like 'message_id', change 'msg.get("id")' below.
                if msg.get("role") == "assistant" and msg.get("id") == messageId:
                    ai_message_text = msg.get("content")
                    ai_msg_index = i
                    break

            if ai_msg_index == -1:
                return jsonify({"error": "Assistant message not found"}), 404

            # Find the user message immediately preceding the AI message
            if ai_msg_index > 0:
                 # Iterate backwards from the message before the AI's message
                 for i in range(ai_msg_index - 1, -1, -1):
                      if all_messages[i].get("role") == "user":
                          user_prompt_text = all_messages[i].get("content")
                          break # Found the closest preceding user prompt

            # Fallback if direct preceding message not found (or AI message was first)
            if not user_prompt_text and all_messages:
                # Find the *last* user message in the conversation up to the AI message index
                # (or the very last if AI message wasn't found)
                search_limit = ai_msg_index if ai_msg_index != -1 else len(all_messages)
                for i in range(search_limit -1, -1, -1):
                     if all_messages[i].get("role") == "user":
                          user_prompt_text = all_messages[i].get("content")
                          break
        except Exception as e:
            print(f"Error querying messages for conversation {conversationId}: {e}")
            return jsonify({"error": "Failed to load feedback target"}), 500

        # Set default text if messages weren't found
        if ai_message_text is None:
            ai_message_text = "[AI response text not found in cosmos_messages_container]"

        if not user_prompt_text:
            user_prompt_text = "[User prompt not found in cosmos_messages_container]"

        # --- Rest of the feedback saving logic remains the same ---
        feedback_id = str(uuid.uuid4())
        item = {
            "id": feedback_id,
            "partitionKey": feedback_id, # Explicitly set partition key if it's the ID
            "userId": user_id,
            "conversationId": conversationId, # Good practice to store the conversation ID too
            "messageId": messageId, # Store the ID of the message being reviewed
            "prompt": user_prompt_text,
            "aiResponse": ai_message_text,
            "feedbackType": feedbackType,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "adminReview": {
                "acknowledged": False,
                "analyzedBy": None,
                "analysisNotes": None,
                "responseToUser": None,
                "actionTaken": None,
                "reviewTimestamp": None
            }
        }

        try:
            cosmos_feedback_container.upsert_item(item)
            return jsonify({"success": True, "feedbackId": feedback_id})
        except Exception as e:
            print(f"Error saving feedback item {feedback_id}: {e}")
            return jsonify({"error": "Failed to save feedback"}), 500
    

    @app.route("/feedback/review", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_get():
        """
        Return feedback for admin review with pagination and filtering.
        """
        try:
            page = request.args.get('page', 1, type=int)
            page_size = request.args.get('page_size', 10, type=int)
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            paginated_items, page, page_size = _paginate_feedback_items(items, page, page_size)
            total_count = len(items)

            return jsonify({
                "feedback": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": math.ceil(total_count / page_size)
            })

        except Exception as e:
             print(f"Error fetching feedback for review: {e}")
             # Log the full exception traceback if possible
             import traceback
             traceback.print_exc()
             return jsonify({"error": f"Failed to retrieve feedback: {str(e)}"}), 500

    @app.route("/feedback/review/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_stats():
        """Return aggregate feedback review statistics for the admin page."""
        try:
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return jsonify(_build_feedback_stats(items))
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve feedback stats: {str(e)}"}), 500

    @app.route("/feedback/review/export", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_export():
        """Export feedback review rows as CSV for the active filter set."""
        try:
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return _build_feedback_export_response(items, 'feedback_review_export', include_user_id=True)
        except Exception as e:
            return jsonify({"error": f"Failed to export feedback: {str(e)}"}), 500

    @app.route("/feedback/review/<feedbackId>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_get_single(feedbackId):
        """
        Fetch a single feedback item by its ID.
        Needed for the edit modal after switching to pagination.
        """
        try:
            # Assuming feedbackId is the partition key as well
            feedback_doc = cosmos_feedback_container.read_item(
                item=feedbackId, partition_key=feedbackId
            )

            result = {
                "id": feedback_doc["id"],
                "userId": feedback_doc.get("userId"),
                "prompt": feedback_doc.get("prompt"),
                "aiResponse": feedback_doc.get("aiResponse"),
                "feedbackType": _normalize_feedback_type(feedback_doc.get("feedbackType")) or feedback_doc.get("feedbackType"),
                "reason": feedback_doc.get("reason"),
                "timestamp": feedback_doc.get("timestamp"),
                "adminReview": feedback_doc.get("adminReview", {})
            }
            return jsonify(result)

        except CosmosResourceNotFoundError: # Import this if not already done
             return jsonify({"error": "Feedback item not found"}), 404
        except Exception as e:
             print(f"Error fetching single feedback item {feedbackId}: {e}")
             import traceback
             traceback.print_exc()
             return jsonify({"error": f"Failed to retrieve feedback item: {str(e)}"}), 500
        
    @app.route("/feedback/review/<feedbackId>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_update(feedbackId):
        """
        Patch admin fields: acknowledged, analysisNotes, responseToUser, actionTaken
        """
        data = request.get_json()

        try:
             # Assume feedbackId is the partition key
            feedback_doc = cosmos_feedback_container.read_item(
                item=feedbackId, partition_key=feedbackId
            )
        except CosmosResourceNotFoundError:
            return jsonify({"error": "Feedback not found"}), 404
        except Exception as e:
            print(f"Error reading feedback item {feedbackId} for update: {e}")
            return jsonify({"error": "Failed to read feedback item"}), 500


        admin_review_data = feedback_doc.get("adminReview", {}) # Get current or default dict

        # Update fields based on request data
        admin_review_data["acknowledged"] = data.get("acknowledged", admin_review_data.get("acknowledged", False))
        admin_review_data["analysisNotes"] = data.get("analysisNotes", admin_review_data.get("analysisNotes"))
        admin_review_data["responseToUser"] = data.get("responseToUser", admin_review_data.get("responseToUser"))
        admin_review_data["actionTaken"] = data.get("actionTaken", admin_review_data.get("actionTaken"))
        admin_review_data["reviewTimestamp"] = datetime.utcnow().isoformat()
        # Optionally add analyzedBy from session user
        # if 'user' in session:
        #     admin_review_data["analyzedBy"] = session['user'].get('oid') or session['user'].get('sub')

        feedback_doc["adminReview"] = admin_review_data # Assign updated dict back

        try:
             cosmos_feedback_container.upsert_item(feedback_doc)
             return jsonify({"success": True})
        except Exception as e:
             print(f"Error updating feedback item {feedbackId}: {e}")
             return jsonify({"error": "Failed to save changes"}), 500


    @app.route("/feedback/retest/<feedbackId>", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_retest(feedbackId):
        """
        Admin retests the prompt. We basically re-run the prompt
        against the current AI chain to see if it's improved.
        """
        data = request.get_json()
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "Missing prompt"}), 400

        try:
            retestResponse = run_prompt_against_gpt(prompt)
            return jsonify({"retestResponse": retestResponse})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        
    @app.route("/feedback/my", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my():
        """
        Returns the current user's feedback items with server-side pagination and filtering.
        Query Parameters:
            page (int): Page number (default: 1).
            page_size (int): Items per page (default: 10).
            type (str): Filter by feedbackType (Positive, Negative, Neutral).
            ack (str): Filter by acknowledged status ('true', 'false').
        """
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            paginated_items, page, page_size = _paginate_feedback_items(items, page, page_size)

            return jsonify({
                "feedback": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": len(items)
            }), 200

        except Exception as e:
            print(f"Error in feedback_my: {str(e)}")
            return jsonify({"error": f"An error occurred while fetching your feedback: {str(e)}"}), 500

    @app.route("/feedback/my/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my_stats():
        """Return aggregate feedback statistics for the current user."""
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return jsonify(_build_feedback_stats(items))
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve feedback stats: {str(e)}"}), 500

    @app.route("/feedback/my/export", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my_export():
        """Export the current user's feedback rows as CSV for the active filter set."""
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_type, filter_ack_bool = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return _build_feedback_export_response(items, 'my_feedback_export', include_user_id=False)
        except Exception as e:
            return jsonify({"error": f"Failed to export feedback: {str(e)}"}), 500


def run_prompt_against_gpt(prompt):
    # To do -  Replace with the real logic of your chat pipeline
    # Example: Access your LLM client and run the prompt
    # from your_llm_module import llm_client
    # response = llm_client.invoke(prompt)
    # return response.content
    print(f"Retesting prompt (stub): {prompt}")
    return f"[Retested with current model config] Mock AI response for: '{prompt}'"