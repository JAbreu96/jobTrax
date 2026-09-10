/*
 * The two seams the original relied on `confirm()` and `alert()` for:
 *   - deleteJob() gates on confirm() before deleting.
 *   - saveField()/deleteJob()/saveJobRecruiter()/createRecruiter() alert() on
 *     failure.
 *
 * jsdom implements neither: `window.confirm`/`window.alert` are present but
 * are no-ops that log a "Not implemented" warning and, for confirm, always
 * return `false`. A component that calls `window.confirm` directly is
 * therefore untestable for its "confirmed" branch at all, and every test
 * exercising an error path prints noise.
 *
 * The fix is to make both seams a prop with a real default, not a bare
 * global call baked into the component. Production code gets the same
 * browser dialogs as before (these defaults just forward to `window.*`);
 * tests pass `confirm={() => true}` / `notify={vi.fn()}` and get a component
 * that is actually exercisable, with no jsdom warnings.
 */

export type ConfirmFn = (message: string) => boolean;
export type NotifyFn = (message: string) => void;

export const defaultConfirm: ConfirmFn = (message) => window.confirm(message);

export const defaultNotify: NotifyFn = (message) => window.alert(message);
