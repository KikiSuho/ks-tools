"""
Project structure tree visualizer with Python AST analysis and change tracking.

Re-exports key types and functions from submodules for convenience.

Classes
-------
AstRenderer : Render Python AST nodes into tree-style structure lines.
CallFlowMode : Enum controlling call flow display mode.
Config : Configuration settings for directory scanning and output generation.
DirectoryStructure : Scan directories and render a tree with code insights.
FilterSettings : Immutable snapshot of filtering-related configuration.
RenderSettings : Immutable snapshot of rendering-related configuration.
SaveResult : Result of saving a directory structure.
VisibilitySettings : Parsed visibility and feature settings from CLI arguments.
WriteStatus : Outcome of a structure file write operation.

Functions
---------
build_filter_settings : Create a FilterSettings snapshot from the current Config state.
build_render_settings : Create a RenderSettings snapshot from the current Config state.
get_tree_connectors : Return connector symbol and next prefix for a tree item.
parse_visibility_args : Parse CLI flags for visibility and feature settings.

Examples
--------
>>> import os
>>> from trellis import DirectoryStructure
>>> scanner = DirectoryStructure(os.getcwd())
>>> scanner.project_name == os.path.basename(os.getcwd())
True

"""

from trellis.config import CallFlowMode as CallFlowMode
from trellis.config import Config as Config
from trellis.config import FilterSettings as FilterSettings
from trellis.config import VisibilitySettings as VisibilitySettings
from trellis.config import build_filter_settings as build_filter_settings
from trellis.config import parse_visibility_args as parse_visibility_args
from trellis.core.persistence import SaveResult as SaveResult
from trellis.core.persistence import WriteStatus as WriteStatus
from trellis.main import DirectoryStructure as DirectoryStructure
from trellis.pyast.renderer import AstRenderer as AstRenderer
from trellis.pyast.renderer import RenderSettings as RenderSettings
from trellis.pyast.renderer import build_render_settings as build_render_settings
from trellis.pyast.tree_drawing import get_tree_connectors as get_tree_connectors

__all__ = [
    "AstRenderer",
    "CallFlowMode",
    "Config",
    "DirectoryStructure",
    "FilterSettings",
    # Note: "main" is intentionally NOT re-exported here to avoid shadowing
    # the trellis.main module. Use trellis.main.main() directly.
    "RenderSettings",
    "SaveResult",
    "VisibilitySettings",
    "WriteStatus",
    "build_filter_settings",
    "build_render_settings",
    "get_tree_connectors",
    "parse_visibility_args",
]
