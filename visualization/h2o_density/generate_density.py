#!/usr/bin/env python3
"""Self-contained STO-3G RHF + CASCI(8e,6o) electron-density generator for the stretched-water viewer.

Pure NumPy/SciPy (McMurchie-Davidson integrals for s,p).  Writes data/*.f16 and data/manifest.json.
Run from anywhere:  python visualization/h2o_density/generate_density.py
Scope: CASCI reference density only.  A VQE density needs the saved PUCCSD parameters from the repo's
results/ summary.json files; see README ("Adding the VQE density").
"""
from __future__ import annotations
import json, math, sys, time
from functools import lru_cache
from pathlib import Path
import numpy as np, scipy
from scipy.special import hyp1f1

BOHR = 0.52917721092
R1_A, ANGLE = 0.96, 104.5
GEOMS = [1.80, 2.20, 2.60]                      # stretched O-H2 distance, angstrom
# STO-3G (Hehre/Stewart/Pople); values match the standard basis-set-exchange tables
ST = (0.15432897, 0.53532814, 0.44463454)
BASIS = {
 "O": dict(s1=([130.7093200, 23.8088610, 6.4436083], ST),
           s2=([5.0331513, 1.1695961, 0.3803890], (-0.09996723, 0.39951283, 0.70011547)),
           p2=([5.0331513, 1.1695961, 0.3803890], (0.15591627, 0.60768372, 0.39195739))),
 "H": dict(s1=([3.42525091, 0.62391373, 0.16885540], ST)),
}
ZNUC = {"O": 8, "H": 1}

def dfact(n): return 1.0 if n <= 0 else n * dfact(n - 2)
def prim_norm(a, l, m, n):
    return (2*a/math.pi)**0.75 * (4*a)**((l+m+n)/2) / math.sqrt(dfact(2*l-1)*dfact(2*m-1)*dfact(2*n-1))

class AO:
    def __init__(s, center, lmn, exps, coefs, label):
        s.c = np.array(center, float); s.lmn = lmn; s.label = label
        s.a = np.array(exps, float)
        s.d = np.array([c * prim_norm(a, *lmn) for a, c in zip(exps, coefs)])

def build_aos(atoms):
    aos = []
    for sym, xyz in atoms:
        for key, (ex, co) in BASIS[sym].items():
            for lmn in ([(0,0,0)] if key[0] == "s" else [(1,0,0),(0,1,0),(0,0,1)]):
                aos.append(AO(xyz, lmn, ex, co, f"{sym}{key}{lmn}"))
    return aos

@lru_cache(maxsize=None)
def Eh(i, j, t, Q, a, b):
    p = a + b; q = a*b/p
    if t < 0 or t > i + j: return 0.0
    if i == j == t == 0: return math.exp(-q*Q*Q)
    if j == 0:
        return (Eh(i-1,j,t-1,Q,a,b)/(2*p) - q*Q/a*Eh(i-1,j,t,Q,a,b) + (t+1)*Eh(i-1,j,t+1,Q,a,b))
    return (Eh(i,j-1,t-1,Q,a,b)/(2*p) + q*Q/b*Eh(i,j-1,t,Q,a,b) + (t+1)*Eh(i,j-1,t+1,Q,a,b))

def boys(n, x):
    return hyp1f1(n + 0.5, n + 1.5, -x) / (2*n + 1)

def Rtab(L, p, X, Y, Z):
    """R^0_{tuv} for t+u+v<=L as ndarray (L+1)^3."""
    r2 = X*X + Y*Y + Z*Z
    F = [(-2*p)**n * boys(n, p*r2) for n in range(L + 1)]
    cache = {}
    def R(t, u, v, n):
        if t < 0 or u < 0 or v < 0: return 0.0
        k = (t, u, v, n)
        if k in cache: return cache[k]
        if t == u == v == 0: val = F[n]
        elif t == 0 and u == 0: val = (v-1)*R(0,0,v-2,n+1) + Z*R(0,0,v-1,n+1)
        elif t == 0: val = (u-1)*R(0,u-2,v,n+1) + Y*R(0,u-1,v,n+1)
        else: val = (t-1)*R(t-2,u,v,n+1) + X*R(t-1,u,v,n+1)
        cache[k] = val; return val
    out = np.zeros((L+1,)*3)
    for t in range(L+1):
        for u in range(L+1-t):
            for v in range(L+1-t-u): out[t,u,v] = R(t,u,v,0)
    return out

def pairdata(A, B):
    data = []
    for a, da in zip(A.a, A.d):
        for b, db in zip(B.a, B.d):
            p = a + b; P = (a*A.c + b*B.c)/p
            E = [np.array([Eh(A.lmn[k], B.lmn[k], t, A.c[k]-B.c[k], a, b) for t in range(A.lmn[k]+B.lmn[k]+1)]) for k in range(3)]
            data.append((p, P, da*db, E))
    return data

def hermite_tensor(E):  # E_t E_u E_v
    return E[0][:,None,None]*E[1][None,:,None]*E[2][None,None,:]

def one_electron(aos, atoms):
    n = len(aos); S = np.zeros((n,n)); T = np.zeros((n,n)); V = np.zeros((n,n))
    for i in range(n):
        for j in range(i+1):
            A, B = aos[i], aos[j]; s = t = v = 0.0
            for a, da in zip(A.a, A.d):
                for b, db in zip(B.a, B.d):
                    p = a + b; P = (a*A.c + b*B.c)/p; w = da*db
                    S1 = lambda k, l1, l2: Eh(l1, l2, 0, A.c[k]-B.c[k], a, b)*math.sqrt(math.pi/p) if l2 >= 0 else 0.0
                    def T1(k):
                        l1, l2 = A.lmn[k], B.lmn[k]
                        return b*(2*l2+1)*S1(k,l1,l2) - 2*b*b*S1(k,l1,l2+2) - 0.5*l2*(l2-1)*S1(k,l1,l2-2)
                    sx, sy, sz = (S1(k, A.lmn[k], B.lmn[k]) for k in range(3))
                    s += w*sx*sy*sz
                    t += w*(T1(0)*sy*sz + sx*T1(1)*sz + sx*sy*T1(2))
                    E = [np.array([Eh(A.lmn[k],B.lmn[k],tt,A.c[k]-B.c[k],a,b) for tt in range(A.lmn[k]+B.lmn[k]+1)]) for k in range(3)]
                    Et = hermite_tensor(E); L = Et.shape[0]+Et.shape[1]+Et.shape[2]
                    for sym, C in atoms:
                        R = Rtab(L, p, *(P - np.array(C)))
                        v += -ZNUC[sym]*w*2*math.pi/p*np.sum(Et*R[:Et.shape[0],:Et.shape[1],:Et.shape[2]])
            S[i,j]=S[j,i]=s; T[i,j]=T[j,i]=t; V[i,j]=V[j,i]=v
    return S, T, V

def eri(aos):
    n = len(aos); pairs = {}
    for i in range(n):
        for j in range(i+1): pairs[(i,j)] = pairdata(aos[i], aos[j])
    keys = list(pairs); G = np.zeros((n,)*4)
    for x, k1 in enumerate(keys):
        for k2 in keys[:x+1]:
            val = 0.0
            for p, P, w1, E1 in pairs[k1]:
                H1 = hermite_tensor(E1)
                for q, Q, w2, E2 in pairs[k2]:
                    H2 = hermite_tensor(E2) * ((-1.0)**(np.arange(len(E2[0]))[:,None,None] + np.arange(len(E2[1]))[None,:,None] + np.arange(len(E2[2]))[None,None,:]))
                    L = sum(H1.shape) + sum(H2.shape)
                    al = p*q/(p+q); R = Rtab(L, al, *(P-Q))
                    s = 0.0
                    for t in range(H1.shape[0]):
                        for u in range(H1.shape[1]):
                            for v in range(H1.shape[2]):
                                s += H1[t,u,v]*np.sum(H2*R[t:t+H2.shape[0], u:u+H2.shape[1], v:v+H2.shape[2]])
                    val += w1*w2*s*2*math.pi**2.5/(p*q*math.sqrt(p+q))
            (i,j),(k,l) = k1, k2
            for a,b in ((i,j),(j,i)):
                for c,d in ((k,l),(l,k)):
                    G[a,b,c,d]=G[c,d,a,b]=val
    return G

def rhf(S, h, G, nocc, e_nuc, tol=1e-12):
    w, U = np.linalg.eigh(S); X = U @ np.diag(w**-0.5) @ U.T
    e0, C0 = np.linalg.eigh(X.T @ h @ X); C0 = X @ C0; P = 2*C0[:, :nocc] @ C0[:, :nocc].T; fs, es = [], []; E_old = 0
    for it in range(200):
        J = np.einsum("pqrs,rs->pq", G, P); K = np.einsum("prqs,rs->pq", G, P)
        F = h + J - 0.5*K; E = 0.5*np.sum(P*(h+F)) + e_nuc
        err = X.T @ (F@P@S - S@P@F) @ X; fs.append(F); es.append(err); fs, es = fs[-8:], es[-8:]
        if abs(E-E_old) < tol and np.abs(err).max() < 1e-9: break
        E_old = E
        if len(fs) > 2:
            m = len(fs); B = -np.ones((m+1,m+1)); B[m,m] = 0
            for a in range(m):
                for b in range(m): B[a,b] = np.sum(es[a]*es[b])
            rhs = np.zeros(m+1); rhs[m] = -1; c = np.linalg.lstsq(B, rhs, rcond=None)[0][:m]; F = sum(ci*fi for ci,fi in zip(c,fs))
        e, Cp = np.linalg.eigh(X.T @ F @ X); C = X @ Cp
        P = 2*C[:, :nocc] @ C[:, :nocc].T
    return dict(E=E, C=C, eps=e, converged=it < 199, iters=it+1)

# ---- CASCI(8e,6o) in a 12-spin-orbital Fock space (alpha: bit p, beta: bit p+6) ----
NSP = 6
def _cdag(i):
    import scipy.sparse as sp
    s = np.arange(1 << 12); m = ((s >> i) & 1) == 0; s0 = s[m]
    sign = 1 - 2*(np.array([bin(x & ((1 << i)-1)).count("1") for x in s0]) & 1)
    return sp.csr_matrix((sign, (s0 | (1 << i), s0)), shape=(1<<12, 1<<12))
def _sector():
    s = np.arange(1 << 12); pc = np.array([bin(x).count("1") for x in s])
    pa = np.array([bin(x & 63).count("1") for x in s]); pb = pc - pa
    return np.where((pa == 4) & (pb == 4))[0]
def casci(h_eff, g, e_const):
    cd = [_cdag(i) for i in range(2*NSP)]; idx = _sector()
    E = np.zeros((NSP, NSP, len(idx), len(idx)))
    for p in range(NSP):
        for q in range(NSP):
            M = cd[p] @ cd[q].T + cd[p+NSP] @ cd[q+NSP].T
            E[p,q] = M[idx][:, idx].toarray()
    Mq = np.einsum("pqrs,rsxy->pqxy", g, E)
    H = np.einsum("pq,pqxy->xy", h_eff, E)
    H += 0.5*sum(E[p,q] @ Mq[p,q] for p in range(NSP) for q in range(NSP))
    H -= 0.5*np.einsum("pqqs,psxy->xy", g, E) + 0*H
    H += e_const*np.eye(len(idx))
    assert np.abs(H - H.T).max() < 1e-9
    w, V = np.linalg.eigh(H); psi = V[:, 0]
    gamma = np.einsum("x,pqxy,y->pq", psi, E, psi)
    return w[0], gamma, w[1]

def geometry(r2_A):
    th = math.radians(ANGLE)
    xyz = [("O",(0,0,0)), ("H",(0,0,R1_A/BOHR)), ("H",(r2_A/BOHR*math.sin(th), 0, r2_A/BOHR*math.cos(th)))]
    return [(s, np.array(c, float)) for s, c in xyz]

def electronic_structure(r2_A):
    atoms = geometry(r2_A); aos = build_aos(atoms)
    S, T, V = one_electron(aos, atoms); G = eri(aos); h = T + V
    e_nuc = sum(ZNUC[a]*ZNUC[b]/np.linalg.norm(ca-cb) for i,(a,ca) in enumerate(atoms) for (b,cb) in atoms[:i])
    r = rhf(S, h, G, 5, e_nuc); C = r["C"]
    hm = C.T @ h @ C; gm = np.einsum("up,vq,wr,xs,uvwx->pqrs", C, C, C, C, G, optimize=True)
    act = list(range(1, 7))
    h_eff = hm[np.ix_(act, act)] + 2*gm[np.ix_(act, act, [0], [0])][..., 0, 0] - gm[np.ix_(act, [0], [0], act)][:, 0, 0, :]
    # note: K term (p c | c q) -> gm[p,c,c,q]
    e_const = e_nuc + 2*hm[0,0] + gm[0,0,0,0]
    g = gm[np.ix_(act, act, act, act)]
    e0, gamma, e1 = casci(h_eff, g, e_const)
    return dict(atoms=atoms, aos=aos, S=S, rhf=r, C=C, gamma=gamma, e_casci=e0, e_nuc=e_nuc, e_const=e_const, gap=e1-e0)

def ao_density_matrix(es):
    C = es["C"]; Ca = C[:, 1:7]
    return 2*np.outer(C[:,0], C[:,0]) + Ca @ es["gamma"] @ Ca.T

def rho_on_axes(aos, P, x, y, z, chunk=24):
    lam, Vv = np.linalg.eigh(0.5*(P+P.T)); keep = np.abs(lam) > 1e-14; lam, Vv = lam[keep], Vv[:, keep]
    out = np.empty((x.size, y.size, z.size))
    for s in range(0, x.size, chunk):
        xs = x[s:s+chunk]; chi = np.zeros((len(aos), xs.size, y.size, z.size))
        for m, ao in enumerate(aos):
            for a, d in zip(ao.a, ao.d):
                gx = xs-ao.c[0]; gy = y-ao.c[1]; gz = z-ao.c[2]
                fx = gx**ao.lmn[0]*np.exp(-a*gx*gx); fy = gy**ao.lmn[1]*np.exp(-a*gy*gy); fz = gz**ao.lmn[2]*np.exp(-a*gz*gz)
                chi[m] += d*fx[:,None,None]*fy[None,:,None]*fz[None,None,:]
        phi = np.tensordot(Vv.T, chi, axes=(1, 0))
        out[s:s+chunk] = np.tensordot(lam, phi*phi, axes=(0, 0))
    return out

def make_axes(atoms, h, margin=6.0):
    pts = np.array([c for _, c in atoms]); lo = pts.min(0)-margin; hi = pts.max(0)+margin
    n = np.ceil((hi-lo)/h).astype(int)+1
    return lo, n, [lo[k]+h*np.arange(n[k]) for k in range(3)]

def main():
    here = Path(__file__).resolve().parent; out = here/"data"; out.mkdir(exist_ok=True)
    H = 0.12; REF = dict(rhf=-74.62389238073564, casci=-74.86097709851931, occ=[1.999188939633346,1.9985416431320568,1.9732290227956406,1.3176550169607404,0.6826567097885724,0.028728667689640962])
    man = dict(schema=1, units=dict(density="electrons / bohr^3 (integrates to N = 10 electrons; NOT a probability density unless divided by 10)", length="bohr", bohr_in_angstrom=BOHR),
               software=dict(numpy=np.__version__, scipy=scipy.__version__, method="pure-NumPy STO-3G RHF + CASCI(8e,6o), frozen 1s-like core"),
               geometry_note=f"Asymmetric O-H stretch: R1 = {R1_A} A fixed, R2 variable, angle HOH = {ANGLE} deg. Not equilibrium water.",
               vqe=dict(available=False, reason="Saved PUCCSD optimal_point parameters were not available in the build environment; see README 'Adding the VQE density'."),
               datasets=[])
    for r2 in GEOMS:
        t0 = time.time(); es = electronic_structure(r2); gid = f"r2-{r2:.2f}"
        P = ao_density_matrix(es); trPS = float(np.sum(P*es["S"]))
        lo, n, ax = make_axes(es["atoms"], H); rho = rho_on_axes(es["aos"], P, *ax)
        _, na, axa = make_axes(es["atoms"], 0.06); audit = float(rho_on_axes(es["aos"], P, *axa, chunk=16).sum()*0.06**3)
        f16 = rho.transpose(2,1,0).astype("<f2"); fn = f"{gid}_casci.f16"; (out/fn).write_bytes(f16.tobytes())
        stored = float(f16.astype(np.float64).sum()*H**3); g64 = float(rho.sum()*H**3)
        occ = np.sort(np.linalg.eigvalsh(es["gamma"]))[::-1]
        entry = dict(id=f"{gid}_casci", geometry_id=gid, source_kind="casci", label="Classical reference: exact CASCI(8e,6o) state (STO-3G)",
            file=fn, dtype="float16-le", layout="x fastest, then y, then z", shape_xyz=[int(v) for v in n], origin_bohr=[float(v) for v in lo], spacing_bohr=H,
            rho_range=dict(min=float(rho.min()), max=float(rho.max())),
            geometry=dict(r1_angstrom=R1_A, r2_angstrom=r2, hoh_angle_deg=ANGLE, atoms=[dict(element=s, xyz_bohr=[float(v) for v in c]) for s, c in es["atoms"]]),
            energies_hartree=dict(rhf=es["rhf"]["E"], casci=es["e_casci"], casci_gap_to_first_excited=es["gap"]),
            checks=dict(trace_PS=trPS, grid_sum_float64=g64, grid_sum_stored_float16=stored, audit_grid_sum_h0p06=audit, audit_spacing_bohr=0.06,
                        gamma_trace=float(np.trace(es["gamma"])), natural_occupations=[float(v) for v in occ], rhf_converged=bool(es["rhf"]["converged"]), min_natural_occupation=float(occ.min())),
            notes="Float16 storage and the 0.12 bohr grid undersample the O 1s cusp region, so grid sums differ from 10 by ~1e-2; trace_PS and the 0.06 bohr audit give the accurate normalization.")
        if abs(r2-2.2) < 1e-9:
            entry["checks"]["vs_saved_repo_reference"] = dict(rhf_diff=es["rhf"]["E"]-REF["rhf"], casci_diff=es["e_casci"]-REF["casci"], max_natural_occ_diff=float(np.abs(occ-np.array(REF["occ"])).max()), reference="results/ansatz/puccsd-reps3-slsqp100/summary.json")
        man["datasets"].append(entry)
        print(gid, f"{time.time()-t0:.0f}s RHF {es['rhf']['E']:.10f} CASCI {es['e_casci']:.10f} trPS {trPS:.8f} audit {audit:.5f} stored {stored:.4f}", flush=True)
    (out/"manifest.json").write_text(json.dumps(man, indent=1))
if __name__ == "__main__": main()
