# MayaMCP Handoff Notes

This file is the current handoff for the next AI thread. Treat the worktree,
Maya scene, and artifacts as authoritative; older chat context is useful but
less reliable than current files and command output.

## Current Task

Long-running goal: use the process of building a highly accurate Coca-Cola
bottle exterior in Maya to improve MayaMCP with generic artist-style modeling
tools only.

Hard constraints:

- Do not add Coke-specific tools, workflows, presets, or hidden shortcuts.
- Any MCP source changes must be generic pipeline/modeling capability.
- Prefer Maya artist operations: component, face, edge, vertex, loop, UV,
  normals, support loops, merge/weld, direct coordinate edits.
- Avoid restarting from scratch. Continue refining the current saved scene.
- Validate from front plus at least one off-front angle before accepting a
  shape edit.
- Commit and push only source/docs/tests for generic MCP functionality. Do not
  commit generated Maya scenes, images, previews, or artifact JSON unless the
  user explicitly asks.

## Repo State

- Workspace: `F:/Codex134NewWorkspace/MayaMCP`
- Branch: `codex/mayamcp-dev`
- Remote tracking branch: `fork/codex/mayamcp-dev`
- Latest pushed commit at handoff: `3e7e9f4`
- Latest commit message: `Harden result compaction and cache fallback tests`
- `git status --short --branch --untracked-files=no` was clean at handoff.
- There are many untracked historical `.png`, `.json`, `.ma`, and turntable
  artifacts in the repo root. They are intentionally untracked. Use
  `--untracked-files=no` when checking source cleanliness.

Recent generic-tool/source commits to know:

- `3e7e9f4` - hardened result compaction and cache fallback tests.
- `1e2ea61` - `inspect_mesh_rings_by_axis` reports matched targets and
  distances.
- `e70b22d` - improved Maya-side tool cache diagnostics.
- `efbf051` - added generic `split_mesh_edges` support.

Static validation after `3e7e9f4`:

- `.venv/Scripts/python.exe -m pytest`
- Result: `31 passed, 4 skipped`

Live validation after `3e7e9f4`:

- `.venv/Scripts/maya-mcp.exe doctor --live`
- Result then: ok, `106` tools, `0` contract issues, cache writable.
- `MAYA_MCP_LIVE=1 python -m pytest -m live_maya -rs`
- Result then: `3 passed, 1 skipped`; audit scene test skipped because the
  Maya scene was dirty at that moment.

At this handoff moment, Maya commandPort was not reachable:

- Effective attempted config: `127.0.0.1:50007`, `source_type=mel`
- Error: connection refused.
- Likely cause: Maya is closed or commandPort is not open.

Recommended Maya commandPort for the next run:

```mel
commandPort -name ":50009" -sourceType "python" -bufferSize 4096 -outputVar "_mcp_maya_results";
```

Recommended MCP env when using that port:

```powershell
$env:MAYA_MCP_COMMAND_PORT="50009"
$env:MAYA_MCP_COMMAND_SOURCE_TYPE="python"
```

Then run:

```powershell
.venv\Scripts\maya-mcp.exe doctor --live
```

## Current Bottle Scene

Main scene to resume:

```text
F:/Codex134NewWorkspace/MayaMCP/mayamcp_artist_mesh_coke_bottle_v1.ma
```

Last verified after v204 modeling pass:

- Scene saved successfully.
- Maya dirty flag was `false`.
- No temporary duplicate/probe transforms remained.

Important target objects:

- `artist_mesh_coke_bottle_body`
- `artist_mesh_ridged_red_cap`
- `artist_mesh_neck_tamper_thread_ring`
- `artist_mesh_label_bottom_raised_edge`
- `artist_mesh_label_top_raised_edge`

Official front reference image:

```text
F:/Codex134NewWorkspace/MayaMCP/reference_coca_cola_original_20oz_official.jpg
```

Latest modeling artifacts:

```text
F:/Codex134NewWorkspace/MayaMCP/.maya_mcp_artifacts/v204_artist_component_refine/
```

Most important files there:

- `v204_final_summary.json`
- `v204_final_front_compare.json`
- `v204_final_front_compare.png`
- `v204_final_front_silhouette.png`
- `v204_final_side_delta_compare.json`
- `v204_final_threequarter_delta_compare.json`
- `v204_final_quality.json`
- `v204_ab_front_summary.json`
- `v204_side_threequarter_delta_summary.json`

## Latest v204 Modeling Pass

The accepted variant was `v204a_top_neck_expand`.

What was applied to original scene objects:

- `artist_mesh_ridged_red_cap`
  - y `7.094400062561025`, radius offset `+0.006`
  - y `6.6160000801086305`, radius offset `+0.004`
- `artist_mesh_coke_bottle_body`
  - y `6.59499979019165`, radius offset `+0.004`
  - y `6.5`, radius offset `+0.004`
  - y `6.300000190734863`, radius offset `+0.002`
- `artist_mesh_neck_tamper_thread_ring`
  - y `6.439999771118166`, radius offset `+0.003`
  - y `6.379999828338623`, radius offset `+0.002`

Tool used:

- `transform_mesh_rings_by_axis`
- Settings: `axis="y"`, `center=[0,0,0]`, `group_tolerance=0.002`,
  `target_tolerance=0.18`, `radius_stat="median"`,
  `preserve_radius_variation=True`, `select_result=False`

Applied vertex counts:

- Body: `288`
- Cap: `192`
- Neck thread ring: `192`

Front silhouette metrics after v204:

- IoU: `0.9865717873587275`
- Precision: `0.9918695081304919`
- Recall: `0.9946153067080787`
- Mean absolute width error: `0.00482177734375`
- Max absolute width error: `0.04296875`
- Aspect error: `0.00212393803098454`

Before v204 baseline from the same run:

- IoU: `0.986487391580992`
- Mean absolute width error: `0.0050048828125`
- Recall: `0.9944802673778738`

Off-front validation:

- Side delta IoU vs pre-v204 side: `0.9995977608688366`
- Side delta mean width error: `0.000244140625`
- Three-quarter delta IoU vs pre-v204 three-quarter:
  `0.9996790703173826`
- Three-quarter delta mean width error: `0.0001220703125`

Quality after v204:

- Body: no border edges, nonmanifold, lamina, invalid, short edges, zero-area,
  zero-UV-area, isolated, or high-valence issues.
- Body still has existing topology debt: `2` ngons, `20` triangles,
  `152` skinny faces.
- Cap: clean except `2` ngons.
- Neck ring and label edge bands have `192` border edges because they are open
  raised rings; otherwise clean.

Important metric caveat:

- `max_abs_width_error` is currently dominated by very top/bottom boundary row
  samples. Do not blindly optimize only that number. Use row-to-component
  mapping and off-front checks before applying edits.

## Current Remaining Shape Errors

Latest final front row samples from `v204_final_front_compare.json`:

- row `0.953033`, signed `-0.04296875`: bottom/contact boundary, noisy but
  still worth inspecting carefully.
- row `0.046967`, signed `-0.01953125`: cap/top edge appears narrow.
- row `0.348337`, signed `-0.01171875`: mid/upper body appears narrow.
- row `0.587084`, signed `+0.01171875`: label lower edge/body appears wide.
- row `0.618395`, signed `-0.01171875`: below label appears narrow.
- row `0.667319`, signed `-0.01171875`: waist/lower mid appears narrow.
- row `0.729941`, signed `+0.01171875`: lower body appears wide.
- row `0.285714`, signed `+0.0078125`: upper body/shoulder appears wide.
- row `0.810176`, signed `+0.0078125`: lower body appears wide.
- row `0.919765`, signed `-0.0078125`: bottom upper transition appears
  narrow.
- row `0.937378`, signed `+0.0078125`: adjacent bottom transition appears
  wide.

Suggested next modeling pass:

1. Reopen Maya and verify commandPort.
2. Confirm the scene opens cleanly and the five target objects exist.
3. Re-run `map_silhouette_errors_to_components` on
   `v204_final_front_compare.json` rows using the fresh playblast framing.
4. Do not globally scale the bottle. Work row-by-row or component-by-component.
5. Candidate next A/B should probably focus on:
   - cap top row around normalized `0.046967`,
   - mid/upper body around normalized `0.348337`,
   - lower label/waist rows around normalized `0.587-0.729`,
   - bottom transition only after careful off-front validation.
6. Use duplicate objects for A/B, delete them, and only apply the winning edit
   to originals after front + side/three-quarter checks.

## Useful Commands

Install/dev:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\maya-mcp.exe doctor --json
.venv\Scripts\maya-mcp.exe doctor --live
.venv\Scripts\maya-mcp.exe tools --brief --category object
.venv\Scripts\maya-mcp.exe tools search "uv face"
.venv\Scripts\maya-mcp.exe docs tools --check
```

Run live tests when Maya is open and the current scene can be temporarily
replaced:

```powershell
$env:MAYA_MCP_LIVE="1"
.venv\Scripts\python.exe -m pytest -m live_maya -rs
```

If the current Maya scene is dirty, live audit tests may skip by design rather
than overwrite the user's scene.

## Tooling Notes

Generic capabilities already available and important for the next thread:

- `audit_scene_strings`: generic scene string/name/path audit.
- `inspect_mesh_rings_by_axis`: finds coordinate-clustered vertex rows and now
  reports matched target coordinates.
- `transform_mesh_rings_by_axis`: artist-style loop/ring radius edits.
- `map_silhouette_errors_to_components`: maps visual silhouette row errors
  back to mesh vertices/edges and suggested side moves.
- `inspect_mesh_quality`: topology QA after edits.
- `split_mesh_edges`: generic edge split support.
- `move_mesh_components`, `transform_mesh_components`,
  `soft_transform_mesh_components`: direct component-level editing.
- `edit_mesh_topology`, `edit_mesh_weld`, `edit_mesh_normals`,
  `edit_uv_components`, `edit_uv_shells`, `edit_uv_topology`: relevant if the
  next pass exposes topology/UV/normal gaps.

Server/runtime capabilities to preserve:

- `MayaConnection.call_tool(...)` uses Maya-side tool caching unless
  `MAYA_MCP_DISABLE_TOOL_CACHE=1`.
- Oversized results are compacted by `mayatools.common.results.compact_result`.
- Full oversized JSON is written under `.maya_mcp_artifacts/results/`.
- `MAYA_MCP_RESULT_MAX_BYTES=0` disables result compaction.
- Prefer `50009/python` commandPort for lower MEL wrapping overhead, but
  `50007/mel` compatibility still works.

## Git Hygiene

- Use `git status --short --branch --untracked-files=no` for source status.
- Do not stage generated artifacts, previews, `.ma` files, or root-level
  historical probe outputs.
- If a generic MCP tool is modified or added:
  1. Run focused tests.
  2. Run `.venv/Scripts/python.exe -m pytest`.
  3. Run relevant live Maya smoke if possible.
  4. Commit and push `codex/mayamcp-dev`.
- If only the Maya scene is refined and no MCP source/docs/tests change, save
  the Maya scene but do not make a git commit.

## First Action For The Next Thread

Run these before doing anything else:

```powershell
git status --short --branch --untracked-files=no
.venv\Scripts\maya-mcp.exe doctor --live
```

If `doctor --live` fails, open Maya, load:

```text
F:/Codex134NewWorkspace/MayaMCP/mayamcp_artist_mesh_coke_bottle_v1.ma
```

Then open the recommended Python commandPort and rerun `doctor --live`.

After that, regenerate a fresh v205 baseline under:

```text
.maya_mcp_artifacts/v205_artist_component_refine/
```

Continue with duplicate-based A/B edits rather than starting a new scene.
