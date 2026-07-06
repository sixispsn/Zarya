"""Слой аннотаций по ГОСТ 2.316-2008: линия-выноска (наклон+излом) -> полка,
надпись над полкой (<=2 строк), стрелка на конце у трубы; контроль пересечений."""
import math
from fontTools.ttLib import TTFont
import os
def _find_font():
    cands=[os.environ.get("OSIFONT_PATH",""),
           "/root/.fonts/osifont.ttf",
           os.path.expanduser("~/.fonts/osifont.ttf"),
           "/usr/share/fonts/truetype/osifont/osifont.ttf",
           os.path.join(os.path.dirname(__file__),"fonts","osifont.ttf")]
    for p in cands:
        if p and os.path.exists(p): return p
    raise FileNotFoundError("osifont.ttf не найден: задайте OSIFONT_PATH")
FONT_PATH=_find_font()
_ttf=TTFont(FONT_PATH); _upm=_ttf["head"].unitsPerEm
_cmap=_ttf.getBestCmap(); _hmtx=_ttf["hmtx"]
def char_w(ch,sz):
    g=_cmap.get(ord(ch)) or _cmap.get(ord("?"))
    aw=_hmtx[g][0] if g in _hmtx.metrics else _upm*0.5
    return aw/_upm*sz
def text_w(s,sz): return sum(char_w(c,sz) for c in s)
def wrap2(text,max_w,sz):
    """Перенос максимум в 2 строки (ГОСТ). Если не влезает — вернём None."""
    words=text.split(); lines=[]; cur=""
    for wd in words:
        t=(cur+" "+wd).strip()
        if text_w(t,sz)<=max_w or not cur: cur=t
        else:
            lines.append(cur); cur=wd
            if len(lines)==2: return None
    if cur: lines.append(cur)
    return lines if len(lines)<=2 else None

def seg_int(p1,p2,p3,p4):
    def ccw(a,b,c): return (c[1]-a[1])*(b[0]-a[0])>(b[1]-a[1])*(c[0]-a[0])
    return ccw(p1,p3,p4)!=ccw(p2,p3,p4) and ccw(p1,p2,p3)!=ccw(p1,p2,p4)

class Occ:
    def __init__(self,canvas): self.rects=[]; self.lines=[]; self.leaders=[]; self.cw,self.ch=canvas
    def add(self,x1,y1,x2,y2): self.rects.append((x1,y1,x2,y2))
    def add_line(self,x1,y1,x2,y2,kind="pipe"): self.lines.append((x1,y1,x2,y2,kind))
    def _seg_rect(self,x1,y1,x2,y2,box):
        bx1,by1,bx2,by2=box
        # отрезок внутри прямоугольника?
        if bx1<=x1<=bx2 and by1<=y1<=by2: return True
        if bx1<=x2<=bx2 and by1<=y2<=by2: return True
        # пересечение со сторонами
        for e in (((bx1,by1),(bx2,by1)),((bx2,by1),(bx2,by2)),
                  ((bx2,by2),(bx1,by2)),((bx1,by2),(bx1,by1))):
            if seg_int((x1,y1),(x2,y2),e[0],e[1]): return True
        # коллинеарное наложение (гориз/верт)
        if y1==y2 and by1-2<=y1<=by2+2 and max(x1,x2)>bx1 and min(x1,x2)<bx2: return True
        if x1==x2 and bx1-2<=x1<=bx2+2 and max(y1,y2)>by1 and min(y1,y2)<by2: return True
        return False
    def hit_rect(self,box):
        x1,y1,x2,y2=box
        if x1<4 or y1<4 or x2>self.cw-4 or y2>self.ch-4: return True
        for a1,b1,a2,b2 in self.rects:
            if x1<a2 and x2>a1 and y1<b2 and y2>b1: return True
        for lx1,ly1,lx2,ly2,_k in self.lines:
            if self._seg_rect(lx1,ly1,lx2,ly2,(x1-2,y1-2,x2+2,y2+2)): return True
        return False
    def leader_ok(self,pts,tb=None):
        """выноска не пересекает чужую геометрию и др. выноски.
        Линии, на которых лежит стартовая точка (anchor), не считаем —
        старт на трубе даёт ложное пересечение."""
        ax,ay=pts[0]
        def on_line(x1,y1,x2,y2,px,py,eps=2.5):
            if min(x1,x2)-eps<=px<=max(x1,x2)+eps and min(y1,y2)-eps<=py<=max(y1,y2)+eps:
                d=abs((x2-x1)*(y1-py)-(x1-px)*(y2-y1))/max(math.hypot(x2-x1,y2-y1),1e-9)
                return d<eps
            return False
        segs=list(zip(pts,pts[1:]))
        for item in self.lines:
            x1,y1,x2,y2,k=item
            if k=="bld": continue              # строительные линии пересекать можно
            if on_line(x1,y1,x2,y2,ax,ay): continue
            for a,b in segs:
                if seg_int(a,b,(x1,y1),(x2,y2)): return False
        for (x1,y1,x2,y2) in self.leaders:
            if on_line(x1,y1,x2,y2,ax,ay): continue
            for a,b in segs:
                if seg_int(a,b,(x1,y1),(x2,y2)): return False
        # наклонный участок не должен резать тексты (свой tb проверяется с усадкой)
        incline=segs[0]
        for (rx1,ry1,rx2,ry2) in self.rects:
            box=(rx1+3,ry1+3,rx2-3,ry2-3)
            if box[0]>=box[2] or box[1]>=box[3]: continue
            for e in ((box[0],box[1],box[2],box[1]),(box[2],box[1],box[2],box[3]),
                      (box[2],box[3],box[0],box[3]),(box[0],box[3],box[0],box[1])):
                if seg_int(incline[0],incline[1],(e[0],e[1]),(e[2],e[3])): return False
        return True
    def add_leader(self,pts):
        for a,b in zip(pts,pts[1:]): self.leaders.append((a[0],a[1],b[0],b[1]))

def arrow(x,y,ang,s=7):
    a1=ang+math.radians(150); a2=ang-math.radians(150)
    return (f'<path d="M{x},{y} L{x+s*math.cos(a1):.1f},{y+s*math.sin(a1):.1f} '
            f'L{x+s*math.cos(a2):.1f},{y+s*math.sin(a2):.1f} Z" fill="#000"/>')

def place(occ,anchor,text,base_sz=12,widths=(210,150,100),shelf_pad=6,
          arrow_at_anchor=False,step=12,maxr=430,minr=44):
    """anchor — точка на трубе (линия контура) -> стрелка. Полка горизонтальная,
    текст над полкой (<=2 строк)."""
    ax,ay=anchor; best=None; bestcost=1e18
    for mw in widths:
        for sz in (base_sz,base_sz-1,base_sz-2):
            lines=wrap2(text,mw,sz)
            if not lines: continue
            tw=max(text_w(l,sz) for l in lines); th=len(lines)*sz*1.2
            shelf=tw+2*shelf_pad
            # рамка текста над полкой — ищем только в окрестности anchor
            gy0=max(6,int(ay-maxr-th)); gy1=min(int(occ.ch-th-24),int(ay+maxr))
            gx0=max(6,int(ax-maxr-shelf)); gx1=min(int(occ.cw-shelf-6),int(ax+maxr))
            for gy in range(gy0,gy1,step):
                for side in (-1,1):        # полка влево/вправо от излома
                    for gx in range(gx0,gx1,step):
                        # излом (колено) и полка
                        shelf_x1,shelf_x2=gx,gx+shelf
                        shelf_y=gy+sz+4                     # полка под 1-й строкой
                        knee=(gx if side>0 else gx+shelf, shelf_y)
                        tb=(gx-2,gy-2,gx+shelf+2,shelf_y+ (sz+4 if len(lines)>1 else 2))
                        if occ.hit_rect(tb): continue
                        pts=[(ax,ay),knee,((shelf_x2) if side>0 else shelf_x1, knee[1])]
                        ll=math.hypot(knee[0]-ax,knee[1]-ay)
                        if ll>maxr or ll<minr: continue    # не лепить над объектом
                        ang_deg=abs(math.degrees(math.atan2(knee[1]-ay,knee[0]-ax)))
                        ang_deg=min(ang_deg,180-ang_deg)   # 0..90 от горизонтали
                        if not (20<=ang_deg<=70): continue # наклон, не верт./гориз.
                        sb=(tb[0]+3,tb[1]+3,tb[2]-3,tb[3]-3)
                        self_cut=False
                        for e in ((sb[0],sb[1],sb[2],sb[1]),(sb[2],sb[1],sb[2],sb[3]),
                                  (sb[2],sb[3],sb[0],sb[3]),(sb[0],sb[3],sb[0],sb[1])):
                            if seg_int(pts[0],pts[1],(e[0],e[1]),(e[2],e[3])): self_cut=True; break
                        if self_cut: continue
                        if not occ.leader_ok(pts): continue
                        cost=ll
                        if cost<bestcost: bestcost=cost; best=(lines,sz,tb,knee,shelf_x1,shelf_x2,side)
            if best: break
        if best: break
    if not best: return None,None
    lines,sz,tb,knee,sx1,sx2,side=best
    occ.add(*tb); occ.add_leader([(ax,ay),knee,(sx2 if side>0 else sx1,knee[1])])
    g=[]
    shelf_y=knee[1]
    ang=math.atan2(shelf_y-ay,knee[0]-ax)
    # наклон труба->излом, затем ГОРИЗОНТАЛЬНАЯ полка
    g.append(f'<line x1="{ax}" y1="{ay}" x2="{knee[0]}" y2="{shelf_y}" stroke="#000" stroke-width="1.2"/>')
    g.append(f'<line x1="{sx1}" y1="{shelf_y}" x2="{sx2}" y2="{shelf_y}" stroke="#000" stroke-width="1.2"/>')
    if arrow_at_anchor: g.append(arrow(ax,ay,ang))
    # ГОСТ: 1-я строка НАД полкой, 2-я — ПОД полкой (полка подчёркивает верхнюю)
    g.append(f'<text x="{sx1+shelf_pad}" y="{shelf_y-4}" font-family="osifont" font-size="{sz}" fill="#000">{lines[0]}</text>')
    if len(lines)>1:
        g.append(f'<text x="{sx1+shelf_pad}" y="{shelf_y+sz+2}" font-family="osifont" font-size="{sz}" fill="#000">{lines[1]}</text>')
    return "".join(g),tb

if __name__=="__main__":
    import cairosvg
    W,Hc=1000,520; occ=Occ((W,Hc))
    body=['<rect width="%d" height="%d" fill="white"/>'%(W,Hc)]
    # труба-контур (горизонталь) + вертикали
    occ.add_line(60,300,940,300); body.append('<line x1="60" y1="300" x2="940" y2="300" stroke="#000" stroke-width="2.4"/>')
    for vx in (300,360,600):
        occ.add_line(vx,120,vx,300); body.append(f'<line x1="{vx}" y1="120" x2="{vx}" y2="300" stroke="#000" stroke-width="2.4"/>')
    labels=[((300,300),"Ввод водопровода 2x\u2205200, абс. отметка 146,8 (-2,200)"),
            ((360,300),"На пожаротушение нижней зоны 2x\u2205200"),
            ((600,300),"Насосная станция ПОЗ")]
    placed=[]
    for anc,t in labels:
        s,box=place(occ,anc,t)
        if s: body.append(s); placed.append(box); print("OK  ",t[:34])
        else: print("FAIL",t[:34])
    def ov(a,b): return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]
    bad=sum(1 for i in range(len(placed)) for j in range(i+1,len(placed)) if ov(placed[i],placed[j]))
    print("overlaps:",bad)
    cairosvg.svg2png(bytestring=('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">'%(W,Hc)+"".join(body)+"</svg>").encode(),write_to="annotate_gost.png",scale=2)
