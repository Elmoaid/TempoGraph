interface Props {
  config: Record<string, unknown>;
  isDirty: boolean;
  onUpdate: (key: string, val: unknown) => void;
  onSave: () => void;
}

export function SettingsPanel({ config, isDirty, onUpdate, onSave }: Props) {
  return (
    <div className="cell" style={{ flex: 1 }}>
      <div className="cell-head">
        Settings
        {isDirty && (
          <button className="btn" onClick={onSave} style={{ marginLeft: "auto", padding: "2px 8px", fontSize: 10 }}>Save</button>
        )}
      </div>
      <div className="cell-body">
        <div className="cfg-row">
          <span className="cfg-label">Max tokens</span>
          <input className="input" type="number" value={(config.max_tokens as number) || 4000} onChange={(e) => onUpdate("max_tokens", parseInt(e.target.value) || 4000)} style={{ width: 80, textAlign: "right" }} />
        </div>
        <div className="cfg-row">
          <span className="cfg-label">Token budget</span>
          <select className="input" value={(config.token_budget as string) || "auto"} onChange={(e) => onUpdate("token_budget", e.target.value)} style={{ width: 100 }}>
            <option value="auto">Auto</option>
            <option value="minimal">Minimal</option>
            <option value="standard">Standard</option>
            <option value="generous">Generous</option>
          </select>
        </div>
        <div className="cfg-row">
          <span className="cfg-label">Telemetry</span>
          <div className={`toggle ${config.telemetry !== false ? "on" : ""}`} onClick={() => onUpdate("telemetry", !(config.telemetry !== false))} />
        </div>
        <div className="cfg-row">
          <span className="cfg-label">Learning</span>
          <div className={`toggle ${config.learning !== false ? "on" : ""}`} onClick={() => onUpdate("learning", !(config.learning !== false))} />
        </div>
      </div>
    </div>
  );
}
