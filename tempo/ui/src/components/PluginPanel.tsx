export interface PluginInfo { name: string; enabled: boolean; description: string; }

interface Props {
  plugins: PluginInfo[];
  onToggle: (name: string, enabled: boolean) => void;
  loading: boolean;
}

export function PluginPanel({ plugins, onToggle, loading }: Props) {
  return (
    <div className="cell" style={{ flex: "0 0 auto" }}>
      <div className="cell-head">Plugins ({plugins.length})</div>
      <div className="cell-body">
        {plugins.map((p) => (
          <div key={p.name} className="plugin-row">
            <div className={`toggle ${p.enabled ? "on" : ""}`} onClick={() => onToggle(p.name, p.enabled)} />
            <span className="plugin-name">{p.name}</span>
            <span className="plugin-desc" title={p.description}>{p.description}</span>
          </div>
        ))}
        {plugins.length === 0 && (
          <div style={{ color: "var(--text-tertiary)", fontSize: 11 }}>{loading ? "Loading..." : "No plugins"}</div>
        )}
      </div>
    </div>
  );
}
