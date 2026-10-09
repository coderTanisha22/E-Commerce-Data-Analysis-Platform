"""Slide-sized charts for the synthetic inventory deck.

Bigger type, fewer marks and one message per chart: these are read from across a
room, not held at desk distance like the report figures.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
from matplotlib.patches import Patch

ACCENT="#35618C"; CRIT="#B02418"; WARN="#C08A00"; GOOD="#2E7D57"
GREY="#B6C2CD"; INK="#151A21"; MUTED="#5A6675"; RULE="#D3DAE1"; PAPER="#FFFFFF"
OUT="reports/slides/"
plt.rcParams.update({"font.size":13,"font.family":"DejaVu Sans"})

inv=pd.read_parquet("data/processed/synthetic_inventory.parquet")
suff=inv[inv.evidence=="sufficient"]

def style(ax,xl="",yl="",grid="y"):
    ax.set_facecolor(PAPER)
    for s in ("top","right"): ax.spines[s].set_visible(False)
    for s in ("left","bottom"): ax.spines[s].set_color(RULE)
    ax.tick_params(colors=MUTED,labelsize=12,length=0)
    ax.set_xlabel(xl,color=MUTED,fontsize=13); ax.set_ylabel(yl,color=MUTED,fontsize=13)
    if grid: ax.grid(axis=grid,color=RULE,lw=.8,alpha=.7); ax.set_axisbelow(True)

def title(ax,t,sub=None):
    """Title above subtitle, both in axes coords so they cannot collide."""
    ax.text(0,1.19 if sub else 1.06,t,transform=ax.transAxes,fontsize=17,
            fontweight="bold",color=INK,va="bottom")
    if sub:
        ax.text(0,1.055,sub,transform=ax.transAxes,fontsize=12,color=MUTED,va="bottom")

def save(fig,name):
    fig.tight_layout(rect=(0,0,1,0.90)); fig.savefig(OUT+name,dpi=200,facecolor=PAPER,bbox_inches="tight")
    plt.close(fig); print("wrote",OUT+name)

# ---------------------------------------------------- 1 real vs synthetic map
fig,ax=plt.subplots(figsize=(10,5.4),facecolor=PAPER)
cols=[("seller_id","real"),("product_id","real"),("units_sold","real"),
      ("first_sale_date","real"),("active_days","real"),("daily_sales_rate","real"),
      ("evidence","real"),("lead_time_days","synthetic"),("current_quantity","synthetic"),
      ("last_restock_date","synthetic"),("reorder_point","derived"),
      ("days_of_inventory","derived"),("status","derived")]
colmap={"real":ACCENT,"synthetic":WARN,"derived":GOOD}
y=np.arange(len(cols))[::-1]
for i,(c,k) in enumerate(cols):
    ax.barh(y[i],1,color=colmap[k],height=.72)
    ax.text(1.03,y[i],c,va="center",fontsize=12.5,color=INK,family="DejaVu Sans Mono")
ax.set_xlim(0,4.2); ax.set_ylim(-.8,len(cols)-.2); ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values(): s.set_visible(False)
title(ax,"Every column is labelled at the source",
      "7 columns come from real Olist orders  ·  3 are generated  ·  3 are formulas over the first two")
ax.legend(handles=[Patch(color=ACCENT,label="Real (from Olist)"),
                   Patch(color=WARN,label="Synthetic (seeded RNG)"),
                   Patch(color=GOOD,label="Derived (formula)")],
          frameon=False,fontsize=12.5,loc="lower right",labelcolor=MUTED)
save(fig,"s1_real_vs_synthetic.png")

# ---------------------------------------------------- 2 filter funnel
fig,ax=plt.subplots(figsize=(10,4.6),facecolor=PAPER)
steps=["All seller-product\npairs in Olist","Drop canceled /\nunavailable","Keep analysis\nwindow only\n= generated table"]
vals=[34448,34212,33787]
drops=[None,-236,-425]
ax.bar(range(3),vals,color=[GREY,GREY,ACCENT],width=.55)
for i,v in enumerate(vals):
    ax.text(i,v+90,f"{v:,}",ha="center",fontsize=15,fontweight="bold",
            color=ACCENT if i==2 else MUTED)
    if drops[i]: ax.text(i,vals[i]-260,f"{drops[i]}",ha="center",fontsize=12.5,color=CRIT)
ax.set_xticks(range(3),steps,fontsize=12)
ax.set_ylim(33400,34750); style(ax,yl="seller-product pairs")
title(ax,"33,787 pairs generated, not 34,448",
      "661 pairs sold only in cancelled orders or outside the window, so they carry no demand signal")
save(fig,"s2_funnel.png")

# ---------------------------------------------------- 3 THE FIX
fig,ax=plt.subplots(figsize=(10,4.8),facecolor=PAPER)
labels=["Stock drawn at random\n(independent of sales)","Stock derived from each\npair's own sales rate"]
vals=[0.0,10.79]
bars=ax.bar([0,1],vals,color=[GREY,CRIT],width=.46)
for i,v in enumerate(vals):
    ax.text(i,v+.30,f"{v:.1f}%",ha="center",fontsize=20,fontweight="bold",
            color=MUTED if i==0 else CRIT)
ax.text(0,1.35,"rule never fires",ha="center",fontsize=12.5,color=MUTED,style="italic")
ax.text(1,6.0,"966 products\nflagged Urgent",ha="center",fontsize=12.5,color=PAPER,fontweight="bold")
ax.set_xticks([0,1],labels,fontsize=12.5); ax.set_ylim(0,13)
style(ax,yl="% flagged Urgent\n(sufficient-evidence rows)")
title(ax,"Deriving stock from real demand is what makes the rule work",
      "Median days of inventory falls from about 7 years to 76 days")
save(fig,"s3_the_fix.png")

# ---------------------------------------------------- 4 status breakdown
fig,ax=plt.subplots(figsize=(10,3.2),facecolor=PAPER)
order=["Urgent","Monitor","Healthy","Insufficient data"]
cols_=[CRIT,WARN,GOOD,GREY]; left=0
counts=inv.status.value_counts()
for s,c in zip(order,cols_):
    n=counts[s]; pct=100*n/len(inv)
    ax.barh(0,pct,left=left,color=c,height=.5)
    if pct>3:
        ax.text(left+pct/2,0,f"{pct:.1f}%",ha="center",va="center",
                color=PAPER,fontsize=14,fontweight="bold")
    left+=pct
ax.set_xlim(0,100); ax.set_ylim(-1.1,.5); ax.set_yticks([]); style(ax,xl="share of 33,787 rows",grid=None)
ax.legend(handles=[Patch(color=c,label=f"{s}  ({counts[s]:,})") for s,c in zip(order,cols_)],
          frameon=False,fontsize=12,ncol=4,loc="lower center",labelcolor=MUTED,
          bbox_to_anchor=(.5,-.78))
title(ax,"Status breakdown","73.5% lack enough sales evidence to score, so they are labelled, not guessed")
save(fig,"s4_status.png")

# ---------------------------------------------------- 5 seed stability
seeds=pd.DataFrame({"Urgent":[2.944,0.0952],"Monitor":[0.757,0.0320],
                    "Healthy":[22.792,0.0909],"Insufficient data":[73.508,0.0]},
                   index=["mean","std"]).T
fig,ax=plt.subplots(figsize=(10,4.4),facecolor=PAPER)
y=np.arange(len(seeds))[::-1]
ax.barh(y,seeds["mean"],xerr=seeds["std"]*10,color=[CRIT,WARN,GOOD,GREY],height=.55,
        error_kw=dict(ecolor=INK,capsize=7,lw=2))
for i,(name,row) in enumerate(seeds.iterrows()):
    ax.text(row["mean"]+2.2,y[i],f"{row['mean']:.2f}%  ± {row['std']:.3f}",
            va="center",fontsize=13,color=INK)
ax.set_yticks(y,seeds.index,fontsize=13); ax.set_xlim(0,95)
style(ax,xl="share of rows (%)",grid="x")
title(ax,"Conclusions do not depend on one lucky seed",
      "30 seeds  ·  error bars shown at 10x actual size, otherwise they are invisible")
save(fig,"s5_seed_stability.png")

# ---------------------------------------------------- 6 sensitivity
fig,ax=plt.subplots(figsize=(10,4.6),facecolor=PAPER)
lead=["(3, 10)","(5, 20)","(10, 30)"]; urgent=[2.693,2.859,3.016]
safety=["0 days","3 days","7 days"]; urgent_s=[2.969,2.859,2.673]
x=np.arange(3)
ax.plot(x,urgent,marker="o",ms=10,lw=2.6,color=CRIT,label="Longer supplier lead time")
ax.plot(x,urgent_s,marker="s",ms=10,lw=2.6,color=ACCENT,label="More safety-stock days")
for i,(a,b) in enumerate(zip(urgent,urgent_s)):
    ax.text(i,a+.055,f"{a:.2f}%",ha="center",fontsize=12,color=CRIT,fontweight="bold")
    ax.text(i,b-.085,f"{b:.2f}%",ha="center",fontsize=12,color=ACCENT,fontweight="bold")
ax.set_xticks(x,["low","default","high"],fontsize=13)
ax.set_ylim(2.55,3.15); style(ax,xl="parameter setting",yl="% flagged Urgent")
ax.legend(frameon=False,fontsize=12.5,labelcolor=MUTED,loc="center left")
title(ax,"The rule reacts in the directions you would expect",
      "Longer wait for resupply raises urgency  ·  more safety stock lowers it")
save(fig,"s6_sensitivity.png")

# ---------------------------------------------------- 7 anchoring + caveat
served=suff.copy()
served["d"]=pd.qcut(served.daily_sales_rate,10,labels=False,duplicates="drop")
g=served.groupby("d").agg(rp=("reorder_point","mean"),cq=("current_quantity","mean"))
fig,ax=plt.subplots(figsize=(10,4.6),facecolor=PAPER)
w=.38; x=np.arange(len(g))
ax.bar(x-w/2,g.rp,w,color=ACCENT,label="Reorder point")
ax.bar(x+w/2,g.cq,w,color=WARN,label="Current quantity")
ax.set_xticks(x,[f"D{i+1}" for i in range(len(g))],fontsize=12)
ax.axvspan(-0.5,7.5,color=GREY,alpha=.18,zorder=0)
ax.text(3.5,4.4,"88% of rows floor at reorder point = 1\n(honest limitation)",
        ha="center",fontsize=12,color=MUTED,style="italic")
style(ax,xl="real sales-rate decile, slowest to fastest",yl="mean units")
ax.legend(frameon=False,fontsize=12.5,labelcolor=MUTED,loc="upper left")
title(ax,"Synthetic stock is anchored to real sales speed",
      "Spearman rho = 0.55 between real sales rate and reorder point")
save(fig,"s7_anchoring.png")
print("\nall slide charts written to reports/slides/")
