"use client";

import { useCallback, useState } from "react";
import useSWR, { mutate } from "swr";
import type { CameraConfig, CameraConfigPayload, CameraStatus, DiscoveredCamera } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";

const INPUT_CLASS =
  "w-full rounded-md border border-bg-tertiary bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-signal focus:outline-none";
const SELECT_CLASS = `${INPUT_CLASS} appearance-none`;
const LABEL_CLASS = "text-[11px] font-medium text-text-secondary";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const EMPTY_FORM: CameraConfigPayload = {
  key: "",
  cameraType: "opencv",
  indexOrPath: 0,
  width: 640,
  height: 480,
  fps: 30,
  serialNumberOrName: "",
  useDepth: false,
};

export function CamerasTab() {
  const { data: statusMap } = useSWR<Record<string, CameraStatus>>(
    "/cameras/status",
    api.getCameraStatus,
    { refreshInterval: 3000 },
  );
  const { data: configMap } = useSWR<Record<string, CameraConfig>>(
    "/cameras/config",
    api.getCameraConfig,
  );

  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<CameraConfigPayload>(EMPTY_FORM);
  const [scanResults, setScanResults] = useState<DiscoveredCamera[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cameraKeys = Object.keys(configMap ?? {});

  const revalidate = useCallback(async () => {
    await Promise.all([mutate("/cameras/status"), mutate("/cameras/config")]);
  }, []);

  async function handleScan() {
    setScanning(true);
    try {
      const results = await api.scanCameras();
      setScanResults(results);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  async function handleConnect(key: string) {
    try {
      await api.connectCamera(key);
      await revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect camera");
    }
  }

  async function handleDisconnect(key: string) {
    try {
      await api.disconnectCamera(key);
      await revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect camera");
    }
  }

  async function handleRemove(key: string) {
    if (!confirm(`Remove camera "${key}"?`)) return;
    try {
      await api.removeCameraConfig(key);
      await revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove camera");
    }
  }

  async function handleAdd() {
    if (!form.key) {
      setError("Camera key is required");
      return;
    }
    try {
      await api.updateCameraConfig(form);
      await revalidate();
      setForm(EMPTY_FORM);
      setShowAdd(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add camera");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-text-primary">Cameras</span>
          <span className="rounded-full bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
            {cameraKeys.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <ActionButton
            variant="ghost"
            className="!px-2.5 !py-1 !text-[11px]"
            onClick={handleScan}
            disabled={scanning}
          >
            {scanning ? "Scanning..." : "Scan"}
          </ActionButton>
          <ActionButton
            variant="secondary"
            className="!px-2.5 !py-1 !text-[11px]"
            onClick={() => setShowAdd((s) => !s)}
          >
            {showAdd ? "Cancel" : "+ Add"}
          </ActionButton>
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-status-error-bg px-3 py-2">
          <p className="text-[12px] text-status-error">{error}</p>
        </div>
      )}

      {/* Scan results */}
      {scanResults.length > 0 && (
        <div className="rounded-lg border border-bg-tertiary bg-bg-elevated p-3">
          <h4 className="mb-2 text-[11px] font-semibold text-text-secondary">Discovered Devices</h4>
          {scanResults.map((cam) => (
            <div key={cam.devicePath} className="flex items-center justify-between py-1.5">
              <div>
                <span className="text-[12px] text-text-primary">{cam.name}</span>
                <span className="ml-2 font-mono text-[11px] text-text-tertiary">
                  {cam.devicePath}
                </span>
              </div>
              <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-secondary">
                {cam.cameraType}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Camera cards */}
      {cameraKeys.map((key) => {
        const config = configMap?.[key];
        const status = statusMap?.[key];
        const isConnected = status?.connected ?? false;

        return (
          <div key={key} className="rounded-lg border border-bg-tertiary bg-bg-secondary p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-text-primary">{key}</span>
                <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold uppercase text-text-secondary">
                  {config?.type ?? "unknown"}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className={`h-1.5 w-1.5 rounded-full ${isConnected ? "bg-status-success" : "bg-text-tertiary"}`} />
                <span className="text-[10px] font-semibold uppercase text-text-secondary">
                  {isConnected ? "Connected" : "Off"}
                </span>
              </div>
            </div>

            {config && (
              <div className="mt-1 text-[11px] text-text-tertiary">
                {config.width}×{config.height} @ {config.fps}fps
              </div>
            )}

            {/* Snapshot preview */}
            {isConnected && (
              <div className="mt-2 overflow-hidden rounded-md bg-bg-tertiary">
                <img
                  src={`${BASE}/cameras/${key}/snapshot?t=${Date.now()}`}
                  alt={`Camera: ${key}`}
                  className="h-32 w-full object-cover"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
              </div>
            )}

            <div className="mt-2 flex items-center gap-1.5">
              {isConnected ? (
                <ActionButton
                  variant="secondary"
                  className="!px-2.5 !py-1 !text-[11px]"
                  onClick={() => handleDisconnect(key)}
                >
                  Disconnect
                </ActionButton>
              ) : (
                <ActionButton
                  variant="primary"
                  className="!px-2.5 !py-1 !text-[11px]"
                  onClick={() => handleConnect(key)}
                >
                  Connect
                </ActionButton>
              )}
              <button
                onClick={() => handleRemove(key)}
                disabled={isConnected}
                className="rounded-md p-1 text-text-tertiary transition-colors hover:bg-status-error-bg hover:text-status-error disabled:pointer-events-none disabled:opacity-50"
                title="Remove camera"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </div>
        );
      })}

      {cameraKeys.length === 0 && !showAdd && (
        <p className="py-4 text-center text-[12px] text-text-tertiary">
          No cameras configured. Scan for devices or add one manually.
        </p>
      )}

      {/* Add camera form */}
      {showAdd && (
        <div className="rounded-lg border border-bg-tertiary bg-bg-elevated p-4">
          <h3 className="mb-3 text-[12px] font-semibold text-text-primary">New Camera</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL_CLASS}>Key</label>
              <input
                className={INPUT_CLASS}
                placeholder="top_cam"
                value={form.key}
                onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Type</label>
              <select
                className={SELECT_CLASS}
                value={form.cameraType}
                onChange={(e) => setForm((f) => ({ ...f, cameraType: e.target.value }))}
              >
                <option value="opencv">OpenCV</option>
                <option value="intelrealsense">Intel RealSense</option>
              </select>
            </div>
            <div>
              <label className={LABEL_CLASS}>Index / Path</label>
              <input
                className={INPUT_CLASS}
                placeholder="0 or /dev/video0"
                value={form.indexOrPath}
                onChange={(e) => setForm((f) => ({ ...f, indexOrPath: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Serial / Name</label>
              <input
                className={INPUT_CLASS}
                placeholder="Optional"
                value={form.serialNumberOrName}
                onChange={(e) => setForm((f) => ({ ...f, serialNumberOrName: e.target.value }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Width</label>
              <input
                className={INPUT_CLASS}
                type="number"
                value={form.width}
                onChange={(e) => setForm((f) => ({ ...f, width: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Height</label>
              <input
                className={INPUT_CLASS}
                type="number"
                value={form.height}
                onChange={(e) => setForm((f) => ({ ...f, height: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>FPS</label>
              <input
                className={INPUT_CLASS}
                type="number"
                value={form.fps}
                onChange={(e) => setForm((f) => ({ ...f, fps: Number(e.target.value) }))}
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 pb-1.5">
                <input
                  type="checkbox"
                  checked={form.useDepth}
                  onChange={(e) => setForm((f) => ({ ...f, useDepth: e.target.checked }))}
                  className="rounded border-bg-tertiary"
                />
                <span className={LABEL_CLASS}>Use Depth</span>
              </label>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <ActionButton variant="primary" className="!px-3 !py-1.5 !text-[12px]" onClick={handleAdd}>
              Add Camera
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  );
}
