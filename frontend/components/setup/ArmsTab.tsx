"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import type { AddArmPayload, HardwareStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";
import { ArmCard } from "./ArmCard";

const INPUT_CLASS =
  "w-full rounded-md border border-bg-tertiary bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-signal focus:outline-none";
const SELECT_CLASS = `${INPUT_CLASS} appearance-none`;
const LABEL_CLASS = "text-[11px] font-medium text-text-secondary";

const EMPTY_FORM: AddArmPayload = {
  id: "",
  name: "",
  role: "follower",
  motorType: "damiao",
  port: "",
  enabled: true,
  structuralDesign: null,
};

const SWR_KEY = "/hardware/status";

export function ArmsTab() {
  const { data } = useSWR<HardwareStatus>(SWR_KEY, api.getHardwareStatus, {
    refreshInterval: 5000,
  });
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<AddArmPayload>(EMPTY_FORM);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const arms = data?.arms ?? [];

  async function handleConnect(armId: string) {
    setActionLoading((prev) => ({ ...prev, [armId]: true }));
    try {
      await api.connectArm(armId);
      await mutate(SWR_KEY);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect");
    } finally {
      setActionLoading((prev) => ({ ...prev, [armId]: false }));
    }
  }

  async function handleDisconnect(armId: string) {
    setActionLoading((prev) => ({ ...prev, [armId]: true }));
    try {
      await api.disconnectArm(armId);
      await mutate(SWR_KEY);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setActionLoading((prev) => ({ ...prev, [armId]: false }));
    }
  }

  async function handleDelete(armId: string) {
    if (!confirm(`Remove arm "${armId}"?`)) return;
    setActionLoading((prev) => ({ ...prev, [armId]: true }));
    try {
      await api.deleteArm(armId);
      await mutate(SWR_KEY);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove arm");
    } finally {
      setActionLoading((prev) => ({ ...prev, [armId]: false }));
    }
  }

  async function handleAdd() {
    if (!form.id || !form.name || !form.port) {
      setError("ID, name, and port are required");
      return;
    }
    try {
      await api.addArm(form);
      await mutate(SWR_KEY);
      setForm(EMPTY_FORM);
      setShowAdd(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add arm");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-text-primary">Arms</span>
          <span className="rounded-full bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
            {arms.length}
          </span>
        </div>
        <ActionButton
          variant="secondary"
          className="!px-2.5 !py-1 !text-[11px]"
          onClick={() => setShowAdd((s) => !s)}
        >
          {showAdd ? "Cancel" : "+ Add Arm"}
        </ActionButton>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md bg-status-error-bg px-3 py-2">
          <p className="text-[12px] text-status-error">{error}</p>
        </div>
      )}

      {/* Arm cards */}
      {arms.map((arm) => (
        <ArmCard
          key={arm.id}
          arm={arm}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onDelete={handleDelete}
          loading={actionLoading[arm.id] ?? false}
        />
      ))}

      {arms.length === 0 && !showAdd && (
        <p className="py-4 text-center text-[12px] text-text-tertiary">
          No arms configured. Click &quot;+ Add Arm&quot; to register one.
        </p>
      )}

      {/* Add arm form */}
      {showAdd && (
        <div className="rounded-lg border border-bg-tertiary bg-bg-elevated p-4">
          <h3 className="mb-3 text-[12px] font-semibold text-text-primary">New Arm</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL_CLASS}>ID</label>
              <input
                className={INPUT_CLASS}
                placeholder="follower_right"
                value={form.id}
                onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Name</label>
              <input
                className={INPUT_CLASS}
                placeholder="Follower Right"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Role</label>
              <select
                className={SELECT_CLASS}
                value={form.role}
                onChange={(e) =>
                  setForm((f) => ({ ...f, role: e.target.value as "leader" | "follower" }))
                }
              >
                <option value="leader">Leader</option>
                <option value="follower">Follower</option>
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Motor Type</label>
              <select
                className={SELECT_CLASS}
                value={form.motorType}
                onChange={(e) => setForm((f) => ({ ...f, motorType: e.target.value }))}
              >
                <option value="damiao">Damiao</option>
                <option value="dynamixel">Dynamixel</option>
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Port</label>
              <input
                className={INPUT_CLASS}
                placeholder="/dev/ttyUSB0 or can0"
                value={form.port}
                onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Structural Design</label>
              <select
                className={SELECT_CLASS}
                value={form.structuralDesign ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    structuralDesign: e.target.value || null,
                  }))
                }
              >
                <option value="">None</option>
                <option value="so100">SO-100</option>
                <option value="koch">Koch</option>
              </select>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <ActionButton variant="primary" className="!px-3 !py-1.5 !text-[12px]" onClick={handleAdd}>
              Add Arm
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  );
}
