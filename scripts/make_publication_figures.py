#!/usr/bin/env python3
"""Build research figures from archived H2O VQE results; emits editable SVG using stdlib only."""
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt

import argparse, csv, html, json, math, xml.etree.ElementTree as ET
from pathlib import Path
from statistics import median

W,H=1400,900
C={"ink":"#19212b","muted":"#596575","axis":"#344054","faint":"#d9e0e8",
   "blue":"#0072b2","orange":"#e69f00","green":"#009e73","red":"#d55e00",
   "purple":"#cc79a7","sky":"#56b4e9","grey":"#697586","pale":"#e7f4ef"}
FIGS=[]
def E(x): return html.escape(str(x),quote=True)
def csvr(p):
    with open(p,newline="",encoding="utf-8-sig") as f:return list(csv.DictReader(f))
def jf(p): return json.loads(Path(p).read_text(encoding="utf8"))
def line(x1,y1,x2,y2,col=None,w=2,dash=""):
    a=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col or C["axis"]}" stroke-width="{w}"{a}/>'
def txt(x,y,s,size=17,col=None,weight="400",anchor="start",extra=""):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,Helvetica,sans-serif" font-size="{size}" fill="{col or C["ink"]}" font-weight="{weight}" text-anchor="{anchor}" {extra}>{E(s)}</text>'
def mark(x,y,kind,col,size=7,fill=None):
    f=fill or col
    if kind=="square":return f'<rect x="{x-size}" y="{y-size}" width="{2*size}" height="{2*size}" fill="{f}" stroke="{col}" stroke-width="2"/>'
    if kind=="triangle":return f'<polygon points="{x},{y-size-1} {x-size-1},{y+size} {x+size+1},{y+size}" fill="{f}" stroke="{col}" stroke-width="2"/>'
    if kind=="diamond":return f'<polygon points="{x},{y-size-1} {x-size-1},{y} {x},{y+size+1} {x+size+1},{y}" fill="{f}" stroke="{col}" stroke-width="2"/>'
    return f'<circle cx="{x}" cy="{y}" r="{size}" fill="{f}" stroke="{col}" stroke-width="2"/>'
def start(title,subtitle,no):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><title>{E(title)}</title><desc>{E(subtitle)}</desc><rect width="100%" height="100%" fill="white"/>',
            txt(58,48,no,17,C["muted"],"700"),txt(58,91,title,30,C["ink"],"700"),txt(58,123,subtitle,17,C["muted"])]
def end(p,foot):
    p.extend([line(58,824,1342,824,C["faint"],1.5),txt(58,855,foot,14,C["muted"]),
              txt(1342,855,"H₂O · STO-3G · frozen-core CAS(8e,6o)",14,C["muted"],anchor="end"),"</svg>"])
    return "\n".join(p)
def axes(p,x0,y0,x1,y1,xmap,ymap,xt,yt,xlabel,ylabel):
    p.extend([line(x0,y1,x1,y1,C["axis"],2),line(x0,y0,x0,y1,C["axis"],2)])
    for x,s in xt:
        xx=xmap(x);p.extend([line(xx,y1,xx,y1+7,C["axis"],1.5),txt(xx,y1+31,s,15,C["muted"],anchor="middle")])
    for y,s in yt:
        yy=ymap(y);p.extend([line(x0-7,yy,x0,yy,C["axis"],1.5),txt(x0-14,yy+5,s,15,C["muted"],anchor="end")])
    p.extend([txt((x0+x1)/2,y1+52,xlabel,18,C["ink"],"600","middle"),
      txt(x0-82,(y0+y1)/2,ylabel,18,C["ink"],"600","middle",f'transform="rotate(-90 {x0-82} {(y0+y1)/2})"')])
def path(p,pts,col,w=3,dash=""):
    if len(pts)>1:p.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>')
def lg(p,items,x,y):
    for i,(label,col,shape) in enumerate(items):
        xx=x+(i//2)*340; yy=y+(i%2)*30
        p.extend([mark(xx+8,yy-5,shape,col,6),txt(xx+25,yy,label,15)])
def save(out,name,title,sub,no,builder,caption,source):
    p=start(title,sub,no);builder(p);(out/(name+".svg")).write_text(end(p,caption),encoding="utf8")
    ET.parse(out/(name+".svg"))
    FIGS.append({"figure":no,"file":name+".svg","title":title,"caption":caption,"source":source})
def q(p,v):
    a=sorted(p);i=(len(a)-1)*v;lo=int(i);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(i-lo) if a else float("nan")
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--project",type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument("--output",type=Path);a=ap.parse_args()
    root=a.project.resolve();out=(a.output or root/"results/publication_figures").resolve();out.mkdir(parents=True,exist_ok=True)
    # Bond-scan inputs
    scan=csvr(root/"results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv")
    refs={float(r["stretched_oh_angstrom"]):r for r in scan if r["record_type"]=="reference"}
    vr={float(r["stretched_oh_angstrom"]):r for r in scan if r["record_type"]=="vqe"}
    xs=sorted(refs); cas={x:float(refs[x]["frozen_core_casci_hartree"]) for x in xs}
    hf={x:float(refs[x]["rhf_hartree"]) for x in xs}; vqe={x:float(vr[x]["total_energy_hartree"]) for x in xs if x in vr}
    # Figure 1: sparse asymmetric PES, only actual points.
    def f1(p):
        x0,x1,y0,y1=160,1290,180,690;lo,hi=min(xs)-.08,max(xs)+.08
        ys=[*cas.values(),*hf.values(),*vqe.values()];yl,yh=min(ys)-.012,max(ys)+.012
        xm=lambda x:x0+(x-lo)/(hi-lo)*(x1-x0);ym=lambda y:y1-(y-yl)/(yh-yl)*(y1-y0)
        ticks=[(x,f"{x:.1f}") for x in xs]
        axes(p,x0,y0,x1,y1,xm,ym,ticks,[(v,f"{v:.2f}") for v in [yl+(yh-yl)*i/4 for i in range(5)]],"Stretched O–H distance R₂ (Å)","Total energy (Ha)")
        for label,d,col,shape in [("RHF",hf,C["blue"],"circle"),("PUCCSD(3)",vqe,C["orange"],"triangle"),("Frozen-core CASCI",cas,C["ink"],"square")]:
            pts=[(xm(x),ym(d[x])) for x in xs if x in d];path(p,pts,col)
            for x,y in pts:p.append(mark(x,y,shape,col,6 if label=="PUCCSD(3)" else 9,"white" if label=="Frozen-core CASCI" else None))
        p.append(txt(1280,155,"R₁ = 0.96 Å · ∠HOH = 104.5°",16,C["muted"],anchor="end"))
        lg(p,[("RHF",C["blue"],"circle"),("Frozen-core CASCI",C["ink"],"square"),("PUCCSD(3)",C["orange"],"triangle")],335,775)
    save(out,"fig01_asymmetric_stretch_energy","Asymmetric O–H stretch: reference and VQE energies","Only the three calculated geometries are connected; connecting segments are visual guides, not a dense PES.","FIGURE 1",f1,"R₂ = 1.8, 2.2, and 2.6 Å. Energies are total electronic plus nuclear-repulsion values from the saved scan.","results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv")
    # Figure 2: scan errors, highlight chemical accuracy
    def f2(p):
        x0,x1,y0,y1=160,1290,180,690;ym=lambda y:y1-(y+10)/330*(y1-y0);xm=lambda x:x0+(x-min(xs))/(max(xs)-min(xs))*(x1-x0)
        p.append(f'<rect x="{x0}" y="{ym(1.6):.1f}" width="{x1-x0}" height="{ym(0)-ym(1.6):.1f}" fill="{C["pale"]}"/>')
        axes(p,x0,y0,x1,y1,xm,ym,[(x,f"{x:.1f}") for x in xs],[(v,str(v)) for v in [0,50,100,150,200,250,300]],"Stretched O–H distance R₂ (Å)","Absolute error vs CASCI (mHa)")
        p.append(line(x0,ym(1.6),x1,ym(1.6),C["green"],2,"8 6"))
        for d,col,shape in [(hf,C["blue"],"circle"),(vqe,C["orange"],"triangle")]:
            pts=[(xm(x),ym(abs(d[x]-cas[x])*1000)) for x in xs if x in d];path(p,pts,col)
            for x,y in pts:p.append(mark(x,y,shape,col,8))
        p.append(txt(x1-5,ym(1.6)-9,"1.6 mHa",14,C["green"],"700","end"))
        lg(p,[("RHF",C["blue"],"circle"),("PUCCSD(3)",C["orange"],"triangle")],610,775)
    save(out,"fig02_scan_error_vs_casci","Correlation recovery along the asymmetric stretch","Absolute total-energy error against frozen-core CASCI; shaded region is the 1.6 mHa target.","FIGURE 2",f2,"Three geometry points only. No values between the sampled geometries are inferred.","results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv")
    # Ansatz pilot
    ar=csvr(root/"results/ansatz/ansatz-resource-pilot/ansatz_runs.csv");groups={}
    for r in ar:groups.setdefault((r["method"],int(float(r["reps"]))),[]).append(r)
    order=[("uccsd",1),("puccsd",1),("puccsd",2),("puccsd",3)]
    names={("uccsd",1):"UCCSD ×1",("puccsd",1):"PUCCSD ×1",("puccsd",2):"PUCCSD ×2",("puccsd",3):"PUCCSD ×3"}
    # Figure 3 Pareto: actual run dots, median diamonds, min-max vertical range.
    def f3(p):
        x0,x1,y0,y1=190,1290,180,690;xm=lambda x:x0+(x-300)/1900*(x1-x0);ym=lambda y:y1-(y+0.4)/16.4*(y1-y0)
        p.append(f'<rect x="{x0}" y="{ym(1.6):.1f}" width="{x1-x0}" height="{ym(0)-ym(1.6):.1f}" fill="{C["pale"]}"/>')
        axes(p,x0,y0,x1,y1,xm,ym,[(400,"400"),(800,"800"),(1200,"1,200"),(1600,"1,600"),(2000,"2,000")],[(0,"0"),(2,"2"),(4,"4"),(8,"8"),(12,"12"),(16,"16")],"Transpiled CX count (level 3)","CASCI error (mHa)")
        p.append(line(x0,ym(1.6),x1,ym(1.6),C["green"],2,"8 6"))
        for k in order:
            rs=groups[k];col=C["blue"] if k[0]=="uccsd" else C["orange"];xx=xm(float(rs[0]["cx_level3"]));es=[float(r["absolute_error_mha"]) for r in rs]
            p.append(line(xx,ym(max(es)),xx,ym(min(es)),col,2))
            for j,e in enumerate(es):p.append(mark(xx+(j*16-8),ym(e),["circle","square"][j],col,7))
            p.append(mark(xx,ym(median(es)),"diamond",C["ink"],9))
            p.append(txt(xx+12,ym(median(es))-14,f'{names[k]} · {rs[0]["parameters"]} params',14,C["ink"],"600"))
        p.append(txt(1280,ym(1.6)-8,"1.6",14,C["green"],"700","end"))
    save(out,"fig03_accuracy_resource_pareto","Accuracy–entangling-resource trade-off","At R₂ = 2.20 Å: dots are observed starts; black diamonds mark medians.","FIGURE 3",f3,"CX counts are level-3 transpiler estimates. Min–max spans two starts (n=2), not a confidence interval.","results/ansatz/ansatz-resource-pilot/ansatz_runs.csv")
    # Figure 4 three aligned resource panels
    def f4(p):
        specs=[("Parameters","parameters",100),("Transpiled CX gates","cx_level3",2200),("Transpiled depth","depth_level3",2600)]
        x0,x1=190,1285
        for i,(title,key,top) in enumerate(specs):
            y0=180+i*185;y1=y0+125;xm=lambda x:x0+(x-.75)/2.5*(x1-x0);ym=lambda y:y1-y/top*(y1-y0)
            p.append(txt(65,y0+20,title,16,C["ink"],"600"));p.extend([line(x0,y1,x1,y1,C["axis"],1.7),line(x0,y0,x0,y1,C["axis"],1.7)])
            for rep in (1,2,3):
                xx=xm(rep);p.extend([line(xx,y1,xx,y1+5,C["axis"],1),txt(xx,y1+20,str(rep),14,C["muted"],anchor="middle")])
            p.append(txt(x0-12,y0+5,str(top),14,C["muted"],anchor="end"));p.append(txt(x0-12,y1+4,"0",14,C["muted"],anchor="end"))
            pts=[(xm(r),ym(float(groups[("puccsd",r)][0][key]))) for r in (1,2,3)]
            path(p,pts,C["orange"])
            for xx,yy in pts:p.append(mark(xx,yy,"circle",C["orange"],7))
            row=groups[("uccsd",1)][0]
            p.append(mark(xm(1),ym(float(row[key])),"square",C["blue"],7))
            if i==2:p.append(txt((x0+x1)/2,y1+48,"PUCCSD repetition count",15,C["muted"],"400","middle"))
        p.extend([mark(1010,758,"circle",C["orange"],6),txt(1028,763,"PUCCSD",14),mark(1120,758,"square",C["blue"],6),txt(1138,763,"UCCSD ×1",14)])
    save(out,"fig04_ansatz_resource_scaling","Circuit-resource growth with paired-ansatz repetitions","Three aligned resource axes; UCCSD is included only at its measured one-layer setting.","FIGURE 4",f4,"Counts are from the recorded level-3 compilation of the logical circuit, not hardware-routed execution.","results/ansatz/ansatz-resource-pilot/ansatz_runs.csv")
    # Figure 5 show starts individually
    def f5(p):
        x0,x1,y0,y1=165,1290,180,690;ym=lambda y:y1-(y+0.4)/16.4*(y1-y0);xs0=[300,590,880,1170]
        axes(p,x0,y0,x1,y1,lambda x:x,ym,[],[(0,"0"),(2,"2"),(4,"4"),(8,"8"),(12,"12"),(16,"16")],"","CASCI error (mHa)")
        p.append(line(x0,ym(1.6),x1,ym(1.6),C["green"],2,"8 6"))
        for j,k in enumerate(order):
            vals=[float(r["absolute_error_mha"]) for r in groups[k]];xx=xs0[j];col=C["blue"] if k[0]=="uccsd" else C["orange"]
            for n,v in enumerate(vals):p.append(mark(xx+(n*18-9),ym(v),["circle","square"][n],col,8))
            p.append(line(xx-23,ym(median(vals)),xx+23,ym(median(vals)),C["ink"],3))
            p.append(txt(xx,720,names[k],15,C["ink"],"600","middle"));p.append(txt(xx,744,f'n={len(vals)} starts',14,C["muted"],anchor="middle"))
            p.append(txt(xx,ym(max(vals))-17,f'{min(vals):.2f}–{max(vals):.2f}',14,C["muted"],"600","middle"))
    save(out,"fig05_ansatz_restart_spread","Observed restart-to-restart variability","Every saved start is shown; short dark bars are medians.","FIGURE 5",f5,"Two starts per configuration only (n=2); observed range is not a confidence interval or a global-minimum guarantee.","results/ansatz/ansatz-resource-pilot/ansatz_runs.csv")
    # Figure 6 ansatz ideal convergence traces
    hs=[]
    for method,rep in order:
        fp=root/f"results/ansatz/ansatz-resource-pilot/{method}-reps{rep}/optimization_history.csv"
        if not fp.exists():continue
        rr=csvr(fp)
        for tr in sorted(set(int(r["trial"]) for r in rr)):
            rows=[r for r in rr if int(r["trial"])==tr];best=1e9;ys=[]
            for r in rows:
                best=min(best,float(r["energy_total_hartree"]));ys.append(abs(best+74.8609770985193)*1000)
            hs.append((method,rep,tr,list(range(1,len(ys)+1)),ys))
    def f6(p):
        x0,x1,y0,y1=175,1290,180,690;xm=lambda x:x0+x/150*(x1-x0);ym=lambda y:y1-(math.log10(max(.01,min(1500,y)))-math.log10(.01))/(math.log10(1500)-math.log10(.01))*(y1-y0)
        axes(p,x0,y0,x1,y1,xm,ym,[(0,"0"),(30,"30"),(60,"60"),(90,"90"),(120,"120"),(150,"150")],[(.01,"0.01"),(.1,"0.1"),(1,"1"),(10,"10"),(100,"100"),(1000,"1,000")],"Objective evaluation count","Best-so-far CASCI error (mHa; log scale)")
        p.append(line(x0,ym(1.6),x1,ym(1.6),C["green"],2,"8 6"))
        for m,r,tr,xs,ys in hs:
            col=C["blue"] if m=="uccsd" else C["orange"];path(p,[(xm(x),ym(max(.01,y))) for x,y in zip(xs,ys)],col,1.8,"4 4" if tr else "")
        lg(p,[("UCCSD ×1",C["blue"],"square"),("PUCCSD ×1, ×2, ×3",C["orange"],"circle")],550,775)
    save(out,"fig06_ansatz_convergence","Optimization traces under a fixed evaluation cap","Thin traces are individual starts; energy is exact statevector and plotted as best-so-far error.","FIGURE 6",f6,"The pilot used a 150-objective-evaluation cap. Gradient evaluations and wall-clock cost are not represented by this x-axis.","results/ansatz/ansatz-resource-pilot/*/optimization_history.csv")
    # Optimizer benchmark data
    metrics=csvr(root/"results/optimizers/systematic-optimizer-study/all_run_metrics.csv")
    held=[r for r in metrics if r["phase"]=="heldout"];ops=["slsqp","lbfgsb","cobyla","powell","spsa"]
    opnames=["SLSQP","L-BFGS-B","COBYLA","Powell","SPSA (auto-cal.)"]
    opcols=[C["blue"],C["green"],C["red"],C["purple"],C["grey"]]
    # log y helper
    def ylog(v):return 690-(math.log10(max(1,min(1200,v)))-0)/(math.log10(1200))*(690-180)
    def f7(p):
        x0,x1=190,1290;xs=[260+i*220 for i in range(5)]
        p.extend([line(x0,690,x1,690,C["axis"]),line(x0,180,x0,690,C["axis"])])
        for v in [1,2,5,10,20,50,100,300,1000]:
            yy=ylog(v);p.extend([line(x0-7,yy,x0,yy,C["axis"],1.4),txt(x0-13,yy+5,str(v),14,C["muted"],anchor="end")])
        p.append(line(x0,ylog(1.6),x1,ylog(1.6),C["green"],2,"8 6"))
        for i,op in enumerate(ops):
            vals=[float(r["error_vs_casci_mha"]) for r in held if r["optimizer"]==op];xx=xs[i]
            for j,v in enumerate(vals):p.append(mark(xx+((j%5)-2)*12,ylog(v),"circle",opcols[i],5.8))
            if vals:
                p.extend([line(xx,ylog(q(vals,.75)),xx,ylog(q(vals,.25)),C["ink"],3),line(xx-14,ylog(median(vals)),xx+14,ylog(median(vals)),C["ink"],4),
                          txt(xx,720,opnames[i],14,C["ink"],"600","middle"),txt(xx,743,f'n={len(vals)}',14,C["muted"],anchor="middle")])
        p.extend([txt((x0+x1)/2,790,"Held-out optimizer",17,C["ink"],"600","middle"),
          txt(65,435,"Absolute error vs CASCI (mHa; logarithmic scale)",15,C["ink"],"600","middle",f'transform="rotate(-90 65 435)"')])
        p.append(txt(x1-2,ylog(1.6)-8,"1.6",14,C["green"],"700","end"))
    save(out,"fig07_optimizer_outcomes","Held-out optimizer outcomes for PUCCSD(1)","Dots are independent held-out starts; black bars show median and interquartile range. Lower is better.","FIGURE 7",f7,"Ten starts per optimizer. Results use ideal statevector objectives; evaluation count is not equal to wall-clock or hardware cost.","results/optimizers/systematic-optimizer-study/all_run_metrics.csv")
    # Fig 8 common checkpoints median/IQR
    cp=csvr(root/"results/optimizers/systematic-optimizer-study/heldout_checkpoints.csv");check=sorted(set(float(r["checkpoint_evaluations"]) for r in cp))
    def f8(p):
        x0,x1,y0,y1=190,1290,180,690;xm=lambda x:x0+(x-min(check))/(max(check)-min(check))*(x1-x0)
        axes(p,x0,y0,x1,y1,xm,ylog,[(x,f"{x:g}") for x in check if x in [100,300,500,800,1000,1200]],[(v,str(v)) for v in [1,2,5,10,20,50,100,300,1000]],"Objective-evaluation checkpoint","Median error vs CASCI (mHa; log scale)")
        p.append(line(x0,ylog(1.6),x1,ylog(1.6),C["green"],2,"8 6"))
        for i,op in enumerate(ops):
            pts=[]
            for x in check:
                vals=[float(r["gap_vs_casci_mha"]) for r in cp if r["optimizer"]==op and float(r["checkpoint_evaluations"])==x]
                if vals:
                    xx,ymed=xm(x),ylog(median(vals));pts.append((xx,ymed));p.append(line(xx,ylog(q(vals,.75)),xx,ylog(q(vals,.25)),opcols[i],2))
            path(p,pts,opcols[i],3)
            for xx,yy in pts:p.append(mark(xx,yy,"circle",opcols[i],4.8))
        lg(p,[(opnames[i],opcols[i],["circle","square","triangle","diamond","circle"][i]) for i in range(5)],280,775)
    save(out,"fig08_optimizer_budget_convergence","Optimizer convergence at common evaluation checkpoints","Center lines are held-out medians; whiskers show the interquartile range.","FIGURE 8",f8,"Objective evaluations are a budget proxy. Exact gradients, their cost, and elapsed time differ across optimizers.","results/optimizers/systematic-optimizer-study/heldout_checkpoints.csv")
    # Figure 9 numeric SPSA calibration heatmap.
    tune=csvr(root/"results/optimizers/systematic-optimizer-study/spsa_tuning_ranked.csv")
    grid={(float(r["a"]),float(r["c"])):float(r["median"]) for r in tune if r.get("a") and r.get("c")}
    aa=sorted(set(k[0] for k in grid));cc=sorted(set(k[1] for k in grid));auto=next((r for r in tune if r["label"]=="auto_calibration"),None)
    def f9(p):
        xx0,yy0,cw,ch=295,250,200,95
        p.append(txt(xx0,190,"Median gap vs empirical SLSQP anchor (mHa; development data)",16,C["ink"],"600"))
        vals=list(grid.values());vmin,vmax=min(vals),max(vals)
        def shade(v):
            t=(math.log(v)-math.log(vmin))/(math.log(vmax)-math.log(vmin)+1e-9);r=round(232-100*t);g=round(244-65*t);b=round(250-25*t)
            return f"#{r:02x}{g:02x}{b:02x}"
        for j,c in enumerate(cc):p.append(txt(xx0+j*cw+cw/2,yy0-20,f"c={c:g}",15,C["ink"],"600","middle"))
        for i,a0 in enumerate(aa):
            y=yy0+i*ch;p.append(txt(xx0-20,y+ch/2+5,f"a={a0:g}",15,C["ink"],"600","end"))
            for j,c in enumerate(cc):
                if (a0,c) not in grid:continue
                v=grid[(a0,c)];x=xx0+j*cw
                p.extend([f'<rect x="{x}" y="{y}" width="{cw-5}" height="{ch-5}" rx="4" fill="{shade(v)}" stroke="white" stroke-width="2"/>',
                  txt(x+(cw-5)/2,y+ch/2+6,f"{v:.0f}",18,C["ink"],"700","middle")])
        if auto:
            p.extend([txt(1050,280,"Auto-calibration",16,C["ink"],"700"),
              f'<rect x="1050" y="300" width="255" height="95" rx="4" fill="#f1f3f5" stroke="{C["grey"]}" stroke-width="2"/>',
              txt(1178,340,f'median {float(auto["median"]):.1f} mHa',16,C["ink"],"600","middle"),
              txt(1178,372,f'n={auto["n"]} development starts',14,C["muted"],anchor="middle")])
        p.extend([txt(xx0,735,"SPSA perturbation scale c",17,C["ink"],"600","middle"),
          txt(115,455,"Learning rate a",16,C["ink"],"600","middle",f'transform="rotate(-90 115 455)"'),
          txt(xx0,785,"Each numeric cell summarizes four tuning starts; smaller is better.",14,C["muted"])])
    save(out,"fig09_spsa_tuning_heatmap","SPSA calibration grid: development-stage results","Numeric grid varies learning-rate scale a and perturbation scale c; auto-calibration is separate.","FIGURE 9",f9,"Tuning data only, not held-out performance. The selected auto-calibration schedule is run-dependent.","results/optimizers/systematic-optimizer-study/spsa_tuning_ranked.csv")
    # Figure 10 ADAPT partial run: plot only accepted macrocycles present in CSV.
    ad=root/"results/ansatz/adapt-slsqp-final-16cycle";prog=csvr(ad/"adapt_progress.csv");cycles=sorted(int(r["macrocycle"]) for r in prog);maxc=max(cycles)
    def f10(p):
        x0,x1=190,1290;xm=lambda x:x0+(x-1)/15*(x1-x0);top,bot=185,485;err=lambda r:float(r["absolute_error_vs_active_casci_millihartree"]);mx=max(32,max(err(r) for r in prog)+2);ym=lambda y:bot-y/mx*(bot-top)
        p.append(f'<rect x="{xm(maxc)}" y="{top}" width="{x1-xm(maxc)}" height="{bot-top}" fill="#f4f5f7"/>')
        axes(p,x0,top,x1,bot,xm,ym,[(v,str(v)) for v in [1,4,8,12,16]],[(0,"0"),(8,"8"),(16,"16"),(24,"24"),(32,"32")],"ADAPT macrocycle","Absolute error vs CASCI (mHa)")
        p.append(line(x0,ym(1.6),x1,ym(1.6),C["green"],2,"8 6"));pts=[(xm(int(r["macrocycle"])),ym(err(r))) for r in prog];path(p,pts,C["green"])
        for x,y in pts:p.append(mark(x,y,"circle",C["green"],7))
        p.extend([txt(x1-8,top+24,f"recorded {maxc}/16 cycles",15,C["muted"],"700","end"),
          txt(xm(maxc)-8,ym(err(prog[-1]))-16,f'{err(prog[-1]):.2f} mHa',14,C["green"],"700","end")])
        top2,bot2=570,700;gvals=[float(r["max_pool_gradient_abs"]) for r in prog];gh=max(gvals)*1.12;yg=lambda y:bot2-y/gh*(bot2-top2)
        p.extend([txt(82,(top2+bot2)/2,"Largest pool gradient (Ha)",14,C["ink"],"600","middle",f'transform="rotate(-90 82 {(top2+bot2)/2})"'),line(x0,top2,x0,bot2,C["axis"],1.7),line(x0,bot2,x1,bot2,C["axis"],1.7),txt(x0-12,bot2+4,"0",14,C["muted"],anchor="end"),txt(x0-12,top2+4,f"{gh:.2f}",14,C["muted"],anchor="end")])
        pts2=[(xm(int(r["macrocycle"])),yg(float(r["max_pool_gradient_abs"]))) for r in prog];path(p,pts2,C["red"],2.5)
        for x,y in pts2:p.append(mark(x,y,"diamond",C["red"],5.5))
        p.append(txt(x0,bot2+39,"Interrupted after cycle 11; the remaining five cycles are unobserved.",14,C["red"],"700"))
    save(out,"fig10_adapt_macrocycle_progress","Fermionic ADAPT-VQE: progress through the interrupted run","Accepted macrocycles from the saved checkpoint; no values are inferred for uncompleted cycles.","FIGURE 10",f10,"The run stopped after 11 of 16 requested cycles. Final recorded error: 3.473 mHa vs active-space CASCI; chemical accuracy was not reached.","results/ansatz/adapt-slsqp-final-16cycle/adapt_progress.csv")
    # Figure 11: show the complete one-sigma sampling interval and separate near-zero accuracy scale.
    nd=jf(root/"results/noisy-demo/puccsd-reps1-16shots.json");casref=float(nd["active_casci_reference_hartree"])
    ideal=(float(nd["ideal_energy_hartree"])-casref)*1000;noisy=(float(nd["noisy_mean_energy_hartree"])-casref)*1000;se=float(nd["propagated_sampling_standard_error_of_mean_hartree"])*1000
    def f11(p):
        # Main panel spans the full ±1 SE interval; inset resolves chemical accuracy near zero.
        x0,x1,y0,y1=190,820,205,655;lo,hi=-100,1500;ym=lambda v:y1-(v-lo)/(hi-lo)*(y1-y0);xc=[360,660]
        p.append(txt(x0,y0-24,"A  Full estimate scale",17,C["ink"],"700"))
        axes(p,x0,y0,x1,y1,lambda x:x,ym,[(xc[0],"Ideal"),(xc[1],"Noisy")],[(0,"0"),(500,"500"),(1000,"1,000"),(1500,"1,500")],"Fixed PUCCSD(1) circuit","Signed error vs CASCI (mHa)")
        p.append(line(x0,ym(0),x1,ym(0),C["ink"],1.5))
        p.extend([mark(xc[0],ym(ideal),"square",C["blue"],8),
          line(xc[1],ym(noisy+se),xc[1],ym(noisy-se),C["red"],3),
          line(xc[1]-12,ym(noisy+se),xc[1]+12,ym(noisy+se),C["red"],3),
          line(xc[1]-12,ym(noisy-se),xc[1]+12,ym(noisy-se),C["red"],3),
          mark(xc[1],ym(noisy),"circle",C["red"],8),
          txt(xc[1]+22,ym(noisy+se)-4,f"±1 SE: {noisy-se:+.0f} to {noisy+se:+.0f} mHa",13,C["red"],"700"),
          txt(xc[0],y1+62,f"{ideal:+.1f} mHa",14,C["blue"],"700","middle"),
          txt(xc[1],y1+62,f"{noisy:+.1f} mHa",14,C["red"],"700","middle")])
        # Inset has its own honest axis and makes the ±1.6 mHa band legible.
        a0,a1,b0,b1=955,1300,205,655;zlo,zhi=-3,15;zy=lambda v:b1-(v-zlo)/(zhi-zlo)*(b1-b0);zmid=(a0+a1)/2
        p.append(txt(a0,b0-24,"B  Accuracy-scale inset",17,C["ink"],"700"))
        axes(p,a0,b0,a1,b1,lambda x:x,zy,[(zmid,"Ideal PUCCSD(1)")],[(-2,"−2"),(0,"0"),(2,"2"),(5,"5"),(10,"10"),(15,"15")],"","Signed error (mHa)")
        p.append(f'<rect x="{a0}" y="{zy(1.6):.1f}" width="{a1-a0}" height="{zy(-1.6)-zy(1.6):.1f}" fill="{C["pale"]}"/>')
        # Re-draw inset axes and ticks above the shaded target band.
        p.extend([line(a0,b1,a1,b1,C["axis"],2),line(a0,b0,a0,b1,C["axis"],2),line(a0,zy(0),a1,zy(0),C["ink"],1.5),
          line(a0,zy(1.6),a1,zy(1.6),C["green"],2,"7 5"),line(a0,zy(-1.6),a1,zy(-1.6),C["green"],2,"7 5"),
          mark(zmid,zy(ideal),"square",C["blue"],8),
          txt(a1-4,zy(1.6)-7,"±1.6 mHa target",13,C["green"],"700","end"),
          txt(zmid,zy(ideal)-15,f"{ideal:+.1f}",14,C["blue"],"700","middle"),
          txt(zmid,b1+62,"Noisy interval is outside this zoom",13,C["muted"],"600","middle")])
        p.append(txt((x0+x1)/2,785,"One seed · 16 shots per each of 276 QWC groups · ±1 propagated sampling SE",14,C["muted"],anchor="middle"))
    save(out,"fig11_synthetic_noise_uncertainty","Low-shot synthetic noise: uncertainty overwhelms the ideal error","Fixed-parameter local Aer result with a two-scale view; not backend-calibrated or IBM hardware data.","FIGURE 11",f11,"One seed; 16 shots/group. Bars show ±1 propagated sampling SE; not QPU data.","results/noisy-demo/puccsd-reps1-16shots.json")
    FIGS[-1]["caption"]="PUCCSD(1), 10 mapped qubits; 4,416 shots total. Synthetic noise p₁=10⁻⁴, p₂=10⁻³, symmetric readout flip=1%. Noisy estimate error +789.3 mHa ±570.4 mHa (one propagated sampling SE, one seed); this is too imprecise to support a chemical-accuracy claim."
    (out/"figure_manifest.json").write_text(json.dumps({"study":"Asymmetric O-H stretch of H2O, STO-3G, frozen-core CAS(8e,6o)","figures":FIGS,
      "not_plotted":["Backend-calibrated Aer run has no completed case in the saved status file.","No completed IBM QPU result was available in the saved project results when this figure set was built; add a hardware comparison after the submitted job finishes."],"vector_primary":True},indent=2),encoding="utf8")
    md=["# H₂O VQE publication figure catalog","","Primary files are editable SVG vector figures; paired PNG previews are 4200 × 2700 px at 600 dpi. They were generated from archived CSV/JSON; no values were synthesized. Lines through bond-scan points are visual guides only.",""]
    for f in FIGS:md += [f'## {f["figure"]} — {f["title"]}',"",f["caption"],"",f'Source: {f["source"]}',""]
    md += ["## Design and interpretation","",
      "Figures follow scientific plotting principles: unit-labelled axes, uncluttered white canvas, accessible color with marker-shape redundancy, and editable vector output. Nature’s guide recommends accessible palettes, readable sans-serif labels, axes with units, and vector artwork: https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/.",
      "The plot structures reflect published VQE work: molecular energy/error curves for water (https://pubs.rsc.org/en/content/articlehtml/2024/cp/d3cp05570a; https://pubs.rsc.org/en/content/articlepdf/2025/dd/d5dd00202h), optimizer convergence for fixed ansatz (https://doi.org/10.1038/s42005-025-02375-9), and error/resource analyses under noise (https://doi.org/10.1103/PhysRevA.109.042413).",
      "Ansatz pilot has n=2 starts only. Optimizer counts are objective evaluations, not equivalent compute cost. ADAPT data is partial at 11/16 cycles (stopped at 3.473 mHa error). Noise plot is one synthetic finite-shot run with very large uncertainty; it is neither calibrated backend noise nor hardware data.",
      "The backend-calibrated Aer study was still marked running with zero completed cases; it is not plotted as a result. No completed IBM QPU data were available when this figure set was generated."]
    (out/"FIGURE_CATALOG.md").write_text("\n".join(md),encoding="utf8")
    gallery=['<!doctype html><meta charset="utf-8"><title>H2O VQE figure review</title><style>body{font:16px Arial,sans-serif;max-width:1200px;margin:32px auto;color:#19212b}figure{margin:28px 0 48px}img{width:100%;border:1px solid #d9e0e8}figcaption{color:#596575;line-height:1.5}</style><h1>H₂O VQE figure review</h1><p>Archived data; see catalog for captions and limitations.</p>']
    for f in FIGS:gallery.append(f'<figure><img src="{E(f["file"])}"><figcaption><b>{E(f["figure"])}. {E(f["title"])}</b><br>{E(f["caption"])}</figcaption></figure>')
    gallery.append('<p><a href="FIGURE_CATALOG.md">Figure catalog</a></p>')
    (out/"index.html").write_text("\n".join(gallery),encoding="utf8")
    print(f"Created {len(FIGS)} SVG figures in {out}")
    for f in FIGS:print(f'{f["figure"]}: {f["file"]}')
if __name__=="__main__":main()





