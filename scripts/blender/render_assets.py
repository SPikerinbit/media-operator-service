"""Reproducible Blender 4.5 LTS 3D asset generator for Media Operator.

Run headless:
    blender --background --python scripts/blender/render_assets.py -- --out <staging_dir>

Lighting & camera convention matches frontend/public/workbench/manifest.json:
- Orthographic camera with 12 deg downward inclination
- Warm upper-left key area light, cool-neutral fill, subtle metallic rim
- Transparent film background (Cycles CPU + OpenImageDenoise)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Directory for rendered PNGs")
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--only", default="", help="Comma-separated asset names to render")
    return parser.parse_args(argv)


def reset_scene(res_x=1024, res_y=1024, samples=48):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 3
    scene.cycles.transmission_bounces = 2
    scene.cycles.transparent_max_bounces = 4
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0

    world = bpy.data.worlds.new("StudyWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.88, 0.91, 0.94, 1.0)
        bg.inputs[1].default_value = 0.42
    return scene


def add_study_lights(scene, elevation_scale=1.0):
    def make_area(name, loc, rot_deg, energy, size, color):
        data = bpy.data.lights.new(name=name, type="AREA")
        data.energy = energy
        data.size = size
        data.color = color
        obj = bpy.data.objects.new(name=name, object_data=data)
        scene.collection.objects.link(obj)
        obj.location = loc
        obj.rotation_euler = Euler(tuple(math.radians(a) for a in rot_deg), "XYZ")
        return obj

    # Warm upper-left key light matching the study-room direction
    make_area("KeyLight", (-3.8, -3.2, 4.8 * elevation_scale), (38, -28, -32), 240, 3.2, (1.0, 0.96, 0.90))
    # Soft cool-neutral front-right fill
    make_area("FillLight", (4.2, -3.6, 2.4 * elevation_scale), (56, 20, 42), 95, 4.2, (0.90, 0.95, 1.0))
    # Subtle rear-top rim for brushed metal / wax specular edge
    make_area("RimLight", (1.2, 4.0, 3.6 * elevation_scale), (-44, 0, 165), 115, 2.8, (0.97, 0.98, 1.0))


def add_ortho_camera(scene, ortho_scale=3.0, inclination_deg=12.0, target=(0.0, 0.0, 0.0), dist=8.0):
    cam_data = bpy.data.cameras.new("OrthoCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("OrthoCam", cam_data)
    scene.collection.objects.link(cam)
    rad = math.radians(inclination_deg)
    cam.location = (
        target[0],
        target[1] - dist * math.cos(rad),
        target[2] + dist * math.sin(rad),
    )
    direction = Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    return cam


def set_smooth(obj):
    if obj.type != "MESH":
        return
    for poly in obj.data.polygons:
        poly.use_smooth = True


def link_obj(scene, obj):
    scene.collection.objects.link(obj)
    return obj


def make_principled_mat(
    name,
    color,
    roughness=0.4,
    metallic=0.0,
    coat=0.0,
    coat_roughness=0.15,
    subsurface=0.0,
    noise_scale=0.0,
    bump_strength=0.0,
):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if subsurface > 0 and "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
        if "Subsurface Scale" in bsdf.inputs:
            bsdf.inputs["Subsurface Scale"].default_value = 0.06
    if noise_scale > 0 and bump_strength > 0:
        tex_coord = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = noise_scale
        noise.inputs["Detail"].default_value = 6.0
        noise.inputs["Roughness"].default_value = 0.55
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = bump_strength
        bump.inputs["Distance"].default_value = 0.01
        nt.links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def make_wood_material(name, split_color, dark_color, seed_offset=0.0):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.68

    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Location"].default_value = (seed_offset, seed_offset * 0.7, 0.0)
    mp.inputs["Scale"].default_value = (1.4, 9.5, 9.5)

    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "RINGS"
    wave.rings_direction = "X"
    wave.inputs["Scale"].default_value = 3.2
    wave.inputs["Distortion"].default_value = 4.6
    wave.inputs["Detail"].default_value = 5.0
    wave.inputs["Detail Scale"].default_value = 1.8

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (*dark_color, 1.0)
    ramp.color_ramp.elements[1].position = 0.82
    ramp.color_ramp.elements[1].color = (*split_color, 1.0)

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.14
    bump.inputs["Distance"].default_value = 0.008

    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], wave.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def add_rounded_box(scene, name, size, bevel=0.06, segments=5, location=(0, 0, 0), rotation=(0, 0, 0), mat=None):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.bevel(
        bm,
        geom=list(bm.edges),
        offset=bevel,
        offset_type="OFFSET",
        segments=segments,
        profile=0.5,
        affect="EDGES",
    )
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    if mat:
        obj.data.materials.append(mat)
    set_smooth(obj)
    return link_obj(scene, obj)


def add_cylinder(scene, name, radius, depth, verts=72, bevel=0.0, location=(0, 0, 0), rotation=(0, 0, 0), mat=None):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=verts, radius1=radius, radius2=radius, depth=depth
    )
    if bevel > 0:
        cap_edges = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-4]
        bmesh.ops.bevel(bm, geom=cap_edges, offset=bevel, segments=4, profile=0.5, affect="EDGES")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    if mat:
        obj.data.materials.append(mat)
    set_smooth(obj)
    return link_obj(scene, obj)


def render_to(scene, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------------------
# 1. Wax Seals (Red for Publish, Blue-Slate for Notes) - zero boolean artifacts
# ---------------------------------------------------------------------------
def build_wax_seal(out_dir: Path, samples: int, variant: str):
    scene = reset_scene(1024, 1024, samples)
    add_study_lights(scene, elevation_scale=1.15)
    # Camera looks almost straight at the seal (front-facing on the envelope)
    add_ortho_camera(scene, ortho_scale=2.45, inclination_deg=12.0, target=(0, 0, 0))

    if variant == "wax":
        wax_col = (0.46, 0.11, 0.14)
        crest_col = (0.40, 0.09, 0.12)
        seed = 1.0
    else:
        wax_col = (0.12, 0.30, 0.36)
        crest_col = (0.10, 0.25, 0.31)
        seed = 3.7

    mat_wax = make_principled_mat(
        f"Wax_{variant}", wax_col, roughness=0.28, coat=0.38, coat_roughness=0.18, subsurface=0.22, noise_scale=26.0, bump_strength=0.04
    )
    mat_crest = make_principled_mat(
        f"WaxCrest_{variant}", crest_col, roughness=0.25, coat=0.42, coat_roughness=0.16, subsurface=0.18, noise_scale=30.0, bump_strength=0.03
    )

    # Organic poured wax blob (oriented in XZ plane facing -Y camera)
    mesh = bpy.data.meshes.new("WaxBase")
    bm = bmesh.new()
    rings = 14
    segs = 96
    max_r = 1.02

    def wobble(theta):
        return (
            1.0
            + 0.075 * math.sin(5 * theta + seed)
            + 0.045 * math.cos(7 * theta - seed * 1.4)
            + 0.025 * math.sin(11 * theta + 0.8)
        )

    # Front & back domed surface
    front_center = bm.verts.new((0.0, -0.055, 0.0))
    back_center = bm.verts.new((0.0, 0.09, 0.0))
    ring_verts_f = []
    ring_verts_b = []
    for r_idx in range(1, rings + 1):
        t = r_idx / rings
        row_f = []
        row_b = []
        for s in range(segs):
            th = (2 * math.pi * s) / segs
            rad = max_r * t * (1.0 if t < 0.62 else (1.0 + (wobble(th) - 1.0) * ((t - 0.62) / 0.38) ** 1.3))
            x = rad * math.cos(th)
            z = rad * math.sin(th)
            # Outer poured lip rises into a soft cushion, inner face slightly recessed
            if t < 0.62:
                y_f = -0.055 - 0.008 * math.cos(t / 0.62 * math.pi * 0.5)
            else:
                u = (t - 0.62) / 0.38
                lip = math.sin(u * math.pi)
                y_f = -0.055 - 0.075 * lip + 0.065 * (u ** 3)
            y_b = 0.09 - 0.03 * (t ** 2)
            row_f.append(bm.verts.new((x, y_f, z)))
            row_b.append(bm.verts.new((x, y_b, z)))
        ring_verts_f.append(row_f)
        ring_verts_b.append(row_b)

    # Connect center fans
    for s in range(segs):
        ns = (s + 1) % segs
        bm.faces.new((front_center, ring_verts_f[0][ns], ring_verts_f[0][s]))
        bm.faces.new((back_center, ring_verts_b[0][s], ring_verts_b[0][ns]))
    # Connect rings
    for r_idx in range(rings - 1):
        for s in range(segs):
            ns = (s + 1) % segs
            bm.faces.new((ring_verts_f[r_idx][s], ring_verts_f[r_idx][ns], ring_verts_f[r_idx + 1][ns], ring_verts_f[r_idx + 1][s]))
            bm.faces.new((ring_verts_b[r_idx][ns], ring_verts_b[r_idx][s], ring_verts_b[r_idx + 1][s], ring_verts_b[r_idx + 1][ns]))
    # Stitch outer rim
    for s in range(segs):
        ns = (s + 1) % segs
        bm.faces.new((ring_verts_f[-1][s], ring_verts_f[-1][ns], ring_verts_b[-1][ns], ring_verts_b[-1][s]))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    blob = bpy.data.objects.new("PouredWaxSeal", mesh)
    blob.data.materials.append(mat_wax)
    set_smooth(blob)
    link_obj(scene, blob)

    # Impressed double concentric ring
    for ring_r, tube_r in ((0.60, 0.022), (0.52, 0.011)):
        bpy.ops.mesh.primitive_torus_add(
            major_radius=ring_r,
            minor_radius=tube_r,
            major_segments=96,
            minor_segments=20,
            location=(0.0, -0.068, 0.0),
            rotation=(math.radians(90), 0.0, 0.0),
        )
        tor = bpy.context.active_object
        tor.data.materials.append(mat_crest)
        set_smooth(tor)

    # Clean, solid embossed center crest (zero boolean glitches!)
    if variant == "wax":
        # Stylized embossed paper-plane / dispatch arrow emblem
        curve_data = bpy.data.curves.new("DispatchCrest", "CURVE")
        curve_data.dimensions = "2D"
        curve_data.fill_mode = "BOTH"
        curve_data.extrude = 0.022
        curve_data.bevel_depth = 0.010
        curve_data.bevel_resolution = 4

        # Upper wing
        sp1 = curve_data.splines.new("POLY")
        coords1 = [(-0.26, 0.02), (0.28, 0.20), (-0.06, -0.04)]
        sp1.points.add(len(coords1) - 1)
        for i, (cx, cz) in enumerate(coords1):
            sp1.points[i].co = (cx, cz, 0.0, 1.0)
        sp1.use_cyclic_u = True

        # Lower wing
        sp2 = curve_data.splines.new("POLY")
        coords2 = [(-0.02, -0.09), (0.28, 0.20), (0.04, -0.24)]
        sp2.points.add(len(coords2) - 1)
        for i, (cx, cz) in enumerate(coords2):
            sp2.points[i].co = (cx, cz, 0.0, 1.0)
        sp2.use_cyclic_u = True

        emblem = bpy.data.objects.new("PublishEmblem", curve_data)
        emblem.location = (0.0, -0.072, 0.0)
        emblem.rotation_euler = (math.radians(90), 0.0, 0.0)
        emblem.data.materials.append(mat_crest)
        link_obj(scene, emblem)
    else:
        # Clean embossed fountain-pen nib + bookmark emblem for Notes
        curve_data = bpy.data.curves.new("NotesCrest", "CURVE")
        curve_data.dimensions = "2D"
        curve_data.fill_mode = "BOTH"
        curve_data.extrude = 0.022
        curve_data.bevel_depth = 0.010
        curve_data.bevel_resolution = 4

        sp = curve_data.splines.new("POLY")
        coords = [(0.0, 0.28), (0.18, 0.02), (0.11, -0.22), (-0.11, -0.22), (-0.18, 0.02)]
        sp.points.add(len(coords) - 1)
        for i, (cx, cz) in enumerate(coords):
            sp.points[i].co = (cx, cz, 0.0, 1.0)
        sp.use_cyclic_u = True

        emblem = bpy.data.objects.new("NotesEmblem", curve_data)
        emblem.location = (0.0, -0.072, 0.0)
        emblem.rotation_euler = (math.radians(90), 0.0, 0.0)
        emblem.data.materials.append(mat_crest)
        link_obj(scene, emblem)

        # Tiny recessed center eyelet bead on nib
        add_cylinder(
            scene,
            "NibEye",
            radius=0.042,
            depth=0.055,
            verts=36,
            bevel=0.008,
            location=(0.0, -0.095, 0.04),
            rotation=(math.radians(90), 0.0, 0.0),
            mat=mat_wax,
        )

    render_to(scene, out_dir / f"{variant}-light-beauty.png")
    render_to(scene, out_dir / f"{variant}-light-body.png")


# ---------------------------------------------------------------------------
# 2. Four Smooth Split-Oak Firewood Logs (wood-0..3) - zero jagged sawtooth
# ---------------------------------------------------------------------------
def build_wood_log(out_dir: Path, samples: int, idx: int):
    scene = reset_scene(1024, 1024, samples)
    add_study_lights(scene)
    add_ortho_camera(scene, ortho_scale=3.1, inclination_deg=14.0, target=(0, 0, 0))

    palettes = [
        ((0.52, 0.36, 0.23), (0.28, 0.17, 0.09), (0.14, 0.09, 0.05), -4.0),
        ((0.49, 0.33, 0.21), (0.25, 0.15, 0.08), (0.12, 0.08, 0.05), 3.0),
        ((0.55, 0.38, 0.25), (0.30, 0.18, 0.10), (0.15, 0.10, 0.06), -2.5),
        ((0.46, 0.31, 0.19), (0.23, 0.14, 0.07), (0.11, 0.07, 0.04), 4.5),
    ]
    split_c, dark_c, bark_c, yaw = palettes[idx % 4]
    mat_split = make_wood_material(f"OakSplit_{idx}", split_c, dark_c, seed_offset=idx * 2.3)
    mat_bark = make_principled_mat(f"OakBark_{idx}", bark_c, roughness=0.88, noise_scale=18.0, bump_strength=0.35)

    # Create a clean split quarter-round firewood log along X axis
    length = 2.48
    half_l = length / 2.0
    x_steps = 28
    # Cross-section profile: flat-ish split top, rounded bark underside
    profile_pts = [
        (0.0, 0.34, 0.14),   # top-back
        (0.0, -0.34, 0.12),  # top-front
        (0.0, -0.44, -0.02),
        (0.0, -0.36, -0.22),
        (0.0, -0.14, -0.34),
        (0.0, 0.16, -0.33),
        (0.0, 0.38, -0.20),
        (0.0, 0.44, 0.00),
    ]
    mesh = bpy.data.meshes.new(f"WoodLog_{idx}")
    bm = bmesh.new()
    rings = []
    n_p = len(profile_pts)
    for xi in range(x_steps + 1):
        u = xi / x_steps
        x = -half_l + u * length
        taper = 1.0 - 0.06 * math.sin(u * math.pi + idx * 0.9)
        bend_z = 0.045 * math.sin(u * math.pi * 1.1 + idx)
        ring = []
        for pi, (_, py, pz) in enumerate(profile_pts):
            # Subtle organic variation on bark vertices only
            bark_jitter = 0.0 if pi < 2 else 0.025 * math.sin(u * 12.0 + pi * 2.1 + idx)
            ring.append(bm.verts.new((x, py * taper + bark_jitter, pz * taper + bend_z + bark_jitter * 0.6)))
        rings.append(ring)

    # Side faces
    for xi in range(x_steps):
        for pi in range(n_p):
            np = (pi + 1) % n_p
            f = bm.faces.new((rings[xi][pi], rings[xi + 1][pi], rings[xi + 1][np], rings[xi][np]))
            f.material_index = 0 if pi == 0 else 1

    # End caps (smoothly capped)
    f_left = bm.faces.new(list(reversed(rings[0])))
    f_left.material_index = 0
    f_right = bm.faces.new(rings[-1])
    f_right.material_index = 0

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # Bevel only the end-cap and top split-plane perimeter edges so bark stays cleanly dark & organic
    sharp_edges = [e for e in bm.edges if e.calc_face_angle(0.0) > math.radians(48)]
    bmesh.ops.bevel(bm, geom=sharp_edges, offset=0.028, segments=3, profile=0.5, affect="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        center = f.calc_center_median()
        normal = f.normal
        # Split top face or end-grain caps use split oak; curved underside/front bark uses dark oak bark
        if abs(normal.x) > 0.55 or (normal.z > 0.42 and center.z > 0.02):
            f.material_index = 0
        else:
            f.material_index = 1
    bm.to_mesh(mesh)
    bm.free()

    log = bpy.data.objects.new(f"Wood_{idx}", mesh)
    log.data.materials.append(mat_split)
    log.data.materials.append(mat_bark)
    log.rotation_euler = (math.radians(18), math.radians(yaw * 0.6), math.radians(yaw + (12 if idx % 2 == 0 else -10)))
    set_smooth(log)
    link_obj(scene, log)

    render_to(scene, out_dir / f"wood-{idx}-light-beauty.png")
    render_to(scene, out_dir / f"wood-{idx}-light-body.png")


# ---------------------------------------------------------------------------
# 3. Smooth Brushed-Metal Trash Bin (body + front occlusion split)
# ---------------------------------------------------------------------------
def build_trash_bin(out_dir: Path, samples: int):
    scene = reset_scene(1024, 1024, samples)
    add_study_lights(scene)
    add_ortho_camera(scene, ortho_scale=3.45, inclination_deg=12.0, target=(0, 0, 0.05))

    mat_slate = make_principled_mat(
        "TrashSlate", (0.27, 0.37, 0.42), roughness=0.44, metallic=0.18, coat=0.12, noise_scale=85.0, bump_strength=0.035
    )
    mat_inner = make_principled_mat("TrashInner", (0.20, 0.28, 0.32), roughness=0.55, metallic=0.12)
    mat_rim = make_principled_mat("TrashRim", (0.64, 0.66, 0.65), roughness=0.26, metallic=0.82, noise_scale=120.0, bump_strength=0.015)

    def make_half_bin(name, start_deg, end_deg, include_bottom=False):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        segs = 64
        r_bot = 0.63
        r_top = 0.87
        thick = 0.035
        z_bot = -0.92
        z_top = 0.90

        outer_bot, outer_top, inner_top, inner_bot = [], [], [], []
        for i in range(segs + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * (i / segs))
            ca, sa = math.cos(ang), math.sin(ang)
            outer_bot.append(bm.verts.new((r_bot * ca, r_bot * sa, z_bot)))
            outer_top.append(bm.verts.new((r_top * ca, r_top * sa, z_top)))
            inner_top.append(bm.verts.new(((r_top - thick) * ca, (r_top - thick) * sa, z_top)))
            inner_bot.append(bm.verts.new(((r_bot - thick) * ca, (r_bot - thick) * sa, z_bot + 0.04)))

        for i in range(segs):
            # Outer wall
            f1 = bm.faces.new((outer_bot[i], outer_bot[i + 1], outer_top[i + 1], outer_top[i]))
            f1.material_index = 0
            # Inner wall
            f2 = bm.faces.new((inner_top[i], inner_top[i + 1], inner_bot[i + 1], inner_bot[i]))
            f2.material_index = 1
            # Top rolled lip
            f3 = bm.faces.new((outer_top[i], outer_top[i + 1], inner_top[i + 1], inner_top[i]))
            f3.material_index = 2

        if include_bottom:
            center_b = bm.verts.new((0.0, 0.0, z_bot + 0.04))
            # Full floor disc
            full_pts = []
            for i in range(96):
                a = 2 * math.pi * i / 96
                full_pts.append(bm.verts.new(((r_bot - 0.01) * math.cos(a), (r_bot - 0.01) * math.sin(a), z_bot + 0.04)))
            for i in range(96):
                f = bm.faces.new((center_b, full_pts[i], full_pts[(i + 1) % 96]))
                f.material_index = 1

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        for m in (mat_slate, mat_inner, mat_rim):
            obj.data.materials.append(m)
        set_smooth(obj)
        return link_obj(scene, obj)

    def make_rim_band(name, start_deg, end_deg):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        segs = 64
        r_mid = 0.872
        z_hi = 0.92
        z_lo = 0.78
        thick = 0.042
        ob, ot, it, ib = [], [], [], []
        for i in range(segs + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * (i / segs))
            ca, sa = math.cos(ang), math.sin(ang)
            ob.append(bm.verts.new(((r_mid - 0.016) * ca, (r_mid - 0.016) * sa, z_lo)))
            ot.append(bm.verts.new(((r_mid + 0.008) * ca, (r_mid + 0.008) * sa, z_hi)))
            it.append(bm.verts.new(((r_mid - thick) * ca, (r_mid - thick) * sa, z_hi)))
            ib.append(bm.verts.new(((r_mid - thick) * ca, (r_mid - thick) * sa, z_lo)))
        for i in range(segs):
            bm.faces.new((ob[i], ob[i + 1], ot[i + 1], ot[i]))
            bm.faces.new((ot[i], ot[i + 1], it[i + 1], it[i]))
            bm.faces.new((it[i], it[i + 1], ib[i + 1], ib[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(mat_rim)
        set_smooth(obj)
        return link_obj(scene, obj)

    # Back half (0..180 deg = +Y rear) & Front half (180..360 deg = -Y front facing camera)
    back_body = make_half_bin("TrashBack", 0.0, 180.0, include_bottom=True)
    back_rim = make_rim_band("TrashRimBack", 0.0, 180.0)
    front_body = make_half_bin("TrashFront", 180.0, 360.0, include_bottom=False)
    front_rim = make_rim_band("TrashRimFront", 180.0, 360.0)

    # Beauty (all visible)
    render_to(scene, out_dir / "trash-light-beauty.png")
    # Body (only back half + interior)
    front_body.hide_render = True
    front_rim.hide_render = True
    render_to(scene, out_dir / "trash-light-body.png")
    # Front (only front occlusion lip)
    front_body.hide_render = False
    front_rim.hide_render = False
    back_body.hide_render = True
    back_rim.hide_render = True
    render_to(scene, out_dir / "trash-light-front.png")


# ---------------------------------------------------------------------------
# 4. Studio Desk TV / Monitor Bezel (transparent 16:9 screen aperture)
# ---------------------------------------------------------------------------
def build_desk_tv_frame(out_dir: Path, samples: int):
    # 1280 x 840 aspect -> clean monitor chassis with exact inner screen window
    scene = reset_scene(1280, 840, samples)
    add_study_lights(scene, elevation_scale=1.1)
    add_ortho_camera(scene, ortho_scale=4.55, inclination_deg=4.5, target=(0, 0, -0.04))

    mat_case = make_principled_mat("TVCase", (0.77, 0.72, 0.63), roughness=0.42, metallic=0.06, coat=0.14, noise_scale=60.0, bump_strength=0.025)
    mat_trim = make_principled_mat("TVTrim", (0.48, 0.42, 0.34), roughness=0.38, metallic=0.35)
    mat_metal = make_principled_mat("TVMetal", (0.72, 0.68, 0.60), roughness=0.25, metallic=0.82)
    mat_dark = make_principled_mat("TVDark", (0.16, 0.18, 0.20), roughness=0.50, metallic=0.15)
    mat_foot = make_principled_mat("TVFoot", (0.36, 0.29, 0.22), roughness=0.48, metallic=0.12)

    # Monolithic beveled frame mesh (outer rect minus inner 16:9 screen aperture) -> zero coplanar overlap!
    def add_hollow_frame(name, ox, oz_bot, oz_top, ix, iz_bot, iz_top, depth, y_center, bevel, mat):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        hy = depth * 0.5
        # 4 outer corners + 4 inner corners at front (-hy) and back (+hy)
        def ring_at(y):
            o0 = bm.verts.new((-ox, y, oz_bot))
            o1 = bm.verts.new((ox, y, oz_bot))
            o2 = bm.verts.new((ox, y, oz_top))
            o3 = bm.verts.new((-ox, y, oz_top))
            i0 = bm.verts.new((-ix, y, iz_bot))
            i1 = bm.verts.new((ix, y, iz_bot))
            i2 = bm.verts.new((ix, y, iz_top))
            i3 = bm.verts.new((-ix, y, iz_top))
            return [o0, o1, o2, o3], [i0, i1, i2, i3]

        fo, fi = ring_at(y_center - hy)
        bo, bi = ring_at(y_center + hy)
        for k in range(4):
            nk = (k + 1) % 4
            # Front bezel quads
            bm.faces.new((fo[k], fo[nk], fi[nk], fi[k]))
            # Back bezel quads
            bm.faces.new((bo[nk], bo[k], bi[k], bi[nk]))
            # Outer perimeter
            bm.faces.new((bo[k], bo[nk], fo[nk], fo[k]))
            # Inner aperture wall
            bm.faces.new((fi[k], fi[nk], bi[nk], bi[k]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=5, profile=0.5, affect="EDGES")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(mat)
        set_smooth(obj)
        return link_obj(scene, obj)

    # Outer chassis: X [-1.93, 1.93], Z [-1.18, 1.39]; Aperture: X [-1.72, 1.72] (3.44), Z [-0.76, 1.18] (1.94 -> 16:9)
    add_hollow_frame("TVChassis", 1.93, -1.18, 1.39, 1.72, -0.76, 1.18, 0.56, 0.0, 0.045, mat_case)
    # Recessed dark inner bezel ring sitting cleanly inside the aperture lip
    add_hollow_frame("TVInnerBezel", 1.74, -0.78, 1.20, 1.69, -0.73, 1.15, 0.16, -0.17, 0.012, mat_dark)

    # Brushed bronze/brass accent strip on chin
    add_rounded_box(scene, "ChinAccent", (3.44, 0.05, 0.03), bevel=0.008, location=(0.0, -0.28, -0.82), mat=mat_trim)

    # Speaker louver slots on right side of chin
    for i in range(9):
        add_rounded_box(
            scene,
            f"Grille_{i}",
            (0.032, 0.06, 0.14),
            bevel=0.006,
            location=(0.82 + i * 0.062, -0.275, -0.98),
            mat=mat_dark,
        )

    # Tactile knurled metallic rotary dial on bottom-right
    add_cylinder(
        scene,
        "DialBase",
        radius=0.115,
        depth=0.09,
        verts=48,
        bevel=0.018,
        location=(1.56, -0.29, -0.98),
        rotation=(math.radians(90), 0.0, 0.0),
        mat=mat_metal,
    )
    add_cylinder(
        scene,
        "DialCap",
        radius=0.088,
        depth=0.04,
        verts=48,
        bevel=0.012,
        location=(1.56, -0.33, -0.98),
        rotation=(math.radians(90), 0.0, 0.0),
        mat=mat_trim,
    )

    # Left-side recessed LED bezel ring
    add_cylinder(
        scene,
        "LedRing",
        radius=0.048,
        depth=0.04,
        verts=32,
        bevel=0.008,
        location=(-1.58, -0.28, -0.98),
        rotation=(math.radians(90), 0.0, 0.0),
        mat=mat_trim,
    )

    # Sturdy walnut/bronze desk pedestal foot
    add_rounded_box(scene, "StandNeck", (1.28, 0.34, 0.14), bevel=0.025, location=(0.0, 0.04, -1.22), mat=mat_foot)
    add_rounded_box(scene, "StandBase", (2.15, 0.46, 0.09), bevel=0.025, location=(0.0, 0.02, -1.31), mat=mat_foot)

    render_to(scene, out_dir / "desk-tv-frame.png")


# ---------------------------------------------------------------------------
# 5. Shredder 3-Mode Machined Metal Switch Plate (aligned below shredder)
# ---------------------------------------------------------------------------
def build_shred_switch_plate(out_dir: Path, samples: int):
    scene = reset_scene(960, 220, samples)
    add_study_lights(scene, elevation_scale=1.1)
    add_ortho_camera(scene, ortho_scale=4.35, inclination_deg=5.0, target=(0, 0, 0))

    mat_plate = make_principled_mat("SwitchSlate", (0.28, 0.38, 0.43), roughness=0.40, metallic=0.22, coat=0.14, noise_scale=70.0, bump_strength=0.03)
    mat_trough = make_principled_mat("SwitchTrough", (0.14, 0.20, 0.24), roughness=0.52, metallic=0.18)
    mat_rivet = make_principled_mat("SwitchRivet", (0.72, 0.75, 0.76), roughness=0.22, metallic=0.88)

    # Main beveled steel housing
    add_rounded_box(scene, "SwitchPlate", (4.10, 0.26, 0.88), bevel=0.055, location=(0.0, 0.0, 0.0), mat=mat_plate)
    # Recessed dark inner switch channel
    add_rounded_box(scene, "SwitchChannel", (3.64, 0.10, 0.66), bevel=0.028, location=(0.0, -0.10, 0.0), mat=mat_trough)

    # Four machined silver rivets in the corners
    for rx in (-1.93, 1.93):
        for rz in (-0.31, 0.31):
            add_cylinder(
                scene,
                f"Rivet_{rx}_{rz}",
                radius=0.036,
                depth=0.05,
                verts=24,
                bevel=0.012,
                location=(rx, -0.135, rz),
                rotation=(math.radians(90), 0.0, 0.0),
                mat=mat_rivet,
            )

    render_to(scene, out_dir / "shred-switch-plate.png")


# ---------------------------------------------------------------------------
# 6. 3D Enamel Platform Badges (Douyin, Xiaohongshu, Bilibili, WeRead)
# ---------------------------------------------------------------------------
def build_platform_badge(out_dir: Path, samples: int, site: str, color):
    scene = reset_scene(256, 256, samples)
    add_study_lights(scene, elevation_scale=1.15)
    add_ortho_camera(scene, ortho_scale=1.75, inclination_deg=8.0, target=(0, 0, 0))

    mat_rim = make_principled_mat("BadgeRim", (0.76, 0.72, 0.64), roughness=0.25, metallic=0.72)
    mat_enamel = make_principled_mat(f"Enamel_{site}", color, roughness=0.20, coat=0.65, coat_roughness=0.10)

    # Subtle satin-brass bezel base + glossy ceramic/enamel tile top
    add_rounded_box(scene, "Bezel", (1.42, 0.26, 1.42), bevel=0.18, segments=6, location=(0.0, 0.04, 0.0), mat=mat_rim)
    add_rounded_box(scene, "Tile", (1.30, 0.24, 1.30), bevel=0.16, segments=6, location=(0.0, -0.04, 0.0), mat=mat_enamel)

    render_to(scene, out_dir / f"badge-{site}.png")


# ---------------------------------------------------------------------------
# 7. Studio 3D Application Icon (Media Operator - Mailbox + Wax-Sealed Letter)
# ---------------------------------------------------------------------------
def build_app_icon(out_dir: Path, samples: int):
    scene = reset_scene(1024, 1024, samples)
    add_study_lights(scene, elevation_scale=1.25)
    add_ortho_camera(scene, ortho_scale=3.15, inclination_deg=15.0, target=(0, 0, 0.02))

    mat_tile = make_principled_mat("IconTile", (0.24, 0.34, 0.40), roughness=0.34, metallic=0.26, coat=0.22, noise_scale=65.0, bump_strength=0.02)
    mat_brass = make_principled_mat("IconBrass", (0.78, 0.61, 0.30), roughness=0.26, metallic=0.86)
    mat_paper = make_principled_mat("IconPaper", (0.94, 0.90, 0.82), roughness=0.62, noise_scale=80.0, bump_strength=0.025)
    mat_paper_back = make_principled_mat("IconPaperBack", (0.85, 0.79, 0.69), roughness=0.68)
    mat_wax = make_principled_mat("IconWax", (0.58, 0.12, 0.16), roughness=0.24, coat=0.45, subsurface=0.24)
    mat_slot = make_principled_mat("IconSlot", (0.07, 0.10, 0.13), roughness=0.65)

    # Rounded macOS/Win11 squircle-like studio badge backing
    add_rounded_box(scene, "IconBrassRim", (2.66, 0.34, 2.66), bevel=0.44, segments=8, location=(0.0, 0.14, 0.0), mat=mat_brass)
    add_rounded_box(scene, "IconBase", (2.50, 0.38, 2.50), bevel=0.40, segments=8, location=(0.0, 0.04, 0.0), mat=mat_tile)

    # Recessed mailbox slot near top
    add_rounded_box(scene, "SlotBar", (1.82, 0.16, 0.24), bevel=0.05, location=(0.0, -0.14, 0.64), mat=mat_slot)
    add_rounded_box(scene, "SlotBrassLip", (1.92, 0.10, 0.07), bevel=0.02, location=(0.0, -0.17, 0.78), mat=mat_brass)

    # Warm cream envelope emerging crisply from the slot, tilted 3 deg for lively silhouette
    env_rot = (0.0, math.radians(-3.0), 0.0)
    add_rounded_box(scene, "EnvBody", (1.72, 0.16, 1.18), bevel=0.045, location=(0.0, -0.24, -0.18), rotation=env_rot, mat=mat_paper)

    # Triangular envelope flap relief on front
    curve = bpy.data.curves.new("IconFlap", "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.extrude = 0.028
    curve.bevel_depth = 0.015
    curve.bevel_resolution = 4
    sp = curve.splines.new("POLY")
    for i, (cx, cz) in enumerate([(-0.82, 0.40), (0.82, 0.40), (0.0, -0.22)]):
        if i > 0:
            sp.points.add(1)
        sp.points[i].co = (cx, cz, 0.0, 1.0)
    sp.use_cyclic_u = True
    flap_obj = bpy.data.objects.new("EnvFlap", curve)
    flap_obj.location = (0.0, -0.34, -0.02)
    flap_obj.rotation_euler = (math.radians(90), math.radians(-3.0), 0.0)
    flap_obj.data.materials.append(mat_paper_back)
    link_obj(scene, flap_obj)

    # Prominent crimson wax seal right at the focal point
    add_cylinder(
        scene,
        "WaxDisc",
        radius=0.38,
        depth=0.14,
        verts=64,
        bevel=0.045,
        location=(0.02, -0.40, -0.24),
        rotation=(math.radians(90), 0.0, 0.0),
        mat=mat_wax,
    )
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.25,
        minor_radius=0.028,
        major_segments=64,
        minor_segments=18,
        location=(0.02, -0.47, -0.24),
        rotation=(math.radians(90), 0.0, 0.0),
    )
    ring = bpy.context.active_object
    ring.data.materials.append(mat_brass)
    set_smooth(ring)

    # Four subtle corner rivets on the slate tile
    for rx in (-0.98, 0.98):
        for rz in (-0.98, 0.98):
            add_cylinder(
                scene,
                f"IconRivet_{rx}_{rz}",
                radius=0.048,
                depth=0.06,
                verts=24,
                bevel=0.015,
                location=(rx, -0.16, rz),
                rotation=(math.radians(90), 0.0, 0.0),
                mat=mat_brass,
            )

    render_to(scene, out_dir / "app-icon.png")


# ---------------------------------------------------------------------------
# 8. Precision Study Desk Mailbox with Flush Color-Matched 3D Hinged Flap
# ---------------------------------------------------------------------------
def build_mailbox(out_dir: Path, samples: int):
    scene = reset_scene(1024, 1024, samples)
    add_study_lights(scene, elevation_scale=1.08)
    cam = add_ortho_camera(scene, ortho_scale=3.95, inclination_deg=12.0, target=(0.0, 0.0, -0.02))

    # Unified satin-matte slate-teal enamel shared by cabinet, faceplate AND hinged flap -> 100% color unity
    mat_enamel = make_principled_mat(
        "MailboxEnamel", (0.24, 0.35, 0.40), roughness=0.38, metallic=0.22, coat=0.18, coat_roughness=0.20, noise_scale=75.0, bump_strength=0.022
    )
    mat_trim = make_principled_mat(
        "MailboxTrim", (0.17, 0.25, 0.29), roughness=0.34, metallic=0.32, coat=0.10, noise_scale=90.0, bump_strength=0.016
    )
    mat_cavity = make_principled_mat(
        "MailboxCavity", (0.028, 0.038, 0.046), roughness=0.82, metallic=0.04
    )
    mat_plaque = make_principled_mat(
        "MailboxPlaque", (0.64, 0.62, 0.58), roughness=0.32, metallic=0.52, coat=0.08, noise_scale=130.0, bump_strength=0.014
    )
    mat_rivet = make_principled_mat(
        "MailboxRivet", (0.74, 0.76, 0.75), roughness=0.24, metallic=0.86
    )
    mat_pin = make_principled_mat(
        "MailboxPin", (0.13, 0.16, 0.19), roughness=0.34, metallic=0.62
    )
    mat_foot = make_principled_mat(
        "MailboxFoot", (0.08, 0.10, 0.12), roughness=0.72, metallic=0.08
    )

    def add_hollow_plate(name, ox, oz_bot, oz_top, ix, iz_bot, iz_top, depth, y_center, bevel, mat):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        hy = depth * 0.5

        def ring_at(y):
            o0 = bm.verts.new((-ox, y, oz_bot))
            o1 = bm.verts.new((ox, y, oz_bot))
            o2 = bm.verts.new((ox, y, oz_top))
            o3 = bm.verts.new((-ox, y, oz_top))
            i0 = bm.verts.new((-ix, y, iz_bot))
            i1 = bm.verts.new((ix, y, iz_bot))
            i2 = bm.verts.new((ix, y, iz_top))
            i3 = bm.verts.new((-ix, y, iz_top))
            return [o0, o1, o2, o3], [i0, i1, i2, i3]

        fo, fi = ring_at(y_center - hy)
        bo, bi = ring_at(y_center + hy)
        for k in range(4):
            nk = (k + 1) % 4
            bm.faces.new((fo[k], fo[nk], fi[nk], fi[k]))
            bm.faces.new((bo[nk], bo[k], bi[k], bi[nk]))
            bm.faces.new((bo[k], bo[nk], fo[nk], fo[k]))
            bm.faces.new((fi[k], fi[nk], bi[nk], bi[k]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=4, profile=0.5, affect="EDGES")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(mat)
        # Keep large flat front/back planes crisp (zero diagonal shading artifacts) while bevels stay silky smooth
        for poly in obj.data.polygons:
            poly.use_smooth = abs(poly.normal.y) < 0.985 and abs(poly.normal.z) < 0.985 and abs(poly.normal.x) < 0.985
        return link_obj(scene, obj)

    body_objs = []
    front_objs = []
    flap_objs = []
    slot_back_objs = []
    slot_front_objs = []

    # --- Body: cabinet walls, overhanging beveled roof lid, base plinth, feet, recessed dark throat ---
    # Side walls, back wall, floor (leave open front cavity behind faceplate)
    body_objs.append(add_rounded_box(scene, "MailboxBackWall", (3.20, 0.16, 1.72), bevel=0.03, location=(0.0, 0.50, -0.02), mat=mat_enamel))
    body_objs.append(add_rounded_box(scene, "MailboxLeftWall", (0.16, 1.10, 1.72), bevel=0.03, location=(-1.53, 0.03, -0.02), mat=mat_enamel))
    body_objs.append(add_rounded_box(scene, "MailboxRightWall", (0.16, 1.10, 1.72), bevel=0.03, location=(1.53, 0.03, -0.02), mat=mat_enamel))
    body_objs.append(add_rounded_box(scene, "MailboxBottomFloor", (3.24, 1.14, 0.13), bevel=0.035, location=(0.0, 0.02, -0.84), mat=mat_enamel))
    # Subtle dark seam groove under top roof lid
    body_objs.append(add_rounded_box(scene, "MailboxLidSeam", (3.16, 1.08, 0.05), bevel=0.01, location=(0.0, 0.02, 0.82), mat=mat_trim))
    # Architectural overhanging beveled roof lid
    body_objs.append(add_rounded_box(scene, "MailboxRoof", (3.30, 1.24, 0.18), bevel=0.048, segments=6, location=(0.0, 0.00, 0.91), mat=mat_enamel))
    # Low-profile desk feet
    body_objs.append(add_rounded_box(scene, "MailboxFootL", (0.42, 0.68, 0.08), bevel=0.02, location=(-1.16, 0.02, -0.92), mat=mat_foot))
    body_objs.append(add_rounded_box(scene, "MailboxFootR", (0.42, 0.68, 0.08), bevel=0.02, location=(1.16, 0.02, -0.92), mat=mat_foot))
    # Deep recessed shadow cavity behind the letter slot
    body_objs.append(add_rounded_box(scene, "MailboxCavityInterior", (2.88, 0.86, 1.50), bevel=0.01, location=(0.0, 0.02, -0.02), mat=mat_cavity))

    # --- Front faceplate: monolithic hollow frame with precision rectangular letter slot ---
    # Outer: X [-1.52, 1.52], Z [-0.79, 0.80]; Aperture: X [-1.24, 1.24] (2.48), Z [0.24, 0.54] (0.30)
    front_objs.append(add_hollow_plate("MailboxFrontFace", 1.52, -0.79, 0.80, 1.24, 0.24, 0.54, 0.12, -0.54, 0.018, mat_enamel))
    # Precision recessed slot bezel collar lining the inside of the aperture
    front_objs.append(add_hollow_plate("MailboxSlotCollar", 1.28, 0.20, 0.58, 1.236, 0.242, 0.538, 0.16, -0.45, 0.008, mat_trim))
    # Subtle lower faceplate trim border strip
    front_objs.append(add_rounded_box(scene, "MailboxLowerTrim", (3.06, 0.05, 0.04), bevel=0.012, location=(0.0, -0.585, -0.79), mat=mat_trim))

    # Brushed champagne-pewter nameplate plaque + 2 mounting pins
    plaque = add_rounded_box(scene, "MailboxPlaque", (1.14, 0.06, 0.35), bevel=0.016, segments=5, location=(0.0, -0.605, -0.27), mat=mat_plaque)
    for poly in plaque.data.polygons:
        poly.use_smooth = abs(poly.normal.y) < 0.985
    front_objs.append(plaque)
    for px in (-0.47, 0.47):
        front_objs.append(
            add_cylinder(
                scene,
                f"PlaquePin_{px}",
                radius=0.028,
                depth=0.04,
                verts=28,
                bevel=0.008,
                location=(px, -0.635, -0.27),
                rotation=(math.radians(90), 0.0, 0.0),
                mat=mat_pin,
            )
        )

    # Four machined satin-silver corner fasteners on faceplate
    for fx in (-1.39, 1.39):
        for fz in (0.68, -0.68):
            front_objs.append(
                add_cylinder(
                    scene,
                    f"CornerRivet_{fx}_{fz}",
                    radius=0.032,
                    depth=0.045,
                    verts=28,
                    bevel=0.012,
                    location=(fx, -0.602, fz),
                    rotation=(math.radians(90), 0.0, 0.0),
                    mat=mat_rivet,
                )
            )

    # --- 3D Flush-Closing Hinged Mailbox Flap (exact same mat_enamel & flush seating!) ---
    # Fits Aperture X [-1.24, 1.24], Z [0.24, 0.54] with razor-fine 0.002 tolerance -> zero black gaps!
    flap_plate = add_rounded_box(scene, "MailboxFlapPlate", (2.476, 0.075, 0.296), bevel=0.013, segments=5, location=(0.0, -0.562, 0.39), mat=mat_enamel)
    for poly in flap_plate.data.polygons:
        poly.use_smooth = abs(poly.normal.y) < 0.985
    flap_objs.append(flap_plate)
    # Tactile sculpted lower edge lip (same enamel, catches subtle warm top-left specular highlight)
    flap_objs.append(add_rounded_box(scene, "MailboxFlapLip", (2.42, 0.042, 0.038), bevel=0.012, segments=4, location=(0.0, -0.594, 0.260), mat=mat_enamel))
    # Subtle twin top hinge knuckles seated along the top hinge axis (Z = 0.536)
    for hx in (-0.90, 0.90):
        flap_objs.append(
            add_cylinder(
                scene,
                f"FlapHingeBarrel_{hx}",
                radius=0.019,
                depth=0.22,
                verts=28,
                bevel=0.006,
                location=(hx, -0.586, 0.536),
                rotation=(0.0, math.radians(90), 0.0),
                mat=mat_enamel,
            )
        )
        flap_objs.append(
            add_cylinder(
                scene,
                f"FlapHingePin_{hx}",
                radius=0.010,
                depth=0.25,
                verts=20,
                bevel=0.003,
                location=(hx, -0.586, 0.536),
                rotation=(0.0, math.radians(90), 0.0),
                mat=mat_rivet,
            )
        )

    # --- Occlusion helper layers for envelope feed-in ---
    slot_back_objs.append(add_rounded_box(scene, "SlotBackPlane", (2.46, 0.02, 0.29), bevel=0.0, location=(0.0, -0.34, 0.39), mat=mat_cavity))
    slot_front_objs.append(add_rounded_box(scene, "SlotFrontPlane", (2.48, 0.05, 0.055), bevel=0.008, location=(0.0, -0.55, 0.232), mat=mat_trim))

    def set_visibility(visible_set, shadow_casters=None):
        all_groups = body_objs + front_objs + flap_objs + slot_back_objs + slot_front_objs
        shadow_set = set(shadow_casters) if shadow_casters is not None else set(visible_set)
        vis = set(visible_set)
        for obj in all_groups:
            in_vis = obj in vis
            in_shadow = obj in shadow_set
            obj.hide_render = not (in_vis or in_shadow)
            obj.visible_camera = in_vis

    # 1. Beauty (body + front + closed flush flap; helper planes hidden)
    set_visibility(body_objs + front_objs + flap_objs)
    render_to(scene, out_dir / "mailbox-light-beauty.png")

    # 2. Body (cabinet + dark slot cavity; front casts ambient shadows into cavity without blocking camera)
    set_visibility(body_objs, body_objs + front_objs)
    render_to(scene, out_dir / "mailbox-light-body.png")

    # 3. Front (open faceplate + plaque + rivets; body casts roof overhang shadow onto front; flap hidden so aperture is open)
    set_visibility(front_objs, body_objs + front_objs)
    render_to(scene, out_dir / "mailbox-light-front.png")

    # 4. Flap (isolated 3D flap with identical roof & faceplate bounce/AO lighting -> 100% seamless composite!)
    set_visibility(flap_objs, body_objs + front_objs + flap_objs)
    render_to(scene, out_dir / "mailbox-light-flap.png")

    # 5. Slot back & slot front occlusion layers
    set_visibility(slot_back_objs)
    render_to(scene, out_dir / "mailbox-light-slot-back.png")

    set_visibility(slot_front_objs, body_objs + front_objs + slot_front_objs)
    render_to(scene, out_dir / "mailbox-light-slot-front.png")

    # Compute exact projected normalized coordinates (origin top-left) for manifest synchronization
    def proj(pt):
        co = world_to_camera_view(scene, cam, Vector(pt))
        return [round(float(co.x), 5), round(float(1.0 - co.y), 5)]

    def proj_box(x0, x1, y, z0, z1):
        pts = [proj((x, y, z)) for x in (x0, x1) for z in (z0, z1)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return [round(min(xs), 5), round(min(ys), 5), round(max(xs) - min(xs), 5), round(max(ys) - min(ys), 5)]

    anchors = {
        "slot": proj((0.0, -0.56, 0.39)),
        "plaque": proj((0.0, -0.635, -0.27)),
        "exit": proj((-1.61, -0.04, -0.02)),
        "flapHinge": proj((0.0, -0.586, 0.538)),
        "slotFront": proj_box(-1.24, 1.24, -0.56, 0.24, 0.54),
        "slotBack": proj_box(-1.23, 1.23, -0.34, 0.25, 0.53),
    }
    anchors_path = out_dir / "mailbox-anchors.json"
    anchors_path.write_text(json.dumps(anchors, indent=2), encoding="utf-8")
    print("[blender] mailbox anchors:", json.dumps(anchors))


def main():
    args = parse_args()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {item.strip() for item in args.only.split(",") if item.strip()}

    def wanted(name: str) -> bool:
        return not only or name in only

    if wanted("mailbox"):
        print("[blender] rendering mailbox (6 layers) ...")
        build_mailbox(out_dir, max(args.samples, 64))
    if wanted("icon"):
        print("[blender] rendering app-icon ...")
        build_app_icon(out_dir, max(args.samples, 64))
    if wanted("wax"):
        print("[blender] rendering wax & wax-blue ...")
        build_wax_seal(out_dir, args.samples, "wax")
        build_wax_seal(out_dir, args.samples, "wax-blue")
    if wanted("wood"):
        for idx in range(4):
            print(f"[blender] rendering wood-{idx} ...")
            build_wood_log(out_dir, args.samples, idx)
    if wanted("trash"):
        print("[blender] rendering trash ...")
        build_trash_bin(out_dir, args.samples)
    if wanted("tv"):
        print("[blender] rendering desk-tv-frame ...")
        build_desk_tv_frame(out_dir, args.samples)
    if wanted("switch"):
        print("[blender] rendering shred-switch-plate ...")
        build_shred_switch_plate(out_dir, args.samples)
    if wanted("badges"):
        print("[blender] rendering platform badges ...")
        build_platform_badge(out_dir, 36, "douyin", (0.09, 0.12, 0.16))
        build_platform_badge(out_dir, 36, "xiaohongshu", (0.72, 0.14, 0.22))
        build_platform_badge(out_dir, 36, "bilibili", (0.16, 0.48, 0.62))
        build_platform_badge(out_dir, 36, "weread", (0.18, 0.44, 0.34))

    print("[blender] ALL DONE ->", out_dir)


if __name__ == "__main__":
    main()
