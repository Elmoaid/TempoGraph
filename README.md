# tempograph

Your codebase is a living thing. Every commit reshapes it — new functions appear, old ones decay, dependencies tangle and untangle. Most tools show you code as it is right now. Tempograph shows you how it got here and where it's headed.

Tempograph parses source files with [tree-sitter](https://tree-sitter.github.io/), extracts every symbol and relationship, and builds a semantic graph — a structural snapshot of your entire codebase at a point in time. Each snapshot captures what exists, what connects to what, and what's drifting toward trouble. Run it again after changes and only the delta is recomputed.

## How It Works

```
commit a1b2c3 ──→ snapshot ──→ 847 symbols, 2,031 edges
commit d4e5f6 ──→ snapshot ──→ 851 symbols, 2,044 edges  (+4 symbols, +13 edges)
commit g7h8i9 ──→ snapshot ──→ 849 symbols, 2,067 edges  (-2 symbols, +23 edges ← coupling growing)
```

Each snapshot is a content-hashed graph stored in `.tempograph/cache.json`. Only files that actually changed are re-parsed — a 10,000-file repo re-indexes in seconds, not minutes. The cache is keyed by file content, not timestamps, so switching branches and coming back doesn't trigger a full rebuild.

## Supported Languages

Python · TypeScript · TSX · JavaScript · JSX · Rust · Go

Tree-sitter grammars handle the parsing. Each language has dedicated handlers for extracting functions, classes, components, hooks, imports, type aliases, traits, interfaces, and their relationships. The parser (`parser.py`) has ~47 extraction methods across all supported languages.

## Install

```bash
pip install -e .
```

Requires Python 3.11+. Dependencies: `tree-sitter`, language grammars, `tiktoken` (token counting), `mcp[cli]` (MCP server).

## CLI

```bash
tempograph <path> --mode <mode> [options]
```

Global options:
- `--query` / `-q` — Search query (for `focus` and `lookup` modes)
- `--file` / `-f` — File path (for `blast` mode), or comma-separated paths (for `diff` mode)
- `--max-tokens` — Token budget for output (default: 4000, affects `focus` and `diff`)
- `--json` — Dump the raw graph as JSON instead of rendering
- `--tokens` — Print token count to stderr after output

Every mode first builds the graph (or loads from cache), then renders. Build time prints to stderr; output prints to stdout.

---

### `overview`

**What it does:** Orients you in a codebase you've never seen. Shows size, languages, entry points, key files ranked by size + complexity, and module structure.

**Input:** Just a repo path. No extra args.

**Output:**
```
repo: my-project
249 files, 3830 symbols, 42,891 lines | TypeScript(187), Rust(31), CSS(12)

entry points:
  src/main.tsx
  src-tauri/src/main.rs

key files (by size + complexity):
  src/components/Canvas.tsx (17,631L, cx=847, TypeScript)
  src/components/Scratchpad.tsx (24,158L, cx=1203, TypeScript)
  src-tauri/src/lib.rs (672L, cx=89, Rust)

structure: src/(187), src-tauri/(31), public/(3)
```

**Under the hood:** Scans all `FileInfo` objects, computes a score per file (`line_count + complexity * 3`), finds entry points by looking for `main` functions and common entry patterns. No graph traversal needed — pure stats.

```bash
tempograph ./my-project --mode overview
```

---

### `map`

**What it does:** File tree with top symbols per file. Like `tree` but it shows you what's *inside* each file — the top 8 symbols sorted by importance (components > classes > exported functions > internal functions).

**Input:** Repo path only.

**Output:**
```
[src/components/]
  Canvas.tsx (17631 lines, 142 sym)
    comp Canvas (L45-17631) — Canvas(): JSX.Element
    func handleKeyDown (L892-1204)
    func handleCommand (L1205-1890)
    ... +139 more

[src/lib/]
  db.ts (312 lines, 18 sym)
    func initDatabase (L12-89) — initDatabase(): Promise<void>
    func loadSettings (L91-145)
```

**Under the hood:** Groups files by directory, then for each file retrieves its symbols from the graph and sorts them by a priority key: components/hooks first, then classes/structs, then exported functions, then everything else. Shows line ranges and signatures where available.

```bash
tempograph ./my-project --mode map
```

---

### `symbols`

**What it does:** Complete symbol index. Every function, class, component, hook, variable, type — with signatures, docstrings, line locations, and caller/callee relationships.

**Input:** Repo path only.

**Output:**
```
── src/lib/db.ts ──
  function initDatabase | L12-89 | initDatabase(): Promise<void> | ← main, App | → loadSettings, migrateSchema
  function loadSettings | L91-145 | loadSettings(db: Database): Settings | ← initDatabase
  function saveSetting | L147-162 | saveSetting(key: string, value: string) | ← SettingsPanel, handleCommand
```

**Under the hood:** Iterates every symbol in the graph, groups by file, and for each symbol queries `callers_of()` and `callees_of()` to show the call graph inline. Signatures are truncated at 120 chars, docstrings at 80.

```bash
tempograph ./my-project --mode symbols
```

---

### `focus`

**What it does:** Given a search query, finds matching symbols and then does a **breadth-first traversal** of the call graph to build a connected subgraph of everything relevant to that topic. This is the mode you use when you're about to work on something and need context.

**Input:** `--query "authentication"` (or any search term — function names, module names, concepts).

**Output:**
```
Focus: authentication

● function handleLogin — src/auth/login.ts:45-120
  sig: handleLogin(credentials: Credentials): Promise<Session>
  called by: LoginForm.onSubmit, AuthProvider.refresh
  calls: validateCredentials, createSession, setToken
  contains: func validateEmail, func hashPassword

  → function validateCredentials — src/auth/validators.ts:12-67
  → function createSession — src/auth/session.ts:23-89
    · function setToken — src/lib/storage.ts:34-41

Related files:
  src/auth/middleware.ts (234 lines)
  src/auth/types.ts (45 lines)
```

**Under the hood:**
1. Fuzzy-searches the symbol index for your query (top 10 seed matches)
2. BFS expansion: for each seed, follows callers (who calls this?), callees (what does this call?), and children (what's inside?) up to depth 2
3. Caps at 40 symbols to keep output manageable
4. Token-budgets the output (default 4000 tokens) — truncates when the budget is hit
5. Appends related files that appeared in edges but weren't shown (with `[grep-only]` warnings for files >500 lines)

```bash
tempograph ./my-project --mode focus --query "payment processing"
```

---

### `lookup`

**What it does:** Answers natural-language questions about the codebase by pattern-matching the question type and querying the graph accordingly. Not AI — it's structured query dispatch.

**Input:** `--query "where is handleLogin defined?"` or `--query "what calls saveDocument?"` or `--query "who imports db.ts?"`

**Recognized question patterns:**
| Pattern | What it does |
|---------|-------------|
| "where is X" / "find X" / "locate X" | Exact + fuzzy symbol search, shows locations and callers |
| "what calls X" / "who uses X" | Lists all callers of a symbol with file:line locations |
| "what does X call" / "dependencies of X" | Lists all callees of a symbol |
| "who imports X" | Lists all files that import a given file |
| "what renders X" | Lists components that render a given component (JSX/TSX) |
| *(anything else)* | Falls back to fuzzy symbol search |

**Output (example: "what calls saveDocument"):**
```
'saveDocument' is called by:
  src/components/Scratchpad.tsx:1204 — handleCommand
  src/scratchpad/hooks/useAutoSave.ts:34 — useAutoSave
  src/lib/docBridge.ts:78 — syncToCloud
```

```bash
tempograph ./my-project --mode lookup --query "what calls saveDocument"
```

---

### `blast`

**What it does:** Shows the blast radius of a file — everything that would be affected if you modify it. Three layers: direct importers, externally-called symbols (which specific functions are used by other files), and component render relationships.

**Input:** `--file src/lib/db.ts` (path relative to repo root).

**Output:**
```
Blast radius for src/lib/db.ts:

Directly imported by (7):
  src/components/Canvas.tsx
  src/components/Scratchpad.tsx
  src/lib/settings.ts
  ...

Externally called symbols:
  initDatabase:
    src/main.tsx:12
    src/lib/settings.ts:34
  saveSetting:
    src/components/SettingsPanel.tsx:89
    src/components/Scratchpad.tsx:1204

Component render relationships:
  (none — this is a utility file)
```

If no external dependencies are found, it tells you: `"No external dependencies found — safe to modify in isolation."`

**Under the hood:** For each symbol in the target file, queries `callers_of()` and filters to only external callers (different file). Also checks `importers_of()` for the file itself, and `renderers_of()` for component relationships.

```bash
tempograph ./my-project --mode blast --file src/lib/db.ts
```

---

### `diff`

**What it does:** Given a list of changed files, renders everything you need to review: what symbols are affected, which exported symbols have external callers (breaking change risk), which files import the changed code, and component tree impact.

**Input:** `--file src/lib/db.ts,src/lib/settings.ts` (comma-separated file paths).

**Output:**
```
Diff context for 2 changed file(s):

Changed files:
  src/lib/db.ts (312 lines, 18 symbols)
  src/lib/settings.ts (145 lines, 8 symbols)

EXTERNAL DEPENDENCIES (breaking change risk):
  function initDatabase (src/lib/db.ts:12)
    <- main (src/main.tsx:5)
    <- App (src/App.tsx:23)

Files importing changed code (4):
  src/components/Canvas.tsx
  src/components/Scratchpad.tsx
  src/components/SettingsPanel.tsx
  src/main.tsx

Key symbols in changed files:
  function initDatabase L12-89
    initDatabase(): Promise<void>
  function loadSettings L91-145
    loadSettings(db: Database): Settings
```

**Under the hood:** Normalizes file paths (handles partial matches), collects all symbols in changed files, identifies exported symbols with external callers as "breaking change risk", finds all importers of changed files, checks component render tree impact, then renders key symbols with signatures until the token budget (default 6000) runs out.

```bash
tempograph ./my-project --mode diff --file src/lib/db.ts,src/lib/settings.ts
```

---

### `hotspots`

**What it does:** Ranks every symbol by a risk score combining coupling, complexity, size, and cross-file dependencies. The top 20 are the places where bugs are most likely to hide and changes are most likely to break things.

**Input:** Repo path only.

**Output:**
```
Top 20 hotspots (highest coupling + complexity):

 1. component Canvas [risk=847] (src/components/Canvas.tsx:45)
    23 callers (12 cross-file), 45 callees, 18 children, 17631 lines, cx=312
    → grep-only (too large to read); high blast radius — changes here break many files

 2. component Scratchpad [risk=623] (src/components/Scratchpad.tsx:38)
    8 callers (5 cross-file), 67 callees, 24 children, 24158 lines, cx=445
    → grep-only (too large to read); refactor candidate — extreme complexity

 3. function handleCommand [risk=234] (src/components/Canvas.tsx:1205)
    12 callers (4 cross-file), 34 callees, 0 children, 685 lines, cx=89
    → consider splitting — complex and large
```

**Scoring formula:**
- `callers × 3` (who depends on this)
- `callees × 1.5` (what this depends on)
- `min(line_count / 10, 50)` (size, capped)
- `children × 2` (internal complexity)
- `cross_file_callers × 5` (blast radius)
- `render_count × 2` (component tree coupling)
- `log₂(cyclomatic_complexity) × 3` (branching complexity)

Actionable warnings are appended: "grep-only" for >500 lines, "high blast radius" for >5 cross-file callers, "refactor candidate" for extreme complexity.

```bash
tempograph ./my-project --mode hotspots
```

---

### `deps`

**What it does:** Analyzes the import graph for circular dependencies and computes dependency layers (topological sort). Layer 0 files depend on nothing; layer N files depend only on layers 0 through N-1.

**Input:** Repo path only.

**Output:**
```
Dependency Analysis:

CIRCULAR IMPORTS (2 cycles):
  1. db.ts → settings.ts → db.ts
  2. Canvas.tsx → shortcuts.ts → Canvas.tsx

Dependency layers (5 levels):
  Layer 0: types.ts, constants.ts, crypto.ts
  Layer 1: db.ts, settings.ts, tauri.ts
  Layer 2: profiles.ts, ai.ts, pipelines.ts
  Layer 3: Canvas.tsx, Scratchpad.tsx, CommandPalette.tsx ... +12 more (15 total)
  Layer 4: App.tsx, main.tsx
```

**Under the hood:** Builds a directed graph of file-level imports, runs cycle detection, then computes a topological ordering into layers. Files in the same layer have no dependencies on each other.

```bash
tempograph ./my-project --mode deps
```

---

### `dead`

**What it does:** Finds exported symbols that are never referenced by any other symbol in the codebase. Sorted by size (biggest dead code first = most cleanup value).

**Input:** Repo path only.

**Output:**
```
Potential dead code (23 symbols, showing top 23 by size):

src/components/GraphView.tsx:
  component GraphView (L1-342, 342 lines)

src/lib/formulaEngine.ts:
  function evaluateFormula (L45-189, 144 lines)
  function parseExpression (L191-267, 76 lines)

src/components/OutputInspector.tsx:
  component OutputInspector (L1-156, 156 lines)

Total: 23 unused symbols (~1,847 lines shown)
Note: decorator-dispatched symbols (@mcp.tool, @app.route, etc.) may be false positives.
```

**Under the hood:** Calls `graph.find_dead_code()` which checks every exported symbol for incoming edges (calls, renders, imports). If a symbol is exported but nothing references it, it's flagged. Groups by file, sorts by line count descending. Warns about false positives for decorator-dispatched patterns (route handlers, MCP tools, etc.).

```bash
tempograph ./my-project --mode dead
```

---

### `arch`

**What it does:** Groups files into modules (top-level directories), shows each module's size/language/exports, then maps inter-module dependencies (both import edges and call/render edges).

**Input:** Repo path only.

**Output:**
```
Architecture Overview:

Modules:
  src/ — 187 files, 3201 symbols, 38,441 lines [TypeScript]
    exports: Canvas(component), Scratchpad(component), App(component), initDatabase(function), buildGraph(function) +42
  src-tauri/ — 31 files, 489 symbols, 4,200 lines [Rust]
    exports: main(function), http_fetch(function), type_text(function) +18

Module dependencies:
  src → src-tauri(47)
  src-tauri → src(0)
```

**Under the hood:** Groups files by their first path segment. Builds two maps: import edges between modules and call/render edges between modules. Merges them into a single dependency count. Identifies top exported symbols per module.

```bash
tempograph ./my-project --mode arch
```

---

### `stats`

**What it does:** Raw numbers plus token cost estimates for each mode. Useful for understanding how much context each mode would consume if fed to an LLM.

**Input:** Repo path only.

**Output:**
```
Build: 0.3s
Files: 249, Symbols: 3830, Edges: 8241
Lines: 42,891

Token costs:
  overview:  342
  map:       2,847
  symbols:   ~57,450 (est)
  focused:   ~2,000-4,000 (query-dep)
  lookup:    ~100-500 (question-dep)
```

**Under the hood:** Runs `render_overview` and `render_map` to get actual token counts via tiktoken. Estimates symbol mode cost at ~15 tokens per symbol. Focus and lookup are query-dependent so it shows ranges.

```bash
tempograph ./my-project --mode stats
```

---

## MCP Server

Tempograph ships an MCP server that gives AI agents structural awareness of your codebase. Instead of pattern-matching over raw text, agents can query the actual dependency graph.

```bash
tempograph-server
```

| Tool | Input | Output |
|------|-------|--------|
| `index_repo` | `repo_path` (string) | Builds graph, returns stats (file/symbol/edge counts) |
| `overview` | `repo_path` | Same as CLI `overview` mode |
| `focus` | `repo_path`, `query` | Same as CLI `focus` mode — BFS subgraph for the query |
| `hotspots` | `repo_path` | Same as CLI `hotspots` mode — ranked risk list |
| `blast_radius` | `repo_path`, `file_path` | Same as CLI `blast` mode — importers, callers, renderers |
| `diff_context` | `repo_path` | Auto-detects changed files via `git diff`, renders full context |
| `dead_code` | `repo_path` | Same as CLI `dead` mode — unreferenced exported symbols |

Add to your Claude settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "tempograph": {
      "command": "tempograph-server",
      "args": []
    }
  }
}
```

## Python API

```python
from tempograph import build_graph, CodeGraph

graph: CodeGraph = build_graph("./my-project")

# All symbols
for sym in graph.symbols.values():
    print(f"{sym.kind.value} {sym.qualified_name} ({sym.file_path}:{sym.line_start})")

# Call graph
for sym in graph.symbols.values():
    callers = graph.callers_of(sym.id)
    callees = graph.callees_of(sym.id)
    if callers or callees:
        print(f"{sym.name}: {len(callers)} callers, {len(callees)} callees")

# Edges (calls, imports, inherits, renders)
for edge in graph.edges:
    print(f"{edge.source_id} --{edge.kind.value}--> {edge.target_id}")
```

Key `CodeGraph` methods:
- `graph.search_symbols(query)` — fuzzy search by name
- `graph.find_symbol(name)` — exact match
- `graph.callers_of(symbol_id)` — who calls this symbol
- `graph.callees_of(symbol_id)` — what does this symbol call
- `graph.children_of(symbol_id)` — nested symbols (methods inside a class, etc.)
- `graph.renderers_of(symbol_id)` — components that render this component
- `graph.importers_of(file_path)` — files that import this file
- `graph.detect_circular_imports()` — find import cycles
- `graph.dependency_layers()` — topological layer sort
- `graph.find_dead_code()` — exported symbols with no incoming references

## Incremental by Default

Tempograph hashes file contents, not modification times. The cache (`.tempograph/cache.json`) maps each file's content hash to its parsed symbols and edges. On re-index:

1. Hash every file in the repo
2. Skip files whose hash matches the cache
3. Re-parse only what actually changed
4. Merge results into the full graph

Switch branches, rebase, cherry-pick — if the bytes haven't changed, the work isn't repeated.

## License

MIT
