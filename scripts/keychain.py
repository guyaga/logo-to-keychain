#!/usr/bin/env python3
"""
logo-to-keychain engine — turn a logo (or a flat cartoon) into a print-ready,
multi-colour keychain: watertight .stl + a Bambu Studio .3mf with each colour
pre-assigned to a filament, plus a preview PNG.

Two modes:
  logo    : a logo/wordmark silhouette -> chosen shape + raised logo (+ tagline/ring)
  mascot  : a flat cartoon image -> colour-segmented layered charm

Method: direct geometric extrusion (shapely + trimesh + manifold3d). NOT Meshy —
flat charms extrude cleanly (watertight, flat-backed, exact edges); Meshy is for
organic/sculptural objects instead.

Deps: pip install numpy pillow opencv-python shapely trimesh manifold3d mapbox_earcut
"""
import os, math, json, zipfile, argparse, numpy as np, cv2, trimesh
from shapely.geometry import Polygon, Point, box, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from shapely.affinity import translate, scale as sscale, rotate
from PIL import Image, ImageDraw, ImageFont

# ---------- generic geometry helpers ----------
def as_polys(geom):
    if geom is None or geom.is_empty: return []
    if isinstance(geom, Polygon): return [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []

def mask_to_polys(mask, pitch=0.1, min_mm2=0.0):
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None: return []
    hier = hier[0]; H = mask.shape[0]; outers, holes = {}, {}
    for i, hh in enumerate(hier):
        pts = cv2.approxPolyDP(cnts[i], 0.8, True)
        if len(pts) < 3: continue
        r = pts.reshape(-1, 2).astype(float); r = np.column_stack([r[:, 0]*pitch, (H-1-r[:, 1])*pitch])
        if hh[3] == -1: outers[i] = r; holes.setdefault(i, [])
        else: holes.setdefault(hh[3], []).append(r)
    out = []
    for i, sh in outers.items():
        p = Polygon(sh, holes.get(i, []))
        if not p.is_valid: p = p.buffer(0)
        if p.area > max(pitch*pitch*10, min_mm2): out.append(p)
    return out

def fit(polys, target_w=None, target_h=None, cx=0.0, cy=0.0):
    polys = [p for p in polys if not p.is_empty]
    u = unary_union(polys); x0, y0, x1, y1 = u.bounds
    f = (target_w/(x1-x0)) if target_w else (target_h/(y1-y0))
    polys = [sscale(p, f, f, origin=(0, 0)) for p in polys]
    u = unary_union(polys); x0, y0, x1, y1 = u.bounds
    return [translate(p, cx-(x0+x1)/2, cy-(y0+y1)/2) for p in polys]

def fit_box(polys, max_w, max_h, cx=0.0, cy=0.0):
    """Scale to fit INSIDE a max_w x max_h box (whichever dim binds), then centre."""
    polys = [p for p in polys if not p.is_empty]
    u = unary_union(polys); x0, y0, x1, y1 = u.bounds
    f = min(max_w/(x1-x0), max_h/(y1-y0))
    polys = [sscale(p, f, f, origin=(0, 0)) for p in polys]
    u = unary_union(polys); x0, y0, x1, y1 = u.bounds
    return [translate(p, cx-(x0+x1)/2, cy-(y0+y1)/2) for p in polys]

def hexp(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
def rrect(w, h, r): return box(-w/2, -h/2, w/2, h/2).buffer(-r, join_style=1).buffer(r, join_style=1)
def circle(R): return Point(0, 0).buffer(R, 128)
def hexagon(R): return Polygon([(R*math.cos(math.radians(a)), R*math.sin(math.radians(a))) for a in (90, 150, 210, 270, 330, 30)])
def shield(w, h): return Polygon([(-w/2, h/2), (w/2, h/2), (w/2, -h/8), (0, -h/2), (-w/2, -h/8)]).buffer(-2, 1).buffer(2, 1)
def rtri(s): return Polygon([(-s/2, -s*0.43), (s/2, -s*0.43), (0, s*0.57)]).buffer(-4, 1).buffer(4, 1)
def ring(Ro, Ri): return circle(Ro).difference(circle(Ri))
def tri(size, cx, cy, up=True):
    s = 1 if up else -1
    return Polygon([(cx-size/2, cy-s*size*0.45), (cx+size/2, cy-s*size*0.45), (cx, cy+s*size*0.55)])
def loop_top(shape, topy, ro=6.0, rh=3.0):
    c = (0, topy + ro - 2.6)
    return shape.union(Point(c).buffer(ro, 80)).difference(Point(c).buffer(rh, 80))

def font(px):
    for f in ("consolab.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try: return ImageFont.truetype(f, px)
        except Exception:
            try: return ImageFont.truetype(os.path.join(r"C:\Windows\Fonts", f), px)
            except Exception: pass
    return ImageFont.load_default()

def text_polys(txt, w=None, h=None, cx=0, cy=0):
    f = font(240); l, t, r, b = ImageDraw.Draw(Image.new("L", (4, 4))).textbbox((0, 0), txt, font=f)
    im = Image.new("L", (r-l+30, b-t+30), 0); ImageDraw.Draw(im).text((15-l, 15-t), txt, font=f, fill=255)
    return fit(mask_to_polys(np.array(im)), target_w=w, target_h=h, cx=cx, cy=cy)

def arched(txt, radius, ch):
    f = font(240); adv = ImageDraw.Draw(Image.new("L", (4, 4))).textlength("M", font=f)
    bb = f.getbbox("M"); pitch = ch/(bb[3]-bb[1]); step = adv*pitch*1.16
    items = []
    for cc in txt:
        if cc == " ": items.append(None); continue
        l, t, r, b = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), cc, font=f)
        im = Image.new("L", (r-l+20, b-t+20), 0); ImageDraw.Draw(im).text((10-l, 10-t), cc, font=f, fill=255)
        items.append(fit(mask_to_polys(np.array(im)), target_h=ch))
    total = step*len(items); s = -total/2 + step/2; out = []
    for gp in items:
        phi = s/radius
        if gp:
            for p in gp: out.append(translate(rotate(p, math.degrees(phi), origin=(0, 0)), radius*math.sin(phi), -radius*math.cos(phi)))
        s += step
    return out

def load_logo_polys(path):
    """Return shapely polys for a logo: use alpha if present, else key out white bg."""
    im = Image.open(path).convert("RGBA"); a = np.array(im)
    alpha = a[..., 3]
    if (alpha < 250).mean() > 0.02:        # has real transparency
        mask = (alpha > 60).astype(np.uint8)*255
    else:                                   # opaque -> key out near-white
        mn = a[..., :3].min(axis=2); mask = (mn < 235).astype(np.uint8)*255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask_to_polys(mask)

# ---------- shape builders (logo mode) ----------
def build_logo(style, LOGO, tagline, width):
    """Each shape fits the logo INSIDE a safe box so it never runs past the edge/ring."""
    def lb(mw, mh, cx=0, cy=0): return fit_box(LOGO, mw, mh, cx, cy)
    d = {"base": [], "logo": [], "accent": []}
    if style == "baseball":
        R = width/2; Ri = R-6.5                       # inside the ring
        d["base"] = [loop_top(circle(R), R)]
        d["accent"] = [ring(R-2.5, R-6.5)] + (arched(tagline, R-9.5, 4.0) if tagline else [])
        d["logo"] = lb(2*Ri*0.80, Ri*0.92, cy=(Ri*0.16 if tagline else 0))
    elif style == "circle":
        R = width/2; d["base"] = [loop_top(circle(R), R)]
        if tagline:
            d["logo"] = lb(R*1.45, R*0.80, cy=R*0.24)
            d["accent"] = [box(-R*0.5, -R*0.34, R*0.5, -R*0.30)] + text_polys(tagline, w=R*0.95, cy=-R*0.55)
        else:
            d["logo"] = lb(R*1.55, R*0.95)
    elif style == "tag":
        w = width; h = width*0.46; d["base"] = [loop_top(rrect(w, h, 6), h/2)]
        if tagline:
            d["logo"] = lb(w*0.80, h*0.50, cy=h*0.16); d["accent"] = text_polys(tagline, w=w*0.46, cy=-h*0.32)
        else:
            d["logo"] = lb(w*0.82, h*0.66)
    elif style == "dogtag":
        w = width*0.55; h = width
        base = rrect(w, h, 8).difference(Point(0, h/2-8).buffer(min(3.2, w*0.08), 64))
        d["base"] = [base]; d["logo"] = lb(w*0.80, h*0.26, cy=h*0.08)
        if tagline: d["accent"] = [tri(8, 0, h*0.30)] + text_polys(tagline, w=w*0.72, cy=-h*0.27)
    elif style == "hexagon":
        R = width/2; inr = R-5
        d["base"] = [loop_top(hexagon(R), R*0.86)]; d["accent"] = [hexagon(R-3).difference(hexagon(R-6))]
        d["logo"] = lb(inr*1.28, inr*0.82)
    elif style == "shield":
        w = width; h = width*1.2; d["base"] = [loop_top(shield(w, h), h/2)]
        d["accent"] = [tri(11, 0, h*0.27)] + (text_polys(tagline, w=w*0.55, cy=-h*0.30) if tagline else [])
        d["logo"] = lb(w*0.72, h*0.30, cy=-h*0.02)
    elif style == "diecut":
        s = fit(LOGO, target_w=width, cy=0)
        plate = unary_union(s).buffer(3.8, join_style=1)           # clean uniform sticker border
        if isinstance(plate, MultiPolygon): plate = max(plate.geoms, key=lambda g: g.area)
        ext = np.asarray(plate.exterior.coords)                    # plate top near centre
        near = np.abs(ext[:, 0]) < width*0.16
        ty = ext[near, 1].max() if near.any() else ext[:, 1].max()
        ro, rh = 5.5, 2.8; cyl = ty + ro + 1.5                     # ring sits clearly above the word
        neck = box(-2.6, ty-2.0, 2.6, cyl)                         # small bridge connecting word -> ring
        body = unary_union([plate, neck, Point(0, cyl).buffer(ro, 80)]).difference(Point(0, cyl).buffer(rh, 80))
        d["base"] = [body]; d["logo"] = s
    elif style == "triangle":
        S = width; base = rtri(S); d["base"] = [loop_top(base, base.bounds[3])]
        d["logo"] = lb(S*0.48, S*0.26, cy=-S*0.03)                 # sit in the wider lower-centre, clear of the slanted edges
        if tagline: d["accent"] = text_polys(tagline, w=S*0.46, cy=-S*0.27)
    elif style == "squircle":
        w = width; base = rrect(w, w, w*0.28); d["base"] = [loop_top(base, w/2)]
        d["logo"] = lb(w*0.78, w*0.42, cy=w*0.04)
        d["accent"] = [Polygon([(w/2-15, w/2), (w/2, w/2), (w/2, w/2-15)]).intersection(base)] + (text_polys(tagline, w=w*0.55, cy=-w*0.27) if tagline else [])
    else:
        raise SystemExit(f"unknown style: {style}")
    return d

# ---------- extrude + export ----------
def extrude(polys, h, z0=0.0):
    ms = []
    for p in polys:
        for q in as_polys(p):
            try:
                m = trimesh.creation.extrude_polygon(q, height=h, engine='earcut')
                if z0: m.apply_translation([0, 0, z0])
                ms.append(m)
            except Exception as e: print("  skip poly:", e)
    return trimesh.util.concatenate(ms) if ms else None

def mesh_xml(m, oid):
    vs = "".join(f'<vertex x="{x:.3f}" y="{y:.3f}" z="{z:.3f}"/>' for x, y, z in m.vertices)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    return f'<object id="{oid}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'

def write_3mf(path, parts):     # parts: [(name, (r,g,b), mesh), ...]
    ids = list(range(2, 2+len(parts)))
    res = "".join(mesh_xml(m, oid) for oid, (_, _, m) in zip(ids, parts))
    comps = "".join(f'<component objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' for oid in ids)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n<resources>\n'+res+
    '<object id="1" type="model"><components>'+comps+'</components></object>\n</resources>\n'
    '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/></build>\n</model>\n')
    msp = "".join(f'    <part id="{oid}" subtype="normal_part">\n      <metadata key="name" value="{nm}"/>\n      <metadata key="extruder" value="{i+1}"/>\n    </part>\n'
                  for i, (oid, (nm, _, _)) in enumerate(zip(ids, parts)))
    ms = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="1">\n    <metadata key="name" value="keychain"/>\n    <metadata key="extruder" value="1"/>\n'+msp+'  </object>\n</config>\n'
    cols = ", ".join('"#%02X%02X%02X"' % tuple(c) for _, c, _ in parts)
    proj = '{\n  "filament_colour": ['+cols+'],\n  "filament_type": ['+", ".join('"PLA"' for _ in parts)+'],\n  "filament_settings_id": ['+", ".join('"Generic PLA"' for _ in parts)+']\n}\n'
    ct = '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n<Default Extension="png" ContentType="image/png"/>\n</Types>\n'
    rels = '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct); z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", ms)
        z.writestr("Metadata/project_settings.config", proj)

def preview(parts, solid, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    cream = (0.937, 0.918, 0.878); L = np.array([-0.4, -0.5, 0.78]); L /= np.linalg.norm(L)
    allt, allc = [], []
    for _, c, m in parts:
        t = m.vertices[m.faces]; sh = (0.5+0.6*np.clip(m.face_normals@L, 0, 1))[:, None]
        allt.append(t); allc.append(np.clip(sh*(np.array(c)/255.0), 0, 1))
    allt = np.concatenate(allt); allc = np.hstack([np.concatenate(allc), np.ones((len(np.concatenate(allc)), 1))])
    b = solid.bounds; fig = plt.figure(figsize=(9, 5), facecolor=cream)
    for i, (el, az) in enumerate([(70, -90), (26, -72)]):
        ax = fig.add_subplot(1, 2, i+1, projection="3d"); ax.set_facecolor(cream)
        ax.add_collection3d(Poly3DCollection(allt, facecolors=allc, linewidths=0))
        ax.set_xlim(b[0, 0], b[1, 0]); ax.set_ylim(b[0, 1], b[1, 1]); ax.set_zlim(b[0, 2], b[1, 2])
        ax.set_box_aspect((b[1, 0]-b[0, 0], b[1, 1]-b[0, 1], (b[1, 2]-b[0, 2])*3))
        ax.view_init(elev=el, azim=az); ax.set_axis_off()
        for pane in (ax.xaxis, ax.yaxis, ax.zaxis): pane.pane.set_visible(False)
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0)
    plt.savefig(path, dpi=120, facecolor=cream); plt.close()

# ---------- mascot mode ----------
def build_mascot(image, palette_hex, charm_h, pt, relief):
    img = cv2.cvtColor(cv2.imread(image), cv2.COLOR_BGR2RGB); H, W = img.shape[:2]
    ff = img.copy(); ffm = np.zeros((H+2, W+2), np.uint8)
    for seed in [(0, 0), (W-1, 0), (0, H-1), (W-1, H-1)]:
        cv2.floodFill(ff, ffm, seed, (0, 0, 0), (16, 16, 16), (16, 16, 16), cv2.FLOODFILL_MASK_ONLY | (255 << 8))
    bg = (ffm[1:-1, 1:-1] > 0) | (img.min(axis=2) > 236)
    fg = (~bg).astype(np.uint8)*255
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1: fg = (lab == 1+np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8)*255
    fgb = fg > 0
    pcols = np.array([hexp(h) for h in palette_hex], np.float32)
    px = img[fgb].astype(np.float32)
    _, kl, ctr = cv2.kmeans(px, min(6, len(palette_hex)+2), None,
                            (cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 4, cv2.KMEANS_PP_CENTERS)
    snap = [int(np.argmin(np.linalg.norm(pcols-c, axis=1))) for c in ctr]
    labimg = -np.ones((H, W), np.int32); flat = labimg[fgb]
    for ci in range(len(ctr)): flat[kl.ravel() == ci] = snap[ci]
    labimg[fgb] = flat
    pitch = charm_h/fgb.any(axis=1).sum(); min_px = int(3.0/(pitch*pitch))
    def drop_small(m):
        nc, ll, s2, _ = cv2.connectedComponentsWithStats(m); o = np.zeros_like(m)
        for c in range(1, nc):
            if s2[c, cv2.CC_STAT_AREA] >= min_px: o[ll == c] = 255
        return o
    region = {}
    for pi in range(len(palette_hex)):
        m = (labimg == pi).astype(np.uint8)*255
        if m.sum() == 0: continue
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)); m = drop_small(m)
        pl = mask_to_polys(m, pitch)
        if pl: region[pi] = pl
    sil = mask_to_polys(fg, pitch)
    allp = sil + [p for v in region.values() for p in v]
    u = unary_union(allp); cx = (u.bounds[0]+u.bounds[2])/2; cy = (u.bounds[1]+u.bounds[3])/2
    sil = [translate(p, -cx, -cy) for p in sil]; region = {k: [translate(p, -cx, -cy) for p in v] for k, v in region.items()}
    topy = u.bounds[3]-cy
    base_poly = unary_union(sil).union(Point(0, topy+3.3).buffer(6.5, 80)).difference(Point(0, topy+3.3).buffer(3.2, 80))
    parts = [("base", hexp(palette_hex[0]), extrude([base_poly], pt))]
    darkest = int(np.argmin([sum(hexp(h)) for h in palette_hex]))
    for pi, pl in region.items():
        if pi == darkest: continue          # darkest colour stays as the base layer
        m = extrude(pl, relief, pt)
        if m is not None: parts.append((f"c{pi}", hexp(palette_hex[pi]), m))
    return parts

# ---------- main ----------
def finish(parts, name, outdir):
    os.makedirs(outdir, exist_ok=True)
    parts = [(nm, c, m) for nm, c, m in parts if m is not None]
    for _, _, m in parts: m.merge_vertices(); m.fix_normals()
    try: solid = trimesh.boolean.union([m for _, _, m in parts], engine='manifold', check_volume=False)
    except Exception as e: print("union fallback:", e); solid = trimesh.util.concatenate([m for _, _, m in parts])
    stl = os.path.join(outdir, name+".stl"); solid.export(stl)
    mf = os.path.join(outdir, name+"_color.3mf"); write_3mf(mf, parts)
    pv = os.path.join(outdir, name+"_preview.png"); preview(parts, solid, pv)
    print(f"  STL : {stl}\n  3MF : {mf}\n  PNG : {pv}")
    print(f"  size: {solid.extents.round(1)} mm | colours: {len(parts)}")

def main():
    ap = argparse.ArgumentParser(description="logo -> printable multi-colour keychain")
    ap.add_argument("--mode", choices=["logo", "mascot"], default="logo")
    ap.add_argument("--image", required=True, help="logo PNG (transparent or white-bg) / flat cartoon for mascot")
    ap.add_argument("--name", default="keychain")
    ap.add_argument("--out", default="./keychains")
    ap.add_argument("--width", type=float, default=70.0, help="overall width/diameter (mm)")
    ap.add_argument("--plate-thick", type=float, default=3.0)
    ap.add_argument("--relief", type=float, default=2.0)
    # logo mode
    ap.add_argument("--style", default="baseball",
                    choices=["baseball", "circle", "tag", "dogtag", "hexagon", "shield", "diecut", "triangle", "squircle"])
    ap.add_argument("--tagline", default="")
    ap.add_argument("--base-color", default="#141414")
    ap.add_argument("--logo-color", default="#F2F1ED")
    ap.add_argument("--accent-color", default="#D43122")
    # mascot mode
    ap.add_argument("--palette", default="#141414,#5F632F,#EBD6AA,#D43122",
                    help="comma hex list; first = base/darkest layer")
    args = ap.parse_args()

    if args.mode == "logo":
        LOGO = load_logo_polys(args.image)
        d = build_logo(args.style, LOGO, args.tagline, args.width)
        base = unary_union(d["base"])
        parts = [("base", hexp(args.base_color), extrude(d["base"], args.plate_thick))]
        for key, col in (("logo", args.logo_color), ("accent", args.accent_color)):
            clipped = []
            for p in d[key]:
                if not p.is_empty: clipped += as_polys(p.intersection(base))
            m = extrude(clipped, args.relief, args.plate_thick) if clipped else None
            if m is not None: parts.append((key, hexp(col), m))
    else:
        parts = build_mascot(args.image, args.palette.split(","), args.width, args.plate_thick, args.relief)

    finish(parts, args.name, args.out)

if __name__ == "__main__":
    main()
