/*
 * Adding, ticking, rewriting and removing prep items.
 *
 * Invalidated rather than patched, matching useInterviewEditing and for the
 * same reason: these rows have a second writer. Claude appends to the list
 * through the MCP tool while the page is open, and a local patch would quietly
 * paper over whatever it added. The list is a dozen rows; the refetch is free.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postJSON } from "../api/client";
import { jobKeyFields, rowKey, type JobKeyInput } from "../lib/jobFields";
import type { PrepKind } from "../api/types";

/** Matches every ["jobDetail", key, ...] entry for one job.
 *
 *  Third copy of this predicate, and the third time for the same reason: the
 *  key object is compared structurally, so a filter built from a fat Job row
 *  matches none of the entries mounted with a bare JobKey. If a fourth appears,
 *  it belongs in lib/jobFields. */
function jobDetailEntries(key: JobKeyInput) {
  const target = rowKey(key);
  return {
    predicate: (q: { queryKey: readonly unknown[] }) =>
      q.queryKey[0] === "jobDetail" &&
      q.queryKey[1] != null &&
      rowKey(q.queryKey[1] as JobKeyInput) === target,
  };
}

export function usePrepEditing(job: JobKeyInput) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries(jobDetailEntries(job));
  };

  const addItem = useMutation({
    mutationFn: (fields: { kind: PrepKind; body: string }) =>
      postJSON<{ id: number }>("/api/prep/add", { ...jobKeyFields(job), ...fields }),
    onSuccess: refresh,
  });

  const setDone = useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) =>
      postJSON<unknown>("/api/prep/update", { id, done }),
    onSuccess: refresh,
  });

  const editItem = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) =>
      postJSON<unknown>("/api/prep/update", { id, body }),
    onSuccess: refresh,
  });

  const deleteItem = useMutation({
    mutationFn: (id: number) => postJSON<unknown>("/api/prep/delete", { id }),
    onSuccess: refresh,
  });

  return { addItem, setDone, editItem, deleteItem };
}
