# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later


__author__ = "Sebastian Sille <nrgsille@gmail.com>"
__version__ = "1.9.2"
__date__ = "18 Nov 2023"


import bpy
import sys

# Wave 1 modules import the frozen F0 absolute package 'maxblend_core'.
# Alias *our own* bundled copy during normal Blender extension loading; never
# silently substitute a different installed add-on's core implementation.
from . import maxblend_core as _maxblend_core
_existing_core = sys.modules.get("maxblend_core")
if _existing_core is not None and _existing_core is not _maxblend_core:
    raise ImportError("MAXBLEND_CORE_NAMESPACE_COLLISION")
sys.modules["maxblend_core"] = _maxblend_core

from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
    poll_file_object_drop,
)
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    CollectionProperty,
)

if "bpy" in locals():
    import importlib
    if "import_max" in locals():
        importlib.reload(import_max)


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportMax(bpy.types.Operator, ImportHelper):
    """Import Autodesk MAX"""
    bl_idname = "import_scene.maxblend"
    bl_label = "MAXBLEND Import (.max)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
        default=1.0,
    )
    approved_texture_root: StringProperty(
        name="Approved Texture Folder",
        description="Optional explicit local folder; bitmap paths outside are blocked",
        subtype='DIR_PATH',
        default="",
    )
    use_image_search: BoolProperty(
        name="Image Search",
        description="Legacy option retained for API compatibility; guarded F6 import never performs recursive image searches",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=(('MATERIAL', "Material".rjust(12), "", 'MATERIAL_DATA', 0x1),
               ('UV', "UV Maps".rjust(11), "", 'UV_DATA', 0x2),
               ('PRIMITIVE', "Primitive".rjust(13), "", 'CUBE', 0x4),
               ('EMPTY', "Empty".rjust(11), "", 'EMPTY_AXIS', 0x8),
               ('ARMATURE', "Armature".rjust(11), "", 'ARMATURE_DATA', 0x10),
               ),
        description="Object types to import",
        default={'MATERIAL', 'UV', 'PRIMITIVE', 'EMPTY', 'ARMATURE'},
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_apply_matrix: BoolProperty(
        name="Apply Matrix",
        description="Use matrix to transform the objects",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        import_include(layout, self)
        import_transform(layout, self)

    def execute(self, context):
        from . import import_max
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        keywords["global_matrix"] = global_matrix

        return import_max.load(self, context, **keywords)

    def invoke(self, context, event):
        return self.invoke_popup(context)


def import_include(layout, operator):
    header, body = layout.panel("MAX_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.enabled = False  # Legacy option is API-compatible, but intentionally inactive in F6.
        layrow.prop(operator, "use_image_search")
        layrow.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_image_search else 'IMAGE_DATA')
        layout.column().prop(operator, "object_filter")
        layout.prop(operator, "approved_texture_root")
        layout.label(text="Texture lookup is default-deny and never recursive", icon='INFO')

        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')


def import_transform(layout, operator):
    header, body = layout.panel("MAX_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_apply_matrix")
        layrow.label(text="", icon='VIEW_ORTHO' if operator.use_apply_matrix else 'MESH_GRID')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class IO_FH_max(bpy.types.FileHandler):
    bl_idname = "IO_FH_maxblend"
    bl_label = "MAXBLEND MAX"
    bl_import_operator = "import_scene.maxblend"
    # Deliberately no bl_export_operator: no native .max exporter exists.
    bl_file_extensions = ".max"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func(self, context):
    self.layout.operator(ImportMax.bl_idname, text="MAXBLEND Fork (.max)")


def register():
    bpy.utils.register_class(ImportMax)
    bpy.utils.register_class(IO_FH_max)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    bpy.utils.unregister_class(IO_FH_max)
    bpy.utils.unregister_class(ImportMax)


if __name__ == "__main__":
    register()
