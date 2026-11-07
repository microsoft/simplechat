// usePromptKnowledgeFill.ts

import { useEffect, useRef, useState } from 'react';
import { ApiError } from './apiClient';
import {
    fillPromptFromKnowledge,
    type PromptKnowledgeRequest,
    type PromptKnowledgeUnresolved,
    type PromptKnowledgeValue,
} from './promptKnowledge';
import type { PromptVariableValues } from './usePromptVariableValues';

export function usePromptKnowledgeFill({
    request,
    variableState,
    enabled,
    draftKey,
}: {
    request: PromptKnowledgeRequest;
    variableState: PromptVariableValues;
    enabled: boolean;
    draftKey: string;
}) {
    const identity = JSON.stringify([request, enabled, draftKey]);
    const latest = useRef({ identity, request, variableState, enabled });
    latest.current = { identity, request, variableState, enabled };
    const controller = useRef<AbortController | null>(null);
    const revisions = useRef<Record<string, number>>({});
    const [pendingKeys, setPendingKeys] = useState<string[]>([]);
    const [unresolved, setUnresolved] = useState<PromptKnowledgeUnresolved[]>([]);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    useEffect(() => {
        controller.current?.abort();
        controller.current = null;
        setPendingKeys([]);
        setUnresolved([]);
        setNotice('');
        setError('');
        return () => controller.current?.abort();
    }, [identity]);

    const cancel = () => {
        if (!controller.current) {
            return;
        }
        controller.current?.abort();
        controller.current = null;
        setPendingKeys([]);
        setNotice('Knowledge lookup cancelled. Your values have not been removed.');
    };

    const fill = async (keys?: string[]) => {
        const current = latest.current;
        if (!current.enabled) {
            setError('Choose knowledge to search before filling variables.');
            return;
        }
        const variables = current.variableState.unfilled.filter(
            (variable) => !variable.builtIn && (!keys || keys.includes(variable.key)),
        );
        if (variables.length === 0) {
            setNotice('There are no unanswered custom variables to fill.');
            return;
        }

        controller.current?.abort();
        const active = new AbortController();
        controller.current = active;
        const expected = Object.fromEntries(
            variables.map((variable) => [
                variable.key,
                current.variableState.getRevision(variable.key),
            ]),
        );
        revisions.current = expected;
        setPendingKeys(variables.map((variable) => variable.key));
        setUnresolved([]);
        setError('');
        setNotice('Searching knowledge for your missing values...');

        try {
            const knownValues = Object.fromEntries(
                Object.entries(current.variableState.getResolvedValues())
                    .filter(([, value]) => value.trim()),
            );
            const response = await fillPromptFromKnowledge(
                { ...current.request, known_values: knownValues },
                variables.map(({ key, name }) => ({ key, name })),
                active.signal,
            );
            if (active.signal.aborted || latest.current.identity !== current.identity) {
                return;
            }
            let filled = 0;
            for (const value of response.values) {
                if (
                    Object.prototype.hasOwnProperty.call(expected, value.key)
                    && latest.current.variableState.applyAiValue(
                        value.key, value, expected[value.key],
                    )
                ) {
                    filled += 1;
                }
            }
            setUnresolved(response.unresolved.filter((item) => Object.prototype.hasOwnProperty.call(expected, item.key)));
            setNotice(
                filled > 0
                    ? `Filled ${filled} ${filled === 1 ? 'variable' : 'variables'} from knowledge. Review the values and sources before sending.`
                    : 'No values were filled. Review the fields below or choose different knowledge.',
            );
        } catch (failure) {
            if (!active.signal.aborted && latest.current.identity === current.identity) {
                setNotice('');
                setError(
                    failure instanceof ApiError
                        ? failure.message
                        : 'Unable to fill variables from knowledge. Your draft is unchanged.',
                );
            }
        } finally {
            if (controller.current === active) {
                controller.current = null;
                setPendingKeys([]);
            }
        }
    };

    const currentUnresolved = unresolved.filter(
        (item) => variableState.getRevision(item.key) === revisions.current[item.key],
    );

    const chooseAlternative = (key: string, value: PromptKnowledgeValue) => {
        if (latest.current.variableState.applyAiValue(key, value, revisions.current[key])) {
            setUnresolved((items) => items.filter((item) => item.key !== key));
            setNotice('Value selected. Review its sources before sending.');
        }
    };

    return { fill, cancel, pendingKeys, unresolved: currentUnresolved, notice, error, chooseAlternative };
}
