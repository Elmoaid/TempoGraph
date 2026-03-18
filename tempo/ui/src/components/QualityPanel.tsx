function ScoreBar({ label, score }: { label: string; score: number }) {
  const color = score >= 75 ? "var(--success)" : score >= 50 ? "var(--warning)" : "var(--error)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
      <span style={{ width: 90, fontSize: 11, color: "var(--text-secondary)", flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 4, background: "var(--bg-active)", borderRadius: 2 }}>
        <div style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 2, transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: 10, width: 28, textAlign: "right", color }}>{score}</span>
    </div>
  );
}

function parseQuality(output: string) {
  const overall = parseInt(output.match(/Quality Score:\s*(\d+)/)?.[1] || "0", 10);
  const parse = (n: string) => {
    const m = output.match(new RegExp(`${n}:\\s*(\\d+)/100\\s*\\((.+?)\\)`));
    return { score: parseInt(m?.[1] || "0", 10), label: m?.[2] || "" };
  };
  return { overall, minimality: parse("Minimality"), simplicity: parse("Simplicity"), independence: parse("Independence"), convention: parse("Convention") };
}

function scoreClass(n: number) { return n >= 75 ? "c-good" : n >= 50 ? "c-warn" : "c-bad"; }

interface Props {
  qualityOutput: string | null;
}

export function QualityPanel({ qualityOutput }: Props) {
  if (!qualityOutput) return null;
  const q = parseQuality(qualityOutput);
  return (
    <div className="cell" style={{ flex: "0 0 auto" }}>
      <div className="cell-head">
        Quality
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700 }} className={scoreClass(q.overall)}>{q.overall}/100</span>
      </div>
      <div className="cell-body">
        <ScoreBar label="Minimality" score={q.minimality.score} />
        <ScoreBar label="Simplicity" score={q.simplicity.score} />
        <ScoreBar label="Independence" score={q.independence.score} />
        <ScoreBar label="Convention" score={q.convention.score} />
      </div>
    </div>
  );
}
