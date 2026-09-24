// ImportMembersDialog.tsx
// Add many people from a CSV file, in the classic manage page's format.
//
// The file is checked with the classic rules before anything is sent (parseMemberCsv), and a
// file with any problem is refused whole, as there. Each row is then added one at a time
// through the native add route, and each row's outcome is kept: added, already a member, or the
// server's own reason it was refused. The failed rows stay listed and can be retried on their
// own. A refusal that every later row would get too -- the caller lost their standing, or the
// group can no longer take members -- stops the run, and the rows not yet tried are kept as
// failed, so a retry picks them up.

import { useRef, useState } from 'react';
import { FileUp, Loader2, RotateCcw } from 'lucide-react';
import { clsx } from 'clsx';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { groupRoleLabel } from '../../lib/groupWorkspaceNavigation';
import { MEMBER_CSV_HEADER, parseMemberCsv, type MemberCsvRow } from '../../lib/groupMembership';

export type ImportRowOutcome =
    | { status: 'added'; name: string }
    | { status: 'already_member'; message: string }
    | { status: 'failed'; message: string; stop: boolean };

interface ImportEntry {
    row: MemberCsvRow;
    outcome: ImportRowOutcome | null;
}

type Stage = 'choose' | 'running' | 'done';

const NOT_ATTEMPTED = 'Not attempted: the import stopped at an earlier row.';
const MAX_LISTED_ERRORS = 10;

function isFailed(entry: ImportEntry): boolean {
    return !entry.outcome || entry.outcome.status === 'failed';
}

function outcomeText(outcome: ImportRowOutcome | null): string {
    if (!outcome) return 'Waiting';
    if (outcome.status === 'added') return 'Added';
    if (outcome.status === 'already_member') return 'Already a member';
    return outcome.message;
}

export function ImportMembersDialog({
    onAddRow, onRunningChange, onFinished, onClose,
}: {
    onAddRow: (row: MemberCsvRow) => Promise<ImportRowOutcome>;
    onRunningChange: (running: boolean) => void;
    onFinished: () => void;
    onClose: () => void;
}) {
    const [stage, setStage] = useState<Stage>('choose');
    const [fileName, setFileName] = useState('');
    const [errors, setErrors] = useState<string[]>([]);
    const [entries, setEntries] = useState<ImportEntry[]>([]);
    const [progress, setProgress] = useState('');
    const running = useRef(false);

    const chooseFile = async (file: File | undefined) => {
        setErrors([]);
        setEntries([]);
        setFileName(file?.name ?? '');
        if (!file) return;
        let text: string;
        try {
            text = await file.text();
        } catch {
            setErrors(['The file could not be read. Choose it again.']);
            return;
        }
        const parsed = parseMemberCsv(text);
        if (parsed.errors.length) {
            setErrors(parsed.errors);
            return;
        }
        setEntries(parsed.rows.map((row) => ({ row, outcome: null })));
    };

    const run = async (targets: ImportEntry[]) => {
        if (running.current || !targets.length) return;
        running.current = true;
        onRunningChange(true);
        setStage('running');
        let stopped = false;
        let index = 0;
        for (const target of targets) {
            index += 1;
            setProgress(`Adding ${index} of ${targets.length}: ${target.row.displayName}`);
            let outcome: ImportRowOutcome;
            if (stopped) {
                outcome = { status: 'failed', message: NOT_ATTEMPTED, stop: false };
            } else {
                outcome = await onAddRow(target.row);
                stopped = outcome.status === 'failed' && outcome.stop;
            }
            setEntries((current) => current.map((entry) => (entry.row.row === target.row.row ? { ...entry, outcome } : entry)));
        }
        running.current = false;
        onRunningChange(false);
        setProgress('');
        setStage('done');
        onFinished();
    };

    const added = entries.filter((entry) => entry.outcome?.status === 'added').length;
    const alreadyMembers = entries.filter((entry) => entry.outcome?.status === 'already_member').length;
    const failed = entries.filter((entry) => entry.outcome && entry.outcome.status === 'failed');
    const busy = stage === 'running';

    return (
        <Modal title="Import members from CSV" size="lg"
            description={`Columns ${MEMBER_CSV_HEADER}. Roles are user, admin or document_manager. Up to 1,000 rows.`}
            onClose={busy ? () => undefined : onClose}
            footer={(
                <>
                    {stage === 'done' && failed.length ? (
                        <GlassButton size="sm" onClick={() => void run(entries.filter(isFailed))}>
                            <RotateCcw size={14} />Retry {failed.length} failed {failed.length === 1 ? 'row' : 'rows'}
                        </GlassButton>
                    ) : null}
                    <GlassButton size="sm" disabled={busy} onClick={onClose}>{stage === 'done' ? 'Done' : 'Cancel'}</GlassButton>
                    {stage === 'choose' ? (
                        <GlassButton size="sm" variant="primary" disabled={!entries.length} onClick={() => void run(entries)}>
                            <FileUp size={14} />{entries.length ? `Add ${entries.length} ${entries.length === 1 ? 'member' : 'members'}` : 'Add members'}
                        </GlassButton>
                    ) : null}
                </>
            )}>
            <div className="space-y-3">
                {stage === 'choose' ? (
                    <>
                        <label className="block space-y-1 text-xs text-text-2">
                            <span>CSV file</span>
                            <input type="file" accept=".csv,text/csv" aria-label="CSV file"
                                className="block w-full min-w-0 text-sm text-text-2 file:mr-3 file:rounded-lg file:border-0 file:bg-surface-2 file:px-3 file:py-1.5 file:text-sm file:text-text-1"
                                onChange={(event) => void chooseFile(event.target.files?.[0])} />
                        </label>
                        <p className="text-xs text-text-3">
                            Each person is looked up in the directory by their user ID. The name and email in the file are used only when the directory can't be reached.
                        </p>
                        {errors.length ? (
                            <div role="alert" className="space-y-1 rounded-xl border border-danger/30 bg-danger-soft p-3 text-xs text-danger">
                                <p className="font-medium">{fileName ? `${fileName} can't be imported.` : 'This file can\'t be imported.'} Found {errors.length} {errors.length === 1 ? 'problem' : 'problems'}:</p>
                                <ul className="list-disc space-y-0.5 pl-5">
                                    {errors.slice(0, MAX_LISTED_ERRORS).map((error) => <li key={error} className="break-words">{error}</li>)}
                                </ul>
                                {errors.length > MAX_LISTED_ERRORS ? <p>... and {errors.length - MAX_LISTED_ERRORS} more</p> : null}
                            </div>
                        ) : null}
                        {entries.length ? (
                            <div role="status" className="space-y-1 rounded-xl border border-edge p-3 text-xs text-text-2">
                                <p className="font-medium text-text-1">{entries.length} {entries.length === 1 ? 'member is' : 'members are'} ready to add.</p>
                                <ul className="space-y-0.5">
                                    {entries.slice(0, 3).map((entry) => (
                                        <li key={entry.row.row} className="break-words">
                                            {entry.row.displayName} ({entry.row.email}) as {groupRoleLabel(entry.row.role)}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ) : null}
                    </>
                ) : (
                    <>
                        {busy ? (
                            <p role="status" className="flex items-center gap-2 text-sm text-text-2">
                                <Loader2 size={15} className="animate-spin" /><span className="min-w-0 break-words">{progress}</span>
                            </p>
                        ) : (
                            <p role="status" className="text-sm text-text-1">
                                {added} added, {alreadyMembers} already {alreadyMembers === 1 ? 'a member' : 'members'}, {failed.length} failed.
                            </p>
                        )}
                        <ul aria-label="Import results" className="max-h-72 space-y-1 overflow-y-auto">
                            {entries.map((entry) => (
                                <li key={entry.row.row} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border border-edge px-3 py-1.5 text-xs">
                                    <span className="text-text-3">Row {entry.row.row}</span>
                                    <span className="min-w-0 break-words font-medium text-text-1">{entry.row.displayName}</span>
                                    <span className={clsx(
                                        'min-w-0 break-words',
                                        entry.outcome?.status === 'failed' ? 'text-danger'
                                            : entry.outcome?.status === 'added' ? 'text-ok' : 'text-text-3',
                                    )}>{outcomeText(entry.outcome)}</span>
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </div>
        </Modal>
    );
}
