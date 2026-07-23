import { createContext, useContext, useState, type ReactNode } from "react";

// The dashboard scopes to one "active" dataset (or all, when null). The choice
// is held here and persisted, and every read hook folds it into its query, so
// each page scopes automatically without threading the id through page props.
const STORAGE_KEY = "leadrx.activeDataset";

interface DatasetCtx {
  datasetId: string | null;
  setDatasetId: (id: string | null) => void;
}

const DatasetContext = createContext<DatasetCtx>({ datasetId: null, setDatasetId: () => {} });

export function DatasetProvider({ children }: { children: ReactNode }) {
  const [datasetId, setId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  });

  const setDatasetId = (id: string | null) => {
    setId(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore storage errors (private mode etc.) */
    }
  };

  return <DatasetContext.Provider value={{ datasetId, setDatasetId }}>{children}</DatasetContext.Provider>;
}

export function useActiveDataset() {
  return useContext(DatasetContext);
}
