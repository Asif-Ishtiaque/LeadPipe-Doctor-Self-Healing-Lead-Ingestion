import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { api } from "../lib/api";

// Poll the read endpoints on a light interval so the dashboard feels live,
// mirroring the Streamlit app's 5s cache TTL.
const live = { refetchInterval: 8000, staleTime: 4000 };

export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: api.stats, ...live });

// SQL-aggregated metrics behind every chart/KPI — replaces pulling all leads
// into the browser to reduce them client-side.
export const useAnalytics = () => useQuery({ queryKey: ["analytics"], queryFn: api.analytics, ...live });

export const useTopLeads = (
  limit = 8,
  opts?: { source?: string; minScore?: number; maxScore?: number },
) =>
  useQuery({
    queryKey: ["top-leads", limit, opts?.source ?? "all", opts?.minScore ?? "", opts?.maxScore ?? ""],
    queryFn: () => api.topLeads(limit, opts),
    ...live,
  });

// Paginated score-ranked call list. keepPreviousData holds the current page
// on screen while the next one loads, so paging doesn't flash empty.
export const useRankedLeads = (
  limit: number,
  offset: number,
  opts?: { source?: string; minScore?: number; maxScore?: number },
) =>
  useQuery({
    queryKey: ["ranked-leads", limit, offset, opts?.source ?? "all", opts?.minScore ?? "", opts?.maxScore ?? ""],
    queryFn: () => api.rankedLeads(limit, offset, opts),
    placeholderData: keepPreviousData,
    ...live,
  });

// Debounced search string flows in as `q`. keepPreviousData avoids the table
// flashing empty between keystrokes.
export const useSearchLeads = (q: string, limit = 200) =>
  useQuery({
    queryKey: ["search-leads", q, limit],
    queryFn: () => api.searchLeads(q, limit),
    placeholderData: keepPreviousData,
    ...live,
  });

export const useDuplicates = () => useQuery({ queryKey: ["duplicates"], queryFn: () => api.duplicates(), ...live });
export const useInvalid = () => useQuery({ queryKey: ["invalid"], queryFn: () => api.invalid(), ...live });
export const useHealing = () => useQuery({ queryKey: ["healing"], queryFn: () => api.healingEvents(), ...live });
export const useHumanReview = () => useQuery({ queryKey: ["human-review"], queryFn: api.humanReview, ...live });
