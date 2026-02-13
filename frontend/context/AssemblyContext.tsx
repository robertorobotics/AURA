"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import useSWR, { mutate as globalMutate } from "swr";
import type { Assembly, AssemblySummary } from "@/lib/types";
import { MOCK_ASSEMBLY, MOCK_SUMMARIES } from "@/lib/mock-data";
import { api } from "@/lib/api";

interface AssemblyContextValue {
  assemblies: AssemblySummary[];
  assembly: Assembly | null;
  isLoading: boolean;
  selectedStepId: string | null;
  selectStep: (stepId: string | null) => void;
  selectAssembly: (assemblyId: string, data?: Assembly) => void;
  refreshAssemblies: () => void;
  deleteAssembly: (id: string) => Promise<void>;
}

const AssemblyContext = createContext<AssemblyContextValue | null>(null);

export function AssemblyProvider({ children }: { children: ReactNode }) {
  const [assemblyId, setAssemblyId] = useState<string>(
    MOCK_SUMMARIES[0]?.id ?? "",
  );
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  const { data: assemblies = MOCK_SUMMARIES, mutate: mutateAssemblies } =
    useSWR<AssemblySummary[]>(
      "/assemblies",
      api.fetchAssemblySummaries,
      { fallbackData: MOCK_SUMMARIES },
    );

  const refreshAssemblies = useCallback(() => {
    void mutateAssemblies();
  }, [mutateAssemblies]);

  // Auto-select gearbox if available (more impressive demo than bearing housing)
  const autoSelected = useRef(false);
  useEffect(() => {
    if (autoSelected.current) return;
    const gearbox = assemblies.find((a) => a.id === "assem_gearbox");
    if (gearbox) {
      autoSelected.current = true;
      setAssemblyId(gearbox.id);
    }
  }, [assemblies]);

  const { data: assembly = null, isLoading } = useSWR<Assembly>(
    assemblyId ? `/assemblies/${assemblyId}` : null,
    () => api.fetchAssembly(assemblyId),
    { fallbackData: assemblyId === MOCK_ASSEMBLY.id ? MOCK_ASSEMBLY : undefined },
  );

  const selectStep = useCallback((stepId: string | null) => {
    setSelectedStepId(stepId);
  }, []);

  const selectAssembly = useCallback(
    (id: string, data?: Assembly) => {
      if (data) {
        void globalMutate(`/assemblies/${id}`, data, false);
      }
      setAssemblyId(id);
      setSelectedStepId(null);
    },
    [],
  );

  const deleteAssembly = useCallback(
    async (id: string) => {
      await api.deleteAssembly(id);
      const updated = await mutateAssemblies();
      if (id === assemblyId) {
        const remaining = updated?.filter((a) => a.id !== id);
        setAssemblyId(remaining?.[0]?.id ?? MOCK_SUMMARIES[0]?.id ?? "");
        setSelectedStepId(null);
      }
    },
    [assemblyId, mutateAssemblies],
  );

  const value = useMemo<AssemblyContextValue>(
    () => ({
      assemblies,
      assembly,
      isLoading,
      selectedStepId,
      selectStep,
      selectAssembly,
      refreshAssemblies,
      deleteAssembly,
    }),
    [assemblies, assembly, isLoading, selectedStepId, selectStep, selectAssembly, refreshAssemblies, deleteAssembly],
  );

  return (
    <AssemblyContext.Provider value={value}>{children}</AssemblyContext.Provider>
  );
}

export function useAssembly(): AssemblyContextValue {
  const ctx = useContext(AssemblyContext);
  if (!ctx) throw new Error("useAssembly must be used within AssemblyProvider");
  return ctx;
}
