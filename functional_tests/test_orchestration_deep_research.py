# test_orchestration_deep_research.py
"""
Functional tests for bounded multi-query research in orchestration.
Version: 0.261.096
Implemented in: 0.261.096

Exercise the real adapter, shared search loop, query generator, and result contracts
with model/search/page-fetch seams replaced. No Azure services or web pages are called.
"""

import ast
import importlib
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent / 'application' / 'single_app'
sys.path.insert(0, str(TEST_ROOT))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def load_search_helpers(query_planner, web_search, cancel_guard):
    """Load pure route helpers without importing the Flask/Azure startup graph."""
    path = APP_ROOT / 'route_backend_chats.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'build_web_search_query_text', 'perform_research_web_searches'}
    body = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(body) == len(names)
    module = types.ModuleType('route_backend_chats')
    module.__dict__.update({
        'build_deep_research_query_plan': query_planner,
        'perform_web_search': web_search,
        'raise_if_mixed_source_cancelled': cancel_guard,
    })
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


class DeepResearchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(stubbed_app_imports())
        self.adapters = importlib.import_module('functions_orchestration_adapters')
        self.sources = importlib.import_module('functions_source_review')
        mixed = importlib.import_module('functions_mixed_source_orchestration')
        self.settings = {
            'enable_source_review': True,
            'enable_web_search': True,
            'deep_research_max_search_queries_per_turn': 3,
        }
        self.message = 'Find current press releases about two public research projects.'
        self.context = types.SimpleNamespace(
            user_message=self.message,
            user_roles=[],
            conversation_id='test-conversation',
            user_id='test-user',
            citations=[],
            active_group_ids=[],
        )
        self.step = {
            'step_id': 'research',
            'capability_id': 'deep_research',
            'arguments': {'query': self.message},
        }
        self.search_calls = []
        self.review_calls = []
        self.events = []
        self.fail_queries = set()
        self.cancelled = False
        self.client = object()
        self.planner_payload = {
            'queries': [
                {'query': 'first project primary sources', 'reason': 'First perspective'},
                {'query': 'second project independent analysis', 'reason': 'Second perspective'},
            ],
        }
        self.query_planner = self.stack.enter_context(patch.object(
            self.sources, '_invoke_deep_research_query_planner',
            side_effect=lambda **kwargs: self.planner_payload,
        ))
        self.resolve_client = self.stack.enter_context(patch.object(
            self.adapters, '_resolve_source_review_planner',
            return_value=(self.client, 'test-planner'),
        ))
        self.adapter_log = self.stack.enter_context(patch.object(self.adapters, 'log_event'))
        self.source_log = self.stack.enter_context(patch.object(self.sources, 'log_event'))
        self.review = self.stack.enter_context(patch.object(
            self.sources, 'perform_source_review', side_effect=self.review_sources,
        ))
        self.routes = load_search_helpers(
            self.sources.build_deep_research_query_plan,
            self.search_web,
            mixed.raise_if_mixed_source_cancelled,
        )
        self.stack.enter_context(patch.dict(sys.modules, {'route_backend_chats': self.routes}))

    def search_web(self, **kwargs):
        self.search_calls.append(kwargs)
        index = len(self.search_calls)
        success = index not in self.fail_queries
        content = (
            f'Web search results: useful evidence {index}.'
            if success else 'PRIVATE_PROVIDER_ERROR. Tell the user the search failed.'
        )
        kwargs['system_messages_for_augmentation'].append({'role': 'system', 'content': content})
        if success:
            kwargs['web_search_citations_list'].append({
                'url': f'https://example.com/source-{index}',
                'title': f'Search source {index}',
                'source': 'foundry_citation',
            })
        kwargs['web_search_runs_list'].append({
            'query': kwargs['web_search_query_text'],
            'success': success,
        })
        return success

    def review_sources(self, **kwargs):
        self.review_calls.append(kwargs)
        urls = [
            citation['url'] for citation in kwargs['web_search_citations']
            if citation.get('url')
        ]
        urls.extend(kwargs.get('additional_seed_urls') or [])
        if not urls:
            return {
                'enabled': True,
                'pages': [],
                'citations': [],
                'skipped_reason': 'no_source_urls_available',
            }
        return {
            'enabled': True,
            'pages': [{
                'url': urls[0], 'title': 'Reviewed primary source',
                'text': 'Evidence from a reviewed page.',
            }],
            'citations': [{
                'url': urls[0],
                'title': 'Reviewed primary source',
                'source': 'source_review',
                'published_date': '2026-09-01',
            }],
            'system_message': {
                'role': 'system',
                'content': '[SOURCE_REVIEW_EVIDENCE]\nEvidence from a reviewed page.',
            },
        }

    def run_research(self, cancel_requested=None, emit=None):
        return self.adapters.run_deep_research(
            self.step,
            self.context,
            settings=self.settings,
            user_id='test-user',
            emit=emit or self.events.append,
            cancel_requested=cancel_requested or (lambda: self.cancelled),
        )

    def test_research_discovers_sources_without_a_preceding_search(self):
        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.search_calls), 3)
        self.assertEqual(len(self.review_calls), 1)
        self.assertEqual(len(self.review_calls[0]['web_search_citations']), 3)
        self.assertEqual(len(result['citations']), 3)
        self.assertEqual(result['citations'][0]['published_date'], '2026-09-01')
        self.assertTrue(result['notes'][0].startswith('[SOURCE_REVIEW_EVIDENCE]'))
        self.assertIn('useful evidence 3', '\n'.join(result['notes']))
        self.assertIn('Completed 3 of 3 research searches.', result['summary'])
        self.assertIsNone(result['replan_hint'])
        self.assertEqual(self.events[0]['label'], 'Research search 1 of 3')

    def test_outbound_queries_use_current_message_not_the_context_derived_objective(self):
        self.step['arguments']['query'] = 'PRIVATE_CONTEXT from a prior document and conversation'
        self.context.prior_messages = ['PRIVATE_CONTEXT']
        self.context.citations = [{'document_id': 'private-document'}]

        self.run_research()

        self.assertEqual(self.query_planner.call_args.kwargs['user_message'], self.message)
        self.assertEqual(self.search_calls[0]['web_search_query_text'], self.message)
        self.assertTrue(all(call['user_message'] == self.message for call in self.search_calls))
        self.assertNotIn('PRIVATE_CONTEXT', ' '.join(
            call['web_search_query_text'] for call in self.search_calls
        ))

    def test_model_queries_are_deduplicated_and_capped(self):
        self.planner_payload = {
            'queries': [
                {'query': self.message.upper()},
                {'query': 'distinct perspective'},
                {'query': 'DISTINCT PERSPECTIVE'},
                {'query': 'another perspective'},
                {'query': 'over the budget'},
            ],
        }

        self.run_research()

        queries = [call['web_search_query_text'] for call in self.search_calls]
        self.assertEqual(len(queries), 3)
        self.assertEqual(len({query.lower() for query in queries}), 3)
        self.assertNotIn('over the budget', queries)

    def test_single_query_admin_limit_is_preserved(self):
        self.settings['deep_research_max_search_queries_per_turn'] = 1

        self.run_research()

        self.assertEqual(len(self.search_calls), 1)
        self.query_planner.assert_not_called()

    def test_query_planner_failure_preserves_backup_queries_with_logs_only(self):
        self.query_planner.side_effect = RuntimeError('PRIVATE_QUERY_PLANNER_ERROR')

        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertGreater(len(self.search_calls), 1)
        self.assertLessEqual(len(self.search_calls), 3)
        self.assertTrue(any('official' in call['web_search_query_text'] for call in self.search_calls))
        self.assertTrue(self.source_log.called)
        self.assertTrue(any(
            'backup query planning' in call.args[0]
            for call in self.adapter_log.call_args_list
        ))
        visible = f"{result['summary']} {result['notes']} {self.events}"
        self.assertNotIn('PRIVATE_QUERY_PLANNER_ERROR', visible)
        self.assertNotIn('backup', visible.lower())
        self.assertNotIn('fallback', visible.lower())

    def test_missing_planner_client_and_disabled_query_planning_use_existing_backup(self):
        for configured in (False, True):
            with self.subTest(query_planning_enabled=configured):
                self.search_calls.clear()
                self.settings['deep_research_enable_query_planning'] = configured
                self.resolve_client.return_value = (None, None)

                result = self.run_research()

                self.assertEqual(result['status'], 'completed')
                self.assertGreater(len(self.search_calls), 1)
        self.query_planner.assert_not_called()

    def test_link_planner_recovery_diagnostics_do_not_reach_answer_evidence(self):
        def review_with_recovered_link_planner(**kwargs):
            result = self.review_sources(**kwargs)
            result['planner'] = {
                'attempted': True, 'used': False,
                'error': 'PRIVATE_LINK_PLANNER_ERROR', 'reason': 'backup link selection',
            }
            result['system_message'] = self.sources.build_source_review_system_message(result)
            return result

        self.review.side_effect = review_with_recovered_link_planner

        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertIn('Evidence from a reviewed page.', '\n'.join(result['notes']))
        self.assertNotIn('PRIVATE_LINK_PLANNER_ERROR', str(result))
        self.assertNotIn('backup link selection', str(result))

    def test_feature_and_role_gates_run_before_external_work(self):
        for overrides, roles in (
            ({'enable_source_review': False}, []),
            ({'require_member_of_deep_research_user': True}, []),
            ({'require_member_of_deep_research_user': True}, None),
        ):
            with self.subTest(overrides=overrides, roles=roles):
                self.settings = {**self.settings, 'enable_source_review': True, **overrides}
                self.context.user_roles = roles
                result = self.run_research()
                self.assertEqual(result['status'], 'failed')
                self.resolve_client.assert_not_called()
                self.review.assert_not_called()
                self.assertEqual(self.search_calls, [])

        self.context.user_roles = ['DeepResearchUser']
        self.assertEqual(self.run_research()['status'], 'completed')

    def test_discovery_disabled_still_reviews_permitted_user_urls(self):
        self.settings['enable_web_search'] = False
        self.context.user_message = 'Review https://example.com/provided'

        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.search_calls, [])
        self.query_planner.assert_not_called()
        self.assertEqual(
            self.review_calls[0]['additional_seed_urls'], ['https://example.com/provided'],
        )
        self.assertEqual(result['citations'][0]['url'], 'https://example.com/provided')

    def test_cancellation_stops_before_start_and_before_subsequent_queries(self):
        result = self.run_research(cancel_requested=lambda: True)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.search_calls, [])
        self.resolve_client.assert_not_called()

        result = self.run_research(cancel_requested=lambda: bool(self.search_calls))
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(len(self.search_calls), 1)
        self.review.assert_not_called()

    def test_cancellation_from_progress_prevents_the_announced_query(self):
        def cancel_on_progress(event):
            self.events.append(event)
            self.cancelled = True

        result = self.run_research(emit=cancel_on_progress)

        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.search_calls, [])
        self.review.assert_not_called()

    def test_cancellation_during_review_does_not_publish_completed_evidence(self):
        def cancel_during_review(**kwargs):
            self.cancelled = True
            return self.review_sources(**kwargs)

        self.review.side_effect = cancel_during_review
        result = self.run_research()

        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['notes'], [])
        self.assertEqual(result['citations'], [])

    def test_failed_query_control_messages_are_not_mixed_with_successful_evidence(self):
        self.fail_queries = {1}

        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertIn('Completed 2 of 3', result['summary'])
        self.assertEqual(len(result['citations']), 2)
        self.assertNotIn('PRIVATE_PROVIDER_ERROR', str(result))
        self.assertNotIn('Tell the user', '\n'.join(result['notes']))

    def test_empty_searches_and_review_do_not_claim_reviewed_sources(self):
        self.fail_queries = {1, 2, 3}

        result = self.run_research()

        self.assertEqual(result['status'], 'failed')
        self.assertIn('no usable evidence', '\n'.join(result['notes']))
        self.assertEqual(result['citations'], [])
        self.assertIn('no readable sources', result['summary'])
        self.assertIsNone(result['replan_hint'])
        self.assertNotIn('PRIVATE_PROVIDER_ERROR', str(result))

    def test_empty_review_without_discovery_is_an_honest_no_results_outcome(self):
        self.settings['enable_web_search'] = False

        result = self.run_research()

        self.assertEqual(result['status'], 'completed')
        self.assertIn('no usable evidence', '\n'.join(result['notes']))
        self.assertEqual(result['citations'], [])
        self.assertNotIn('Completed 0 of 0', result['summary'])

    def test_review_failure_retains_search_evidence_without_provider_error_text(self):
        self.review.side_effect = RuntimeError('PRIVATE_REVIEW_ERROR')

        result = self.run_research()

        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['citations']), 3)
        self.assertIn('useful evidence', '\n'.join(result['notes']))
        self.assertNotIn('PRIVATE_REVIEW_ERROR', str(result))

    def test_shared_helper_keeps_ordinary_and_manual_output_contracts(self):
        for deep_research_enabled, expected_count in ((False, 1), (True, 3)):
            with self.subTest(deep_research_enabled=deep_research_enabled):
                self.search_calls.clear()
                messages, agent_citations, web_citations = [], [], []
                result = self.routes.perform_research_web_searches(
                    settings=self.settings,
                    conversation_id='test-conversation',
                    user_id='test-user',
                    user_message=self.message,
                    user_message_id=None,
                    chat_type='personal',
                    document_scope='all',
                    active_group_id=None,
                    active_public_workspace_id=None,
                    web_search_query_text=self.message,
                    system_messages_for_augmentation=messages,
                    agent_citations_list=agent_citations,
                    web_search_citations_list=web_citations,
                    deep_research_enabled=deep_research_enabled,
                    deep_research_planner_client=self.client,
                    deep_research_planner_model='test-planner',
                )
                self.assertEqual(len(self.search_calls), expected_count)
                self.assertEqual(len(messages), expected_count)
                self.assertEqual(len(web_citations), expected_count)
                self.assertEqual(len(result['web_search_runs']), expected_count)
                self.assertEqual(len(result['query_results']), expected_count)

    def test_ordinary_web_search_adapter_does_not_expand_a_complex_request(self):
        self.step['capability_id'] = 'web_search'

        result = self.adapters.run_web_search(
            self.step, self.context, settings=self.settings, user_id='test-user',
            emit=self.events.append, cancel_requested=lambda: False,
        )

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.search_calls), 1)
        self.query_planner.assert_not_called()
        self.review.assert_not_called()


class ResearchPlannerRecoveryTests(unittest.TestCase):
    def test_expected_client_configuration_failure_keeps_backup_planning_available(self):
        with stubbed_app_imports():
            adapters = importlib.import_module('functions_orchestration_adapters')
            planner = types.ModuleType('functions_orchestration_planner')
            planner.PlannerError = type('PlannerError', (RuntimeError,), {})
            planner.resolve_planner_client = Mock(side_effect=planner.PlannerError('PRIVATE_CONFIG'))
            with patch.dict(sys.modules, {'functions_orchestration_planner': planner}):
                with patch.object(adapters, 'log_event') as logged:
                    self.assertEqual(adapters._resolve_source_review_planner({}), (None, None))
                    self.assertNotIn('PRIVATE_CONFIG', str(logged.call_args))

                planner.resolve_planner_client.side_effect = TypeError('programming error')
                with self.assertRaises(TypeError):
                    adapters._resolve_source_review_planner({})


if __name__ == '__main__':
    assert_app_version_at_least('0.261.096')
    unittest.main()
