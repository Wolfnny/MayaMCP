# MayaMCP handoff notes

- Branch: `codex/add-uv-texture-tools`.
- Latest pushed generic-tool commit: `5808736 Use VP2 texture reload for previews`.
- Current generic tool work: texture preview refresh now uses VP2's native `ogs -reset` / `ogs -reloadTextures` path, touches file texture paths in place, and preserves Maya-friendly forward-slash texture paths. This touches `refresh_file_textures`, `setup_product_preview_scene`, and `setup_turntable_preview_scene`.
- Validation done: `py_compile` and `git diff --check` passed. Maya visual recheck passed with `v132_product_refresh_true.png` and `turntable_v132_refresh_true/v132_refresh_true_contact.png`.
- Important visual state: texture refresh is now verified for the label in both product preview and 0/45/90/135/180 turntable contact sheet. The bottle model itself is still not final.
- Safer bottle scene to resume from: `mayamcp_official_layered_bottle_v117_multiside_label.ma`. The `v118_deep_base` scene has a darker base experiment but was not visually proven better.
- Latest measured v117 silhouette comparison against the official 20 oz reference: IoU `0.9630`, aspect error `0.0071`, mean absolute width error `0.0135`. Largest remaining band error is shoulder/upper-label transition `0.18-0.34` normalized height; model is still too wide there and slightly too narrow in the top cap/neck band.
- Next validation: continue from v117 or a cleaned v118, then focus on bottle shape/material realism instead of texture-cache debugging. Validate from at least one off-front camera angle before accepting a visual change.
- Worktree note: generated `.png` / `.ma` assets are intentionally untracked. Existing tracked dirty files in `src/mayatools/object/create_advanced_model.py`, `src/mayatools/object/curve_modeling.py`, `src/mayatools/scene/generate_scene.py`, and `src/mayatools/scene/scene_save.py` were not part of the final texture-refresh commit and should not be staged without reviewing their origin.
