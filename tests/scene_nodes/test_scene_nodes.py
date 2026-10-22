# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic decoded facts; these tests do NOT establish MAX binary fidelity."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.interfaces import SceneNode, SceneNodePlan, Diagnostic
from maxblend_core.scene_nodes import (
    Camera, Evidence, Keyframe, Layer, Light, NodeDetails, NodePlanner, Timeline,
    TransformTrack, build_scene, class_hint, manifest_animation_summaries,
)

EV = Evidence("Scene", 0x0960, 3)
IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.),
            (0., 0., 1., 0.), (0., 0., 0., 1.))


def node(n, kind="MESH", parent=None, **kw):
    return NodeDetails(SceneNode(n, n, kind, parent, IDENTITY), EV,
                       normalized_transform=True, **kw)


def track(n, channel, keys, **kw):
    return TransformTrack(n, channel, "KEYED", tuple(Keyframe(f, v) for f, v in keys), EV,
                          **({"normalized_values": True} | kw))


class SceneNodesTests(unittest.TestCase):
    def test_f0_seam_pure_python(self):
        self.assertEqual(NodePlanner().plan(SceneNode("Obj", "Obj", "MESH")).diagnostics, ())
        self.assertNotIn("bpy", sys.modules)
        self.assertEqual(class_hint(0x1002), "CAMERA")
        self.assertEqual(class_hint(0x1011), "LIGHT")
        self.assertEqual(class_hint(0x5FD602DF3C5575A1), "LIGHT")
        self.assertEqual(class_hint(0xBAD), "UNKNOWN")

    def test_scene_hierarchy_and_keyed_transform_tracks(self):
        p = node("Parent")
        c = node("Child", parent="Parent")
        keys = (
            track("Child", "translation", [(0, (0., 0., 0.)), (24, (1., 2., 3.))]),
            track("Child", "rotation_quaternion", [(0, (1., 0., 0., 0.)),
                                                    (24, (0., 0., 0., 1.))]),
            track("Child", "scale", [(0, (1., 1., 1.)), (24, (2., 1., 1.))]),
        )
        scene = build_scene((p, c), timeline=Timeline(0, 24, 24., EV), tracks=keys)
        self.assertEqual(scene.status, "success")
        self.assertEqual(len(scene.tracks), 3)
        self.assertEqual({t.channel for t in scene.tracks}, {"translation", "rotation_quaternion", "scale"})
        summaries = manifest_animation_summaries(scene)
        self.assertEqual(summaries[0]["supported_tracks"], ["translation"])
        self.assertEqual(summaries[0]["coverage"], "partial")
        self.assertEqual(summaries[0]["warnings"][-1]["code"], "keyframe_payload_not_in_v1")
        self.assertEqual(summaries[0]["fps"], 24)
        self.assertEqual(summaries[0]["target_object_id"], "Child")

    def test_frame_rates_and_intervals(self):
        for fps in (24, 25, 30):
            with self.subTest(fps=fps):
                s = build_scene((node("Obj"),), timeline=Timeline(-10, 160, fps, EV))
                self.assertEqual(s.status, "success")
        invalid = build_scene((node("Obj"),), timeline=Timeline(30, 0, 0, EV))
        self.assertEqual(invalid.status, "failed")
        self.assertIn("invalid_fps", {d.code for d in invalid.diagnostics})
        self.assertIn("invalid_frame_range", {d.code for d in invalid.diagnostics})

    def test_camera_perspective_focal_filmback_shift_clipping(self):
        fov = 2 * math.atan(36 / (2 * 50))
        cam = Camera("PERSPECTIVE", horizontal_fov_rad=fov, focal_length_mm=50,
                     filmback_width_mm=36, filmback_height_mm=24,
                     shift_x=.1, shift_y=-.1, clip_near_m=.1, clip_far_m=100)
        s = build_scene((node("Cam", "CAMERA", camera=cam),), timeline=Timeline(0, 30, 30, EV))
        self.assertEqual(s.status, "success")
        self.assertEqual(s.details[0].camera.projection, "PERSPECTIVE")

    def test_camera_ortho_and_invalid_clip(self):
        cam = Camera("ORTHOGRAPHIC", ortho_width_m=10, clip_near_m=.1, clip_far_m=50)
        self.assertEqual(build_scene((node("Cam", "CAMERA", camera=cam),),
                                     timeline=Timeline(0, 10, 25, EV)).status, "success")
        bad = Camera("PERSPECTIVE", horizontal_fov_rad=5, clip_near_m=5, clip_far_m=1)
        d = build_scene((node("Cam", "CAMERA", camera=bad),), timeline=Timeline(0, 10, 25, EV)).diagnostics
        self.assertIn("invalid_camera_clip", {e.code for e in d})
        self.assertIn("invalid_camera_fov", {e.code for e in d})

    def test_light_units_and_unsupported_renderer_photometry(self):
        light = Light("AREA", intensity=200, color_linear_rgb=(1, .5, .1),
                      area_size_m=(2, 3), renderer_photometry_unsupported=True)
        s = build_scene((node("Light", "LIGHT", light=light),), timeline=Timeline(0, 10, 25, EV))
        self.assertEqual(s.status, "partial")
        self.assertIn("light_intensity_units_unknown", {d.code for d in s.diagnostics})
        self.assertIn("renderer_photometry_unsupported", {d.code for d in s.diagnostics})
        bad = Light("UNKNOWN", intensity=-2)
        s = build_scene((node("Other", "LIGHT", light=bad),), timeline=Timeline(0, 10, 25, EV))
        self.assertEqual(s.status, "failed")
        self.assertIn("light_kind_unsupported", {d.code for d in s.diagnostics})

    def test_layers_visibility_and_missing_refs(self):
        layer = Layer("FloorA", EV, "First floor", visible=False)
        obj = node("Child", layer_ids=("FloorA",), visible=False)
        s = build_scene((obj,), timeline=Timeline(0, 10, 25, EV), layers=(layer,))
        self.assertEqual(s.status, "success")
        self.assertEqual(s.details[0].visible, False)
        self.assertEqual(s.layers[0].visible, False)
        s = build_scene((node("Child", layer_ids=("Gone",)),),
                        timeline=Timeline(0, 10, 25, EV))
        self.assertIn("layer_target_missing", {d.code for d in s.diagnostics})

    def test_missing_parent_duplicate_and_cycles(self):
        for contents, code in (
            ((node("A", parent="Missing"),), "parent_missing"),
            ((node("A"), node("A")), "duplicate_node_id"),
            ((node("A", parent="B"), node("B", parent="A")), "parent_cycle"),
            ((node("A", parent="A"),), "parent_self"),
        ):
            with self.subTest(code=code):
                s = build_scene(contents, timeline=Timeline(0, 3, 30, EV))
                self.assertEqual(s.status, "failed")
                self.assertIn(code, {d.code for d in s.diagnostics})
        s = build_scene((node("A"),), timeline=Timeline(0, 3, 30, EV),
                        layers=(Layer("X", EV, "X", "Y"), Layer("Y", EV, "Y", "X")))
        self.assertIn("layer_cycle", {d.code for d in s.diagnostics})

    def test_missing_controller_and_targets(self):
        ts = (
            track("A", "translation", []),
            track("Lost", "scale", [(0, (1, 1, 1))]),
            track("A", "constraint", [(0, (1, 2, 3))], controller_supported=False),
        )
        s = build_scene((node("A"),), timeline=Timeline(0, 30, 30, EV), tracks=ts)
        self.assertIn("animation_source_missing", {d.code for d in s.diagnostics})
        self.assertIn("animation_target_missing", {d.code for d in s.diagnostics})
        self.assertIn("unsupported_controller", {d.code for d in s.diagnostics})
        self.assertEqual(manifest_animation_summaries(s)[2]["coverage"], "unsupported")

    def test_interpolation_sampling_axis_conversions(self):
        a = track("A", "translation", [(0, (0, 0, 0))],
                  interpolation="LINEAR", interpolation_verified=False)
        s = build_scene((node("A"),), timeline=Timeline(0, 20, 25, EV), tracks=(a,))
        self.assertIn("interpolation_unverified", {d.code for d in s.diagnostics})
        b = track("A", "scale", [(0, (1, 1, 1))], normalized_values=False)
        n = NodeDetails(
            SceneNode("A", "A", "MESH", local_matrix=IDENTITY), EV, normalized_transform=False)
        s = build_scene((n,), timeline=Timeline(0, 20, 25, EV), tracks=(b,))
        self.assertIn("node_axes_unverified", {d.code for d in s.diagnostics})
        self.assertIn("animation_axes_unverified", {d.code for d in s.diagnostics})
        self.assertEqual(b.keys[0].value, (1, 1, 1))  # no hidden double conversion
        sample = TransformTrack("A", "translation", "SAMPLED", (Keyframe(0, (0, 0, 0)),), EV,
                                "LINEAR", True, True)
        self.assertIn("sample_interpolation_unsupported", {
            d.code for d in build_scene((node("A"),), timeline=Timeline(0, 20, 25, EV),
                                        tracks=(sample,)).diagnostics})

    def test_invalid_frames_quaternions_and_limits(self):
        broken = track("A", "rotation_quaternion", [(0, (2, 0, 0, 0)), (0, (1, 0, 0, 0))])
        s = build_scene((node("A"),), timeline=Timeline(0, 20, 25, EV), tracks=(broken,))
        self.assertEqual(s.status, "failed")
        self.assertIn("invalid_rotation_quaternion", {d.code for d in s.diagnostics})
        with self.assertRaises(ValueError):
            Evidence("/private/client.max", 0x0960)
        with self.assertRaises(ValueError):
            Evidence("Scene", 70000)
        with self.assertRaises(ValueError):
            build_scene((node("A"),) * 100001, timeline=Timeline(0, 1, 25, EV))



    def test_f0_plan_and_diagnostic_type_provenance(self):
        plan = NodePlanner().plan(SceneNode("Invalid ID", "safe", "OTHER"))
        self.assertIsInstance(plan, SceneNodePlan)
        self.assertIsInstance(plan.diagnostics[0], Diagnostic)
        self.assertIsNone(plan.diagnostics[0].evidence)  # F0-only API has no source locator
        scene = build_scene((NodeDetails(SceneNode("Invalid ID", "safe", "OTHER"), EV),),
                            timeline=Timeline(0, 10, 25, EV))
        d = next(d for d in scene.diagnostics if d.code == "invalid_node_id")
        self.assertIsInstance(scene.nodes[0], SceneNodePlan)
        self.assertEqual(d.evidence, EV.token())
        self.assertEqual(d.status, "failed")
        self.assertNotIn("/", d.evidence)

    def test_camera_explicit_target_requires_existing_node(self):
        missing = build_scene((node("Cam", "CAMERA",
                                    camera=Camera("PERSPECTIVE", focal_length_mm=50, target_id="Target")),),
                              timeline=Timeline(0, 30, 30, EV))
        self.assertEqual(missing.status, "failed")
        self.assertIn("camera_target_missing", {d.code for d in missing.diagnostics})
        valid = build_scene((node("Cam", "CAMERA",
                                  camera=Camera("PERSPECTIVE", focal_length_mm=50, target_id="Target")),
                             node("Target", "EMPTY")), timeline=Timeline(0, 30, 30, EV))
        self.assertEqual(valid.status, "success")
        unknown = build_scene((node("Cam", "CAMERA",
                                    camera=Camera("PERSPECTIVE", focal_length_mm=50)),),
                              timeline=Timeline(0, 30, 30, EV))
        self.assertEqual(unknown.status, "success")
        self.assertIsNone(unknown.details[0].camera.target_id)

    def test_camera_invalid_lens_filmback_and_unknown_projection(self):
        cases = (
            (Camera("PERSPECTIVE", focal_length_mm=-1), "invalid_camera_parameter", "failed"),
            (Camera("PERSPECTIVE", focal_length_mm=50, filmback_width_mm=0), "invalid_camera_parameter", "failed"),
            (Camera("PERSPECTIVE", focal_length_mm=50, shift_x=float("nan")), "invalid_camera_shift", "failed"),
            (Camera("UNKNOWN"), "camera_projection_unknown", "partial"),
            (Camera("ORTHOGRAPHIC"), "camera_ortho_size_missing", "partial"),
            (Camera("PERSPECTIVE", focal_length_mm=50, target_id="../leak"), "invalid_camera_target_id", "failed"),
        )
        for cam, code, status in cases:
            with self.subTest(code=code):
                result = build_scene((node("Cam", "CAMERA", camera=cam),),
                                     timeline=Timeline(0, 24, 24, EV))
                self.assertEqual(result.status, status)
                self.assertIn(code, {d.code for d in result.diagnostics})

    def test_unknown_unverified_values_remain_unset(self):
        scene = build_scene((node("Cam", "CAMERA", camera=Camera()),
                             node("Light", "LIGHT", light=Light())),
                            timeline=Timeline())
        self.assertEqual(scene.status, "partial")
        self.assertIsNone(scene.timeline.fps)
        self.assertIsNone(scene.timeline.start_frame)
        self.assertIsNone(scene.details[0].camera.horizontal_fov_rad)
        self.assertIsNone(scene.details[1].light.intensity)
        self.assertIn("fps_unknown", {d.code for d in scene.diagnostics})
        self.assertIn("light_kind_unsupported", {d.code for d in scene.diagnostics})

    def test_nonfinite_and_malformed_inputs_do_not_crash(self):
        malformed = NodePlanner().plan(SceneNode("Node", "Node", "MESH",
                             local_matrix=((1, 0),)))
        self.assertIn("invalid_local_matrix", {d.code for d in malformed.diagnostics})
        result = NodePlanner().plan(SceneNode(None, "Node", "MESH"))
        self.assertIn("invalid_node_id", {d.code for d in result.diagnostics})
        broken = track("A", "translation", [(0, (0, 0, 0)), (5, (float("nan"), 0, 0))])
        s = build_scene((node("A"),), tracks=(broken,), timeline=Timeline(0, 10, 25, EV))
        self.assertEqual(s.status, "failed")
        self.assertIn("invalid_animation_keys", {d.code for d in s.diagnostics})

    def test_controller_interpolation_and_timebase_no_overclaim(self):
        for t in (
            track("A", "translation", [(0, (0, 0, 0))], interpolation="LINEAR",
                  interpolation_verified=False),
            track("A", "translation", [(0, (0, 0, 0))], interpolation="BEZIER"),
            track("A", "translation", [(0, (0, 0, 0))], controller_supported=False),
        ):
            with self.subTest(t=t.interpolation):
                s = build_scene((node("A"),), tracks=(t,),
                                timeline=Timeline(0, 20, 25, EV))
                self.assertEqual(s.status, "partial")
                self.assertTrue(set(d.code for d in s.diagnostics) &
                                {"interpolation_unverified", "unsupported_controller"})
                self.assertEqual(manifest_animation_summaries(s)[0]["coverage"], "unsupported")
        unknown_fps = build_scene((node("A"),),
                                  timeline=Timeline(0, 20, None, EV))
        self.assertEqual(unknown_fps.status, "partial")
        self.assertIn("fps_unknown", {d.code for d in unknown_fps.diagnostics})

if __name__ == "__main__":
    unittest.main()
