"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import type { HardwareStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";

const INPUT_CLASS =
  "w-full rounded-md border border-bg-tertiary bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-signal focus:outline-none";
const SELECT_CLASS = `${INPUT_CLASS} appearance-none`;
const LABEL_CLASS = "text-[11px] font-medium text-text-secondary";
const SWR_KEY = "/hardware/status";

export function PairingsTab() {
  const { data } = useSWR<HardwareStatus>(SWR_KEY, api.getHardwareStatus, {
    refreshInterval: 5000,
  });
  const [showCreate, setShowCreate] = useState(false);
  const [leaderId, setLeaderId] = useState("");
  const [followerId, setFollowerId] = useState("");
  const [pairingName, setPairingName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const arms = data?.arms ?? [];
  const pairings = data?.pairings ?? [];
  const leaders = arms.filter((a) => a.role === "leader");
  const followers = arms.filter((a) => a.role === "follower");

  function armName(id: string) {
    return arms.find((a) => a.id === id)?.name ?? id;
  }

  /** Filter followers to those compatible with selected leader (matching structuralDesign). */
  function compatibleFollowers() {
    const leader = arms.find((a) => a.id === leaderId);
    if (!leader?.structuralDesign) return followers;
    return followers.filter(
      (f) => !f.structuralDesign || f.structuralDesign === leader.structuralDesign,
    );
  }

  async function handleCreate() {
    if (!leaderId || !followerId) {
      setError("Select both a leader and a follower");
      return;
    }
    const name = pairingName || `${armName(leaderId)} → ${armName(followerId)}`;
    try {
      await api.createPairing(leaderId, followerId, name);
      await mutate(SWR_KEY);
      setLeaderId("");
      setFollowerId("");
      setPairingName("");
      setShowCreate(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create pairing");
    }
  }

  async function handleRemove(lid: string, fid: string) {
    try {
      await api.removePairing(lid, fid);
      await mutate(SWR_KEY);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove pairing");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-text-primary">Pairings</span>
          <span className="rounded-full bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
            {pairings.length}
          </span>
        </div>
        <ActionButton
          variant="secondary"
          className="!px-2.5 !py-1 !text-[11px]"
          onClick={() => setShowCreate((s) => !s)}
        >
          {showCreate ? "Cancel" : "+ Create"}
        </ActionButton>
      </div>

      {error && (
        <div className="rounded-md bg-status-error-bg px-3 py-2">
          <p className="text-[12px] text-status-error">{error}</p>
        </div>
      )}

      {/* Pairing list */}
      {pairings.map((p) => (
        <div
          key={`${p.leaderId}-${p.followerId}`}
          className="flex items-center justify-between rounded-lg border border-bg-tertiary bg-bg-secondary p-3"
        >
          <div>
            <div className="text-[13px] font-medium text-text-primary">{p.name}</div>
            <div className="mt-0.5 text-[11px] text-text-tertiary">
              {armName(p.leaderId)} → {armName(p.followerId)}
            </div>
          </div>
          <button
            onClick={() => handleRemove(p.leaderId, p.followerId)}
            className="rounded-md p-1 text-text-tertiary transition-colors hover:bg-status-error-bg hover:text-status-error"
            title="Remove pairing"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      ))}

      {pairings.length === 0 && !showCreate && (
        <p className="py-4 text-center text-[12px] text-text-tertiary">
          No pairings. Create one to link a leader arm to a follower.
        </p>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="rounded-lg border border-bg-tertiary bg-bg-elevated p-4">
          <h3 className="mb-3 text-[12px] font-semibold text-text-primary">New Pairing</h3>
          <div className="flex flex-col gap-3">
            <div>
              <label className={LABEL_CLASS}>Leader</label>
              <select
                className={SELECT_CLASS}
                value={leaderId}
                onChange={(e) => setLeaderId(e.target.value)}
              >
                <option value="">Select leader...</option>
                {leaders.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Follower</label>
              <select
                className={SELECT_CLASS}
                value={followerId}
                onChange={(e) => setFollowerId(e.target.value)}
              >
                <option value="">Select follower...</option>
                {compatibleFollowers().map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Name (optional)</label>
              <input
                className={INPUT_CLASS}
                placeholder="Left Pair"
                value={pairingName}
                onChange={(e) => setPairingName(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <ActionButton variant="primary" className="!px-3 !py-1.5 !text-[12px]" onClick={handleCreate}>
                Create Pairing
              </ActionButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
