# test_chat_model_description_tooltip.py
#!/usr/bin/env python3
"""
Functional test for chat model description tooltip.
Version: 0.236.023
Implemented in: 0.236.023

This test ensures multi-endpoint model options include a title attribute
that can display the model description on hover.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_chat_model_description_tooltip():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    template_path = os.path.join(repo_root, 'application', 'single_app', 'templates', 'chats.html')
    content = read_file_text(template_path)

    assert 'title="{{ model.description or model.display_name }}"' in content, "Model tooltip title missing in chat model select."

    print("✅ Chat model description tooltip verified.")


if __name__ == "__main__":
    test_chat_model_description_tooltip()
