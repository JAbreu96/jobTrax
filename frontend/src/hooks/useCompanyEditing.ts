/*
 * Editing the company research notebook.
 *
 * One section at a time, matching how the sections are actually written: the
 * research skill fills two or three in a pass, and a correction by hand touches
 * exactly one. A whole-profile save would turn every hand edit into a race with
 * whatever Claude wrote thirty seconds earlier.
 *
 * The cache entry is patched rather than invalidated -- unlike interview
 * rounds, a profile section has no second writer racing the page. The server
 * answers with the whole stored row, so the patch is the server's own copy and
 * not a guess reassembled on the client.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postJSON } from "../api/client";
import type {
  CompanyProfile, CompanyProfileResponse, CompanySection,
} from "../api/types";

export interface SaveSectionArgs {
  field: CompanySection | "website";
  value: string;
}

export function companyProfileKey(company: string) {
  return ["companyProfile", (company || "").trim().toLowerCase()] as const;
}

export function useCompanyEditing(company: string) {
  const queryClient = useQueryClient();

  const saveSection = useMutation({
    mutationFn: ({ field, value }: SaveSectionArgs) =>
      postJSON<{ ok: boolean; profile: CompanyProfile }>(
        "/api/companies/profile/update", { company, field, value },
      ),
    onSuccess: (result) => {
      queryClient.setQueryData<CompanyProfileResponse>(
        companyProfileKey(company),
        (prev) => ({ company: prev?.company ?? company, profile: result.profile }),
      );
    },
  });

  return { saveSection };
}
