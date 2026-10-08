# test_orchestration_file_sign_in_publication.py
"""A file a signed-in run renders is published under that run's sign-in, or says why not.

Version: 0.261.303
Implemented in: 0.261.303

A Word report rendered from an action's results failed with only "This file could not be
created." Publishing the file re-checked its sources through a fresh rendering service built on
the execution's worker thread. That service had no signed-in session, so every web search, web
page, deep research, agent or action source in the file's lineage was refused. Publication is
now checked by the rendering service that ran the attempt. A file that still cannot be checked
without a sign-in, such as one rendered in the background, fails as ``output_sign_in_required``
with a reason and no file-only retry, and its step reports ``file_sign_in_required``. Real
production modules run with external Azure I/O doubled.
"""

import pytest

from functions_orchestration_artifacts import OUTPUT_SIGN_IN_REQUIRED, signed_in_session_required
from functions_orchestration_output_store import (
    OUTPUT_FAILURE_MESSAGES,
    OUTPUT_UNAVAILABLE_MESSAGES,
    OutputError,
    OutputUnavailableError,
)
from functions_orchestration_rendering import _render_step_result, output_failure
from functions_orchestration_result_contracts import EXTERNAL_SESSION_UNAVAILABLE_REASON
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_support.versioning import assert_app_version_at_least


def _no_session(record, *, operation):
    raise ResultUnavailableError(EXTERNAL_SESSION_UNAVAILABLE_REASON)


def test_version_includes_the_file_sign_in_fix():
    assert_app_version_at_least('0.261.303')


def test_publication_is_checked_by_the_service_that_rendered_the_file(lifecycle, monkeypatch):
    import functions_orchestration_artifacts as artifacts

    attempt_service = lifecycle.service
    # What the registered factory built on a worker thread: no signed-in session to check sources.
    sessionless = lifecycle.restart()
    lifecycle.service = attempt_service
    sessionless.authorize_execution = _no_session
    monkeypatch.setattr(artifacts, '_service_factory', lambda user_id, conversation_id: sessionless)

    completed = lifecycle.run(lifecycle.prepare())
    assert completed['state'] == 'completed', completed
    assert lifecycle.blobs.uploads == 1

    # Once the attempt ends, a publication check uses a fresh service again, and a refusal
    # caused only by the missing sign-in keeps that reason.
    message = attempt_service.transport.message(lifecycle.raw(completed), committed=True)
    with pytest.raises(OutputUnavailableError) as refused:
        lifecycle.modules.sources.authorize_generated_artifact_source('owner', message, for_publication=True)
    assert refused.value.code == OUTPUT_SIGN_IN_REQUIRED


def test_another_conversations_attempt_never_authorizes_this_publication(lifecycle, monkeypatch):
    import functions_orchestration_artifacts as artifacts

    completed = lifecycle.run(lifecycle.prepare())
    message = lifecycle.service.transport.message(lifecycle.raw(completed), committed=True)
    sessionless = lifecycle.restart()
    sessionless.authorize_execution = _no_session
    monkeypatch.setattr(artifacts, '_service_factory', lambda user_id, conversation_id: sessionless)
    foreign = type('Foreign', (), {})()
    foreign.store = type('Store', (), {'user_id': 'owner', 'conversation_id': 'conversation-2'})()
    with artifacts.render_attempt_scope(foreign):
        with pytest.raises(OutputUnavailableError) as refused:
            lifecycle.modules.sources.authorize_generated_artifact_source('owner', message, for_publication=True)
    assert refused.value.code == OUTPUT_SIGN_IN_REQUIRED


def test_a_file_that_needs_a_sign_in_says_so_and_offers_no_file_only_retry(lifecycle, production_modules):
    service = lifecycle.service
    real = service.authorize_execution

    def background(record, *, operation):
        # A render running in the background: checking its sources needs a sign-in it lacks.
        if operation == 'prepare':
            raise ResultUnavailableError(EXTERNAL_SESSION_UNAVAILABLE_REASON)
        return real(record, operation=operation)

    service.authorize_execution = background
    output = lifecycle.prepare()
    failed = lifecycle.run(output)
    assert failed['state'] == 'failed'
    assert failed['error_code'] == OUTPUT_SIGN_IN_REQUIRED
    assert failed['message'] == OUTPUT_UNAVAILABLE_MESSAGES[OUTPUT_SIGN_IN_REQUIRED]
    assert failed['can_retry'] is False and failed['next_retry_at'] is None
    assert lifecycle.raw(output)['automatic_attempts'] == 1
    assert lifecycle.blobs.uploads == 0

    # Read from a signed-in request, the saved file says why it could not be created.
    service.authorize_execution = real
    saved = service.read(output['output_id'])
    assert saved['state'] == 'failed' and saved['available'] is True
    assert saved['error_code'] == OUTPUT_SIGN_IN_REQUIRED
    assert saved['message'] == OUTPUT_FAILURE_MESSAGES[OUTPUT_SIGN_IN_REQUIRED]
    assert saved['can_retry'] is False
    with pytest.raises(OutputError):
        service.manual_retry(output['output_id'], 'file-only-retry')

    schema = production_modules.schema
    step = _render_step_result(
        saved, None, build_step_result=schema.build_step_result, build_failure=schema.build_failure,
    )
    assert step['status'] == 'failed'
    assert step['failure']['code'] == 'file_sign_in_required'
    assert step['failure']['message'] == schema.FAILURE_MESSAGES['file_sign_in_required']
    assert step['summary'] == saved['message']


def test_only_a_missing_session_is_classified_as_a_sign_in_requirement():
    refused = ResultUnavailableError(EXTERNAL_SESSION_UNAVAILABLE_REASON)
    wrapped = OutputUnavailableError('output_access_denied')
    wrapped.__cause__ = refused
    assert signed_in_session_required(refused) and signed_in_session_required(wrapped)
    assert output_failure(refused) == (OUTPUT_SIGN_IN_REQUIRED, False)
    assert output_failure(wrapped) == (OUTPUT_SIGN_IN_REQUIRED, False)

    denied = ResultUnavailableError('external_identity_access_denied')
    assert not signed_in_session_required(denied)
    assert output_failure(denied) == ('output_access_denied', False)
