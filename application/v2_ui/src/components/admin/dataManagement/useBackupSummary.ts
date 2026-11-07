// useBackupSummary.ts
// Both the readiness and backup cards need one latest-backup read, so this hook shares it.
//
// The read is cached per page visit and per backups revision. The store's epoch advances
// each time the page is left, which is what keeps a later visit from reusing this visit's
// summary after its revision counter starts again from zero.

import { useEffect, useState } from 'react';
import {
    listBackups,
    readHistoryFailure,
    type BackupGlobalSummary,
    type HistoryFailure,
} from '../../../lib/dataManagement';
import { currentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';

export interface BackupSummaryState {
    summary: BackupGlobalSummary | null;
    loading: boolean;
    failure: HistoryFailure | null;
}

let cachedKey: string | null = null;
let cachedSummary: BackupGlobalSummary | null = null;
let cachedFailure: HistoryFailure | null = null;
let inFlight: {
    key: string;
    promise: Promise<BackupGlobalSummary>;
} | null = null;

function loadSummary(key: string): Promise<BackupGlobalSummary> {
    if (inFlight?.key === key) return inFlight.promise;

    const promise = listBackups({ status: 'available', scheduled: 'all', pageSize: 1 }, null)
        .then((page) => {
            cachedKey = key;
            cachedSummary = page.summary ?? {};
            cachedFailure = null;
            return cachedSummary;
        })
        .catch((error: unknown) => {
            cachedKey = key;
            cachedSummary = null;
            cachedFailure = readHistoryFailure(error, 'Backup summary could not be loaded.');
            throw cachedFailure;
        })
        .finally(() => {
            if (inFlight?.key === key) inFlight = null;
        });

    inFlight = { key, promise };
    return promise;
}

export function useBackupSummary(enabled: boolean): BackupSummaryState {
    const backupsRevision = useDataManagementStore((state) => state.backupsRevision);
    const key = `${currentEpoch()}:${backupsRevision}`;
    const [state, setState] = useState<BackupSummaryState>(() => ({
        summary: cachedKey === key ? cachedSummary : null,
        loading: false,
        failure: cachedKey === key ? cachedFailure : null,
    }));

    useEffect(() => {
        if (!enabled) return undefined;

        let active = true;
        if (cachedKey === key) {
            setState({ summary: cachedSummary, loading: false, failure: cachedFailure });
            return () => {
                active = false;
            };
        }

        setState((current) => ({ ...current, loading: true, failure: null }));
        loadSummary(key)
            .then((summary) => {
                if (active) setState({ summary, loading: false, failure: null });
            })
            .catch((failure: HistoryFailure) => {
                if (active) setState({ summary: null, loading: false, failure });
            });

        return () => {
            active = false;
        };
    }, [enabled, key]);

    return state;
}
