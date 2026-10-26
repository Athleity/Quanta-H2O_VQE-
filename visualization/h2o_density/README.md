# H₂O electron-density viewer (asymmetric O–H stretch)

Interactive 3D viewer for the electron density ρ(r) of water at three precomputed geometries:
R₁ = 0.96 Å fixed, ∠HOH = 104.5°, R₂ = 1.80 / 2.20 / 2.60 Å. These are **not** equilibrium water.

## Status
- **CASCI reference (exact CAS(8e,6o), STO-3G): included.** At R₂ = 2.20 Å it matches the repo's saved RHF/CASCI energies and natural occupations to ~1e-11 Eh.
- **VQE-derived density (saved PUCCSD state): NOT included yet.** It needs the `optimal_point` parameters from `results/**/summary.json`, which were unavailable when this was built. The viewer shows that option disabled. To add it: compute the state's spin-summed 1-RDM, then call `ao_density_matrix` / `rho_on_axes` from `generate_density.py` and add a `source_kind: "vqe"` entry to `data/manifest.json`. The viewer picks it up automatically. Note the saved parameters fix the state only up to orbital sign conventions; check energies against the saved total energy.

## Run locally
    cd visualization/h2o_density
    python3 -m http.server 8000
    # open http://localhost:8000/web/index.html   (needs a WebGL2 browser)

Regenerate data (NumPy + SciPy only, ~1 min): `python3 generate_density.py`
Browser smoke test: `pip install playwright && playwright install chromium && python3 tests/browser_check.py`

## Files
- `generate_density.py` – integrals, RHF, CASCI, density grids, manifest
- `data/manifest.json` – geometry, energies, normalization checks; `data/*.f16` – float16 density volumes (x fastest)
- `web/index.html`, `style.css`, `app.js` – viewer (WebGL2, no libraries; fonts load from Google Fonts with fallbacks)
- `tests/browser_check.py` – headless-browser checks (see limitations)

## Reading the view
- **Glowing blue shells** are five isodensity surfaces of ρ(r) (0.004 … 2.5 e/bohr³, listed in the legend). ρ integrates to N = 10 electrons; it is **not** a probability density unless divided by 10.
- **Atoms and bonds** are geometry only (O red, H white). The solid bond is the fixed O–H₁ (0.96 Å); the dashed bond is the stretched O–H₂.
- **Bond-stretch animation / scrubber:** only R₂ = 1.80, 2.20, 2.60 Å are computed. Between them the atoms move continuously and the neighbouring densities cross-fade; the tag turns to "interpolated". Intermediate densities are not calculated.
- Float16 storage on a 0.12 bohr grid gives grid sums of ~10.02-10.04; the manifest's Tr(PS) and fine-grid values are the accurate normalization.

## Controls
Drag rotate · Shift/right-drag pan · wheel/pinch zoom · arrows, +/−, R (reset), F (fit) · Play/Pause stretch, scrubber, Auto-rotate · Controls drawer: shell level (re-meshes), glow, atom size.

## Performance design
No ray-marching: the 15 isosurfaces are meshed once at load (marching tetrahedra, ~1 s, yields between shells) and drawn as ordinary triangles (~110k per geometry), with adaptive resolution if the device is slow.

## Copy into your GitHub project
Copy this whole folder to `visualization/h2o_density/` in your repo, then `git add visualization/h2o_density && git commit`. Nothing is pushed for you. Data is ~11 MB.
