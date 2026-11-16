# test_orchestration_runtime_service_binding.py
"""Central Render uses the parent's initialized actor-bound service, never a replacement.

Version: 0.261.127
Implemented in: 0.261.127
The parent service, context binder and runtime callback are real; artifact I/O is blocked.
"""

import pytest

from functions_orchestration_executor import _context_rendering_service, _dependency_request_context
from functions_orchestration_result_contracts import ResultContractError
from test_orchestration_services import checkpoint_factory, runtime, services
from test_support.orchestration_results import ResultFixture


def bound_context():
    fixture = ResultFixture()
    owner = services(fixture)
    record, context = runtime(fixture)
    owner.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token='owning-lease-token', execution_check=lambda: True,
    )
    return fixture, owner, context


def test_renderer_callback_uses_exact_service_installed_by_parent():
    fixture, owner, context = bound_context()
    selected = _context_rendering_service(context, settings={}, user_id='owner')
    request_context = _dependency_request_context(context)
    assert selected is owner.rendering
    assert selected.results is context.result_service
    assert request_context['rendering_service'] is owner.rendering
    assert 'rendering_service_factory' not in request_context
    assert not fixture.container.items


@pytest.mark.parametrize('change', ['caller', 'actor', 'conversation', 'result_service'])
def test_renderer_callback_rejects_changed_actor_or_replaced_result_service(change):
    fixture, _, context = bound_context()
    caller = 'owner'
    if change == 'caller':
        caller = 'another-owner'
    elif change == 'actor':
        context.user_id = 'another-owner'
    elif change == 'conversation':
        context.conversation_id = 'another-conversation'
    else:
        context.result_service = fixture.restart()
    with pytest.raises(ResultContractError) as failure:
        _context_rendering_service(context, settings={}, user_id=caller)
    assert failure.value.code == 'result_producer_mismatch'
    assert not fixture.container.items


@pytest.mark.parametrize('value', [None, True, {'enabled': True}, lambda: None])
def test_renderer_callback_rejects_non_service_readiness_claims(value):
    fixture, _, context = bound_context()
    context.rendering_service = value
    with pytest.raises(ResultContractError) as failure:
        _context_rendering_service(context, settings={}, user_id='owner')
    assert failure.value.code == 'result_adapter_unavailable'
    assert not fixture.container.items
