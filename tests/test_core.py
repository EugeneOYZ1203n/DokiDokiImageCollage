import json
import os

import numpy as np
import pytest
from PIL import Image

from collage import assign, colors, crop, geometry, instagram
from collage.config import Settings
from collage.models import LabelledTemplate, Placeholder, load_labelled, rename_labelled, save_labelled
from collage.render import render
from collage.storage import Store


def solid(rgb, size=(64, 64)):
    return Image.new("RGB", size, rgb)


# ---- models / config
def test_labelled_roundtrip(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 50)).save(t)
    lt = LabelledTemplate(str(t), (100, 50), [Placeholder(1, 0, 0, 10, 10, "a"), Placeholder(2, 20, 5, 30, 20, "b")])
    p = tmp_path / "x.json"
    save_labelled(lt, str(p))
    back = load_labelled(str(p))
    assert back.size == (100, 50) and [q.tag for q in back.placeholders] == ["a", "b"]
    new = rename_labelled(str(p), "renamed")
    assert new.endswith("renamed.json") and load_labelled(new).template_path == str(t)


def test_settings_tolerant_load():
    s = Settings.from_dict({"max_recent_folders": 999, "crop_tolerance": "bad", "instagram_size_mode": "x",
                            "remember_window": "yes", "unknown": 1})
    assert s.max_recent_folders == 50 and s.crop_tolerance == 0.10
    assert s.instagram_size_mode == "ask" and s.remember_window is True


# ---- storage
def test_recent_folders_mru_dedupe_cap(tmp_path):
    st = Store(str(tmp_path / "data"))
    st.settings.max_recent_folders = 3
    for n in "abcd":
        st.add_recent(str(tmp_path / n))
    st.add_recent(str(tmp_path / "c"))
    assert [os.path.basename(p) for p in st.recent_folders] == ["c", "d", "b"]
    assert [os.path.basename(p) for p in Store(str(tmp_path / "data")).recent_folders] == ["c", "d", "b"]  # persisted
    st.set_settings(Settings(max_recent_folders=1))
    assert len(st.recent_folders) == 1
    st.clear_recent()
    assert st.recent_folders == []


def test_store_recovers_from_corrupt_settings(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_text("{not json")
    st = Store(str(root))
    assert st.recent_folders == [] and st.settings == Settings()
    assert (root / "settings.json.bad").exists()


def test_save_copies_template_image_beside_json(tmp_path):
    src = tmp_path / "elsewhere" / "t.png"
    src.parent.mkdir()
    Image.new("RGB", (100, 50)).save(src)
    store_dir = tmp_path / "templates"
    lt = LabelledTemplate(str(src), (100, 50), [Placeholder(1, 0, 0, 10, 10, "a")])
    jp = store_dir / "x.json"
    save_labelled(lt, str(jp))
    assert json.loads(jp.read_text())["template"] == "t.png"
    src.unlink()  # original gone: copy keeps the template usable
    back = load_labelled(str(jp))
    assert os.path.exists(back.template_path) and os.path.dirname(back.template_path) == str(store_dir)


def test_load_legacy_absolute_path_falls_back_beside_json(tmp_path):
    Image.new("RGB", (10, 10)).save(tmp_path / "t.png")
    jp = tmp_path / "x.json"
    jp.write_text(json.dumps({"template": "Z:\\gone\\t.png", "size": [10, 10], "placeholders": []}))
    assert load_labelled(str(jp)).template_path == str(tmp_path / "t.png")


def test_migrate_legacy_once(tmp_path):
    legacy = tmp_path / "labelled_templates"
    legacy.mkdir()
    img = tmp_path / "t.png"
    Image.new("RGB", (100, 50)).save(img)
    save_labelled(LabelledTemplate(str(img), (100, 50), [Placeholder(1, 0, 0, 10, 10, "a")]), str(legacy / "old.json"))
    st = Store(str(tmp_path / "data"))
    assert st.migrate_legacy([str(legacy)]) == 1
    assert os.path.exists(os.path.join(st.templates_dir, "old.json"))
    assert st.migrate_legacy([str(legacy)]) == 0


# ---- geometry
def test_snap_move_to_neighbour_edge():
    r = geometry.snap_move((103, 50, 50, 50), [(0, 0, 100, 100)], (400, 400), 8)
    assert r[0] == 100


def test_resize_snaps_edge_and_dimension():
    others = [(200, 0, 100, 100)]
    r = geometry.resize_rect((0, 0, 50, 50), "e", 197, 25, others, (400, 400), False, 8)
    assert r[0] + r[2] == 200
    r = geometry.resize_rect((0, 0, 50, 50), "e", 96, 25, [(300, 300, 100, 40)], (400, 400), False, 8)
    assert r[2] == 100  # width snapped to neighbour width


@pytest.mark.parametrize("handle", geometry.HANDLES)
def test_resize_locked_keeps_aspect_inbounds(handle):
    r = geometry.resize_rect((100, 100, 80, 40), handle, 370, 330, [], (400, 400), True, 8)
    assert r[2] / r[3] == pytest.approx(2.0, rel=1e-6)
    assert r[0] >= -1e-9 and r[1] >= -1e-9 and r[0] + r[2] <= 400 + 1e-9 and r[1] + r[3] <= 400 + 1e-9


def test_set_field_lock():
    assert geometry.set_field((0, 0, 100, 50), "w", 200, True, (1000, 1000)) == (0, 0, 200, 100)
    r = geometry.set_field((0, 0, 100, 50), "w", 200, False, (1000, 1000))
    assert r == (0, 0, 200, 50)
    r = geometry.set_field((0, 0, 100, 50), "h", 80, True, (1000, 1000))
    assert r[2] / r[3] == pytest.approx(2.0)


def test_hit_test():
    assert geometry.hit_test((10, 10, 100, 100), 10, 10, 5) == "nw"
    assert geometry.hit_test((10, 10, 100, 100), 60, 60, 5) == "move"
    assert geometry.hit_test((10, 10, 100, 100), 300, 300, 5) is None


# ---- crop
def test_centered_and_clamp():
    b = crop.centered_box(200, 100, 1.0)
    assert (b.x, b.y, b.w, b.h) == (50, 0, 100, 100)
    z = crop.zoom(b, 2.0, 200, 100)
    assert z.w == 50 and z.w / z.h == pytest.approx(1.0)
    p = crop.pan(z, -999, -999, 200, 100)
    assert p.x == 0 and p.y == 0


def test_resize_corner_inside():
    b = crop.CropBox(50, 0, 100, 100)
    r = crop.resize_corner(b, "nw", 100, 40, 200, 100)
    assert r.w / r.h == pytest.approx(1.0)
    assert r.x + r.w == pytest.approx(150) and r.y + r.h == pytest.approx(100)


def test_best_crop_contains_blob():
    img = Image.new("RGB", (400, 200), (120, 120, 120))
    for x in range(330, 380):
        for y in range(80, 130):
            img.putpixel((x, y), (255, 0, 0))
    box = crop.auto_crop(img, 1.0, 0.1)
    assert box.x + box.w >= 380 and box.w / box.h == pytest.approx(1.0)


def test_auto_crop_aspect_fit_is_centered():
    img = solid((10, 20, 30), (105, 100))
    box = crop.auto_crop(img, 1.0, 0.10)
    assert box.w == pytest.approx(100) and box.x == pytest.approx(2.5)


# ---- colours / assign
def test_hue_scheme_fit():
    red, blue, cyan = (255, 0, 0), (0, 0, 255), (0, 255, 255)
    labs = colors.rgb_to_lab([red, blue, cyan])
    errs = colors.scheme_errors(labs, "complementary", [red])
    assert errs[0] < 1 and errs[2] < 1 and errs[1] > 30


def test_best_scheme_any_prefers_simple_when_equal():
    labs = colors.rgb_to_lab([(255, 0, 0), (250, 10, 10), (240, 20, 0)])
    scheme, base, _ = colors.best_scheme_any(labs, 3)
    assert scheme == "monotone"


def test_gradient_assign_orders_pool():
    greys = [(v, v, v) for v in (200, 20, 120, 255, 70)]
    labs = colors.rgb_to_lab(greys)
    phs = [Placeholder(i, i * 100, 0, 100, 100, "t") for i in range(5)]
    p = assign.AutoParams(mode="gradient", start=(0, 0, 0), end=(255, 255, 255), max_delta=200)
    idx = assign.assign_gradient(labs, assign.gradient_targets(phs, (500, 100), p), 200, True)
    assert [greys[i][0] for i in idx] == sorted(g[0] for g in greys)


def test_gradient_radial_center_darkest():
    phs = [Placeholder(0, 200, 200, 100, 100, "t"), Placeholder(1, 0, 0, 100, 100, "t")]
    p = assign.AutoParams(mode="gradient", gradient_kind="radial", start=(0, 0, 0), end=(255, 255, 255))
    t = assign.gradient_targets(phs, (500, 500), p)
    assert t[0][0] < t[1][0]


def test_gradient_strict_nofit():
    labs = colors.rgb_to_lab([(255, 0, 0)] * 3)
    t = np.array([colors.rgb_to_lab((0, 0, 255))] * 3)
    with pytest.raises(assign.NoFit):
        assign.assign_gradient(labs, t, 35, True)
    assert len(assign.assign_gradient(labs, t, 35, False)) == 3


def make_pool(tmp_path, colors_):
    paths = []
    for i, c in enumerate(colors_):
        p = tmp_path / f"{i}.png"
        solid(c).save(p)
        paths.append(str(p))
    return paths, colors.rgb_to_lab(colors_)


def test_auto_assign_scheme_and_no_reuse(tmp_path):
    cols = [(255, 0, 0), (250, 20, 20), (0, 0, 255), (0, 255, 0)]
    pools = {"t": make_pool(tmp_path, cols)}
    lt = LabelledTemplate("x", (200, 100), [Placeholder(1, 0, 0, 100, 100, "t"), Placeholder(2, 100, 0, 100, 100, "t")])
    p = assign.AutoParams(mode="scheme", scheme="monotone", bases=[(255, 0, 0)], tolerance=20, seed=1)
    out = assign.auto_assign(lt, pools, p)
    assert len(set(out.values())) == 2 and all(pools["t"][0].index(v) in (0, 1) for v in out.values())
    p.bases = [(0, 0, 255)]
    p.tolerance = 10
    with pytest.raises(assign.NoFit):
        assign.auto_assign(lt, pools, p)


def test_pool_too_small(tmp_path):
    pools = {"t": make_pool(tmp_path, [(1, 2, 3)])}
    lt = LabelledTemplate("x", (200, 100), [Placeholder(1, 0, 0, 10, 10, "t"), Placeholder(2, 10, 0, 10, 10, "t")])
    with pytest.raises(assign.PoolTooSmall):
        assign.auto_assign(lt, pools, assign.AutoParams())


def test_suggestions(tmp_path):
    pools = {"t": make_pool(tmp_path, [(255, 0, 0), (250, 30, 0), (0, 0, 255)])}
    lt = LabelledTemplate("x", (200, 100), [Placeholder(1, 0, 0, 10, 10, "t"), Placeholder(2, 10, 0, 10, 10, "t")])
    s = assign.suggest(lt, pools, assign.AutoParams(mode="scheme", scheme="monotone"))
    assert colors.rgb_hue(s.bases[0]) < 20 or colors.rgb_hue(s.bases[0]) > 340
    g = assign.suggest(lt, pools, assign.AutoParams(mode="gradient"))
    assert g.start != g.end


# ---- render / instagram
def test_render_places_crop(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(t)
    src = tmp_path / "s.png"
    img = Image.new("RGB", (40, 20), (255, 0, 0))
    for x in range(20, 40):
        for y in range(20):
            img.putpixel((x, y), (0, 255, 0))
    img.save(src)
    lt = LabelledTemplate(str(t), (100, 100), [Placeholder(1, 10, 10, 20, 20, "a")])
    out = render(lt, {1: (str(src), crop.CropBox(20, 0, 20, 20))})
    assert out.size == (100, 100) and out.getpixel((15, 15))[:3] == (0, 255, 0) and out.getpixel((50, 50))[:3] == (0, 0, 0)


def test_instagram():
    assert instagram.check_size(1080, 1350).ok
    r = instagram.check_size(800, 800)
    assert not r.ok and r.nearest_size == (1080, 1080) and r.warnings
    assert not instagram.check_size(1080, 1000).ok


# ---- split / align / distribute / padding
def test_split_grid_tiles_exactly():
    cells = geometry.split_grid((10, 20, 100, 70), 2, 3, 0)
    assert len(cells) == 6
    assert sum(c[2] * c[3] for c in cells) == 100 * 70
    assert min(c[0] for c in cells) == 10 and max(c[0] + c[2] for c in cells) == 110
    assert min(c[1] for c in cells) == 20 and max(c[1] + c[3] for c in cells) == 90
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def test_split_grid_gap_and_errors():
    cells = geometry.split_grid((0, 0, 110, 50), 1, 3, 5)
    assert [c[0] for c in cells] == [0, 40, 80] or cells[1][0] - (cells[0][0] + cells[0][2]) == 5
    assert cells[-1][0] + cells[-1][2] == 110
    with pytest.raises(ValueError):
        geometry.split_grid((0, 0, 10, 10), 0, 2)
    with pytest.raises(ValueError):
        geometry.split_grid((0, 0, 10, 10), 20, 1)


def test_align():
    rs = [(0, 0, 10, 10), (50, 20, 20, 30)]
    assert [r[0] for r in geometry.align(rs, "left")] == [0, 0]
    assert [r[0] + r[2] for r in geometry.align(rs, "right")] == [70, 70]
    mid = geometry.align(rs, "middle")
    assert mid[0][1] + 5 == mid[1][1] + 15
    assert geometry.align(rs, "top", (0, 5, 100, 100))[1][1] == 5


def test_distribute():
    rs = [(0, 0, 10, 10), (15, 0, 10, 10), (90, 0, 10, 10)]
    out = geometry.distribute(rs, "h")
    gaps = [out[1][0] - (out[0][0] + out[0][2]), out[2][0] - (out[1][0] + out[1][2])]
    assert gaps[0] == pytest.approx(gaps[1]) and out[0][0] == 0 and out[2][0] == 90
    assert geometry.distribute(rs[:2], "h") == rs[:2]


def test_group_snap():
    dx, dy = geometry.snap_move_group([(0, 0, 10, 10), (20, 0, 10, 10)], 68, 0, [(100, 0, 50, 50)], (400, 400), 5)
    assert dx == 70 and dy == 0


def test_padding_roundtrip_and_old_json(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 50)).save(t)
    lt = LabelledTemplate(str(t), (100, 50), [Placeholder(1, 0, 0, 40, 40, "a", padding=5)])
    p = tmp_path / "x.json"
    save_labelled(lt, str(p))
    assert load_labelled(str(p)).placeholders[0].padding == 5
    d = json.loads(p.read_text())
    del d["placeholders"][0]["padding"]
    p.write_text(json.dumps(d))
    assert load_labelled(str(p)).placeholders[0].padding == 0
    assert Placeholder(1, 0, 0, 40, 40, "a", padding=999).inset[2] >= 1


def test_render_respects_padding(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(t)
    src = tmp_path / "s.png"
    Image.new("RGB", (20, 20), (255, 0, 0)).save(src)
    lt = LabelledTemplate(str(t), (100, 100), [Placeholder(1, 10, 10, 40, 40, "a", padding=10)])
    out = render(lt, {1: (str(src), crop.CropBox(0, 0, 20, 20))})
    assert out.getpixel((12, 12))[:3] == (0, 0, 0) and out.getpixel((30, 30))[:3] == (255, 0, 0)


# ---- crop guardrails
import math
import random as _random

from collage.imageio import open_reduced
from collage.saliency import saliency_map


@pytest.mark.parametrize("size", [(1, 1), (7, 300), (300, 6), (5000, 40), (40, 5000), (200, 100)])
@pytest.mark.parametrize("ar", [0.05, 0.5, 1.0, 2.0, 20.0])
def test_fit_box_always_valid(size, ar):
    iw, ih = size
    for box in (crop.CropBox(-50, -50, 1e6, 1e6), crop.CropBox(float("nan"), 0, 5, 5), crop.CropBox(iw, ih, 3, 3),
                crop.CropBox(0, 0, 0, 0), crop.CropBox(iw / 2, ih / 2, 1, 1)):
        b = crop.fit_box(box, iw, ih, ar)
        assert b.w / b.h == pytest.approx(ar, rel=1e-9)
        assert b.x >= 0 and b.y >= 0 and b.x + b.w <= iw + 1e-9 and b.y + b.h <= ih + 1e-9


@pytest.mark.parametrize("size", [(7, 300), (300, 7), (4000, 100), (100, 4000), (1, 50)])
@pytest.mark.parametrize("ar", [0.5, 1.0, 3.0])
def test_best_crop_exact_aspect_extreme_images(size, ar):
    img = Image.new("RGB", size, (90, 90, 90))
    b = crop.auto_crop(img, ar, 0.0)
    assert b.w / b.h == pytest.approx(ar, rel=1e-6)
    assert b.x >= 0 and b.y >= 0 and b.x + b.w <= size[0] + 1e-6 and b.y + b.h <= size[1] + 1e-6
    assert saliency_map(img).shape[0] >= 2


def test_crop_ops_fuzz_stay_inside():
    rnd = _random.Random(5)
    for _ in range(1500):
        iw, ih = rnd.randint(20, 3000), rnd.randint(20, 3000)
        ar = rnd.choice([0.2, 1, 4])
        b = crop.centered_box(iw, ih, ar)
        for _ in range(6):
            k = rnd.choice("zcp")
            if k == "z":
                b = crop.zoom(b, rnd.uniform(0.3, 3), iw, ih, (rnd.uniform(-50, iw + 50), rnd.uniform(-50, ih + 50)))
            elif k == "p":
                b = crop.pan(b, rnd.uniform(-9e3, 9e3), rnd.uniform(-9e3, 9e3), iw, ih)
            else:
                b = crop.resize_corner(b, rnd.choice(["nw", "ne", "se", "sw"]), rnd.uniform(-100, iw + 100), rnd.uniform(-100, ih + 100), iw, ih)
            assert b.x >= -1e-9 and b.y >= -1e-9 and b.x + b.w <= iw + 1e-6 and b.y + b.h <= ih + 1e-6
            assert b.w / b.h == pytest.approx(ar, rel=1e-6)


def test_render_never_raises_on_edge_boxes(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (300, 300)).save(t)
    rnd = _random.Random(2)
    for n in range(60):
        w, h = rnd.randint(300, 4000), rnd.randint(300, 4000)
        p = tmp_path / f"{n}.jpg"
        Image.new("RGB", (w, h), (10, 200, 10)).save(p)
        img, f = open_reduced(str(p), 800)
        ow, oh = w, h
        ar = rnd.choice([0.5, 1, 2])
        box = crop.pan(crop.centered_box(ow, oh, ar), rnd.choice([-1e9, 1e9]), rnd.choice([-1e9, 1e9]), ow, oh)
        lt = LabelledTemplate(str(t), (300, 300), [Placeholder(1, 0, 0, int(100 * ar), 100, "a")])
        out = render(lt, {1: (str(p), box)}, getter=lambda q: (img, f))
        assert out.size == (300, 300)


def test_render_bad_box_falls_back_and_reports_unreadable(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(t)
    src = tmp_path / "s.png"
    Image.new("RGB", (40, 40), (255, 0, 0)).save(src)
    lt = LabelledTemplate(str(t), (100, 100), [Placeholder(1, 0, 0, 20, 20, "a"), Placeholder(2, 50, 0, 20, 20, "a")])
    errs = []
    out = render(lt, {1: (str(src), crop.CropBox(float("nan"), 0, 10, 10)), 2: (str(tmp_path / "missing.png"), crop.CropBox(0, 0, 10, 10))}, errors=errs)
    assert out.getpixel((5, 5))[:3] == (255, 0, 0)
    assert len(errs) == 1 and "missing.png" in errs[0]


def test_load_labelled_clamps_and_validates(tmp_path):
    t = tmp_path / "t.png"
    Image.new("RGB", (100, 100)).save(t)
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"template": str(t), "size": [100, 100], "placeholders": [
        {"id": 1, "x": -10, "y": 90, "w": 50, "h": 50, "tag": "a"},
        {"id": 2, "x": 500, "y": 500, "w": 5, "h": 5, "tag": "a"}]}))
    lt = load_labelled(str(p))
    assert len(lt.placeholders) == 1 and lt.placeholders[0].rect == (0, 90, 40, 10)
    p.write_text(json.dumps({"template": str(t)}))
    with pytest.raises(ValueError):
        load_labelled(str(p))
