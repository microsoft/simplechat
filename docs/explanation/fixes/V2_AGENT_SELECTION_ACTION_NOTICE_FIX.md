# V2 agent selection action notice fix

**Fixed in version: 0.261.395** (`application/single_app/config.py`)

Selecting an agent displayed a generic action-checking and sign-in notice in the
composer even when there was no action problem. The recovery component used agent
selection alone as the condition for that fallback message.

The composer now stays clear when there is no recovery issue. Actual recovery
errors remain visible, and unavailable actions still require the existing
recheck, cancel, or explicit continue decision. Action checks and service
authentication behavior have not changed.

Regression coverage is in `functional_tests/test_v2_agent_action_notice.py`
and `ui_tests/test_chat_action_recovery.py`.
