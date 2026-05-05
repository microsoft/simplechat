# functions_logging.py

# functions_logging.py

from config import *
import functions_settings

def add_file_task_to_file_processing_log(document_id, user_id, content):
    settings = functions_settings.get_settings()
    enable_file_processing_log = settings.get('enable_file_processing_logs', True)

    if enable_file_processing_log:
        try:
            id_value = str(uuid.uuid4())
            log_item = {
                "id": id_value,
                "document_id": document_id,
                "user_id": user_id,
                "log": content,
                "timestamp": datetime.utcnow().isoformat()
            }
            cosmos_file_processing_container.create_item(log_item)
        except Exception as e:
            raise e
        
