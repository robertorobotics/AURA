"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import type { AddToolPayload, ToolInfo, ToolPairingInfo, TriggerInfo } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";

const INPUT_CLASS =
  "w-full rounded-md border border-bg-tertiary bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-signal focus:outline-none";
const SELECT_CLASS = `${INPUT_CLASS} appearance-none`;
const LABEL_CLASS = "text-[11px] font-medium text-text-secondary";
const SECTION_HEADER = "text-[12px] font-semibold text-text-primary";

const EMPTY_TOOL: AddToolPayload = {
  id: "",
  name: "",
  motorType: "dynamixel",
  port: "",
  motorId: 1,
  toolType: "gripper",
  enabled: true,
};

export function ToolsTab() {
  const { data: tools } = useSWR<ToolInfo[]>("/tools", api.getTools, { refreshInterval: 5000 });
  const { data: triggers } = useSWR<TriggerInfo[]>("/triggers", api.getTriggers, { refreshInterval: 5000 });
  const { data: toolPairings } = useSWR<ToolPairingInfo[]>("/tool-pairings", api.getToolPairings);

  const [showToolForm, setShowToolForm] = useState(false);
  const [toolForm, setToolForm] = useState<AddToolPayload>(EMPTY_TOOL);
  const [pairingTrigger, setPairingTrigger] = useState("");
  const [pairingTool, setPairingTool] = useState("");
  const [pairingAction, setPairingAction] = useState("toggle");
  const [error, setError] = useState<string | null>(null);

  const toolList = tools ?? [];
  const triggerList = triggers ?? [];
  const pairingList = toolPairings ?? [];

  async function handleAddTool() {
    if (!toolForm.id || !toolForm.name || !toolForm.port) {
      setError("Tool ID, name, and port are required");
      return;
    }
    try {
      await api.addTool(toolForm);
      await mutate("/tools");
      setToolForm(EMPTY_TOOL);
      setShowToolForm(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add tool");
    }
  }

  async function handleDeleteTool(id: string) {
    try {
      await api.deleteTool(id);
      await mutate("/tools");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete tool");
    }
  }

  async function handleConnectTool(id: string) {
    try {
      await api.connectTool(id);
      await mutate("/tools");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect tool");
    }
  }

  async function handleDisconnectTool(id: string) {
    try {
      await api.disconnectTool(id);
      await mutate("/tools");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect tool");
    }
  }

  async function handleCreatePairing() {
    if (!pairingTrigger || !pairingTool) {
      setError("Select both a trigger and a tool");
      return;
    }
    try {
      await api.createToolPairing(pairingTrigger, pairingTool, pairingAction);
      await mutate("/tool-pairings");
      setPairingTrigger("");
      setPairingTool("");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create tool pairing");
    }
  }

  async function handleRemovePairing(triggerId: string, toolId: string) {
    try {
      await api.removeToolPairing(triggerId, toolId);
      await mutate("/tool-pairings");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove pairing");
    }
  }

  function triggerName(id: string) {
    return triggerList.find((t) => t.id === id)?.name ?? id;
  }

  function toolName(id: string) {
    return toolList.find((t) => t.id === id)?.name ?? id;
  }

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <div className="rounded-md bg-status-error-bg px-3 py-2">
          <p className="text-[12px] text-status-error">{error}</p>
        </div>
      )}

      {/* --- Tools section --- */}
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className={SECTION_HEADER}>Tools ({toolList.length})</h3>
          <ActionButton
            variant="secondary"
            className="!px-2.5 !py-1 !text-[11px]"
            onClick={() => setShowToolForm((s) => !s)}
          >
            {showToolForm ? "Cancel" : "+ Add"}
          </ActionButton>
        </div>

        {toolList.map((tool) => (
          <div key={tool.id} className="flex items-center justify-between rounded-lg border border-bg-tertiary bg-bg-secondary p-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-text-primary">{tool.name}</span>
                <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] uppercase text-text-secondary">
                  {tool.toolType}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-tertiary">
                <span>{tool.motorType}</span>
                <span className="font-mono">{tool.port}:{tool.motorId}</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <div className={`h-1.5 w-1.5 rounded-full ${tool.status === "connected" ? "bg-status-success" : "bg-text-tertiary"}`} />
              {tool.status === "connected" ? (
                <ActionButton variant="secondary" className="!px-2 !py-0.5 !text-[10px]" onClick={() => handleDisconnectTool(tool.id)}>
                  Disconnect
                </ActionButton>
              ) : (
                <ActionButton variant="primary" className="!px-2 !py-0.5 !text-[10px]" onClick={() => handleConnectTool(tool.id)}>
                  Connect
                </ActionButton>
              )}
              <button
                onClick={() => handleDeleteTool(tool.id)}
                className="rounded-md p-1 text-text-tertiary hover:bg-status-error-bg hover:text-status-error"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </div>
        ))}

        {toolList.length === 0 && !showToolForm && (
          <p className="py-2 text-center text-[11px] text-text-tertiary">No tools configured.</p>
        )}

        {showToolForm && (
          <div className="rounded-lg border border-bg-tertiary bg-bg-elevated p-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={LABEL_CLASS}>ID</label>
                <input className={INPUT_CLASS} placeholder="gripper_1" value={toolForm.id} onChange={(e) => setToolForm((f) => ({ ...f, id: e.target.value }))} />
              </div>
              <div>
                <label className={LABEL_CLASS}>Name</label>
                <input className={INPUT_CLASS} placeholder="Main Gripper" value={toolForm.name} onChange={(e) => setToolForm((f) => ({ ...f, name: e.target.value }))} />
              </div>
              <div>
                <label className={LABEL_CLASS}>Type</label>
                <select className={SELECT_CLASS} value={toolForm.toolType} onChange={(e) => setToolForm((f) => ({ ...f, toolType: e.target.value }))}>
                  <option value="gripper">Gripper</option>
                  <option value="screwdriver">Screwdriver</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <div>
                <label className={LABEL_CLASS}>Motor Type</label>
                <select className={SELECT_CLASS} value={toolForm.motorType} onChange={(e) => setToolForm((f) => ({ ...f, motorType: e.target.value }))}>
                  <option value="dynamixel">Dynamixel</option>
                  <option value="damiao">Damiao</option>
                </select>
              </div>
              <div>
                <label className={LABEL_CLASS}>Port</label>
                <input className={INPUT_CLASS} placeholder="/dev/ttyUSB0" value={toolForm.port} onChange={(e) => setToolForm((f) => ({ ...f, port: e.target.value }))} />
              </div>
              <div>
                <label className={LABEL_CLASS}>Motor ID</label>
                <input className={INPUT_CLASS} type="number" value={toolForm.motorId} onChange={(e) => setToolForm((f) => ({ ...f, motorId: Number(e.target.value) }))} />
              </div>
            </div>
            <div className="mt-2 flex justify-end">
              <ActionButton variant="primary" className="!px-3 !py-1 !text-[11px]" onClick={handleAddTool}>Add Tool</ActionButton>
            </div>
          </div>
        )}
      </section>

      {/* --- Triggers section --- */}
      <section className="flex flex-col gap-2">
        <h3 className={SECTION_HEADER}>Triggers ({triggerList.length})</h3>
        {triggerList.map((t) => (
          <div key={t.id} className="flex items-center justify-between rounded-lg border border-bg-tertiary bg-bg-secondary px-3 py-2">
            <div className="text-[12px]">
              <span className="font-medium text-text-primary">{t.name}</span>
              <span className="ml-2 text-text-tertiary">{t.triggerType} · pin {t.pin}</span>
            </div>
            <button
              onClick={() => { api.deleteTrigger(t.id).then(() => mutate("/triggers")); }}
              className="rounded-md p-1 text-text-tertiary hover:bg-status-error-bg hover:text-status-error"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        ))}
        {triggerList.length === 0 && (
          <p className="py-2 text-center text-[11px] text-text-tertiary">No triggers configured.</p>
        )}
      </section>

      {/* --- Tool Pairings section --- */}
      <section className="flex flex-col gap-2">
        <h3 className={SECTION_HEADER}>Tool Pairings ({pairingList.length})</h3>
        {pairingList.map((p) => (
          <div key={`${p.triggerId}-${p.toolId}`} className="flex items-center justify-between rounded-lg border border-bg-tertiary bg-bg-secondary px-3 py-2">
            <div className="text-[12px]">
              <span className="text-text-primary">{triggerName(p.triggerId)}</span>
              <span className="mx-1.5 text-text-tertiary">→</span>
              <span className="text-text-primary">{toolName(p.toolId)}</span>
              <span className="ml-2 text-text-tertiary">({p.action})</span>
            </div>
            <button
              onClick={() => handleRemovePairing(p.triggerId, p.toolId)}
              className="rounded-md p-1 text-text-tertiary hover:bg-status-error-bg hover:text-status-error"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        ))}

        {/* Create pairing inline */}
        {triggerList.length > 0 && toolList.length > 0 && (
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className={LABEL_CLASS}>Trigger</label>
              <select className={SELECT_CLASS} value={pairingTrigger} onChange={(e) => setPairingTrigger(e.target.value)}>
                <option value="">Select...</option>
                {triggerList.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <div className="flex-1">
              <label className={LABEL_CLASS}>Tool</label>
              <select className={SELECT_CLASS} value={pairingTool} onChange={(e) => setPairingTool(e.target.value)}>
                <option value="">Select...</option>
                {toolList.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <div className="w-24">
              <label className={LABEL_CLASS}>Action</label>
              <select className={SELECT_CLASS} value={pairingAction} onChange={(e) => setPairingAction(e.target.value)}>
                <option value="toggle">Toggle</option>
                <option value="momentary">Momentary</option>
              </select>
            </div>
            <ActionButton variant="primary" className="!px-2.5 !py-1.5 !text-[11px]" onClick={handleCreatePairing}>
              Link
            </ActionButton>
          </div>
        )}

        {pairingList.length === 0 && (triggerList.length === 0 || toolList.length === 0) && (
          <p className="py-2 text-center text-[11px] text-text-tertiary">
            Add tools and triggers first to create pairings.
          </p>
        )}
      </section>
    </div>
  );
}
