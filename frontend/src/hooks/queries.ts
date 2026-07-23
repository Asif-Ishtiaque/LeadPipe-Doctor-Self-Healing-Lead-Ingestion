import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useActiveDataset } from "../lib/datasetContext";
import type { CallStatus } from "../lib/types";

// Poll the read endpoints on a light interval so the dashboard feels live,
// mirroring the Streamlit app's 5s cache TTL.
const live = { refetchInterval: 8000, staleTime: 4000 };

// Every dashboard read folds in the active dataset (null = all datasets), so
// each page scopes automatically. `did` is part of the query key so switching
// datasets refetches cleanly.

export const useStats = () => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({ queryKey: ["stats", did], queryFn: () => api.stats(did), ...live });
};

export const useAnalytics = () => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({ queryKey: ["analytics", did], queryFn: () => api.analytics(did), ...live });
};

export const useTopLeads = (limit = 8, opts?: { source?: string; minScore?: number; maxScore?: number }) => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({
    queryKey: ["top-leads", limit, opts?.source ?? "all", opts?.minScore ?? "", opts?.maxScore ?? "", did],
    queryFn: () => api.topLeads(limit, { ...opts, datasetId: did }),
    ...live,
  });
};

// Paginated score-ranked call list. keepPreviousData holds the current page
// on screen while the next one loads, so paging doesn't flash empty.
export const useRankedLeads = (limit: number, offset: number, opts?: { source?: string; minScore?: number; maxScore?: number }) => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({
    queryKey: ["ranked-leads", limit, offset, opts?.source ?? "all", opts?.minScore ?? "", opts?.maxScore ?? "", did],
    queryFn: () => api.rankedLeads(limit, offset, { ...opts, datasetId: did }),
    placeholderData: keepPreviousData,
    ...live,
  });
};

// Debounced search string flows in as `q`, plus the smart-filter options.
export const useSearchLeads = (q: string, limit = 200, opts?: { source?: string; minScore?: number; flagged?: boolean }) => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({
    queryKey: ["search-leads", q, limit, opts?.source ?? "", opts?.minScore ?? "", opts?.flagged ?? "", did],
    queryFn: () => api.searchLeads(q, limit, { ...opts, datasetId: did }),
    placeholderData: keepPreviousData,
    ...live,
  });
};

// The rep call queue. NOT on the live poll -- a rep works a stable snapshot;
// worked leads drop off only on an explicit reload (refetch).
export const useCallList = (limit = 20) => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({
    queryKey: ["call-list", limit, did],
    queryFn: () => api.callList(limit, did),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
};

export const useSourcePerformance = () => {
  const { datasetId: did } = useActiveDataset();
  return useQuery({ queryKey: ["source-performance", did], queryFn: () => api.sourcePerformance(did), ...live });
};

// Datasets (the list is global, not dataset-scoped).
export const useDatasets = () => useQuery({ queryKey: ["datasets"], queryFn: api.datasets, ...live });

export const useDeleteDataset = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteDataset(id),
    onSuccess: () => qc.invalidateQueries(),
  });
};

export const useRenameDataset = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.renameDataset(id, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
};

// Set a lead's disposition; refresh the stats/overview counts on success.
export const useSetDisposition = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, status }: { leadId: string; status: CallStatus }) => api.setLeadStatus(leadId, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stats"] }),
  });
};

export const usePipelineRuns = (limit = 20) =>
  useQuery({ queryKey: ["pipeline-runs", limit], queryFn: () => api.pipelineRuns(limit), ...live });

export const useDuplicates = () => useQuery({ queryKey: ["duplicates"], queryFn: () => api.duplicates(), ...live });
export const useInvalid = () => useQuery({ queryKey: ["invalid"], queryFn: () => api.invalid(), ...live });
export const useHealing = () => useQuery({ queryKey: ["healing"], queryFn: () => api.healingEvents(), ...live });
export const useHumanReview = () => useQuery({ queryKey: ["human-review"], queryFn: api.humanReview, ...live });
