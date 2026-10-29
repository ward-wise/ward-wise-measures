"""byop/v1 — bring-your-own-polygons measure contract: validator, pinning helper, registry checks."""

from .validate import ValidationError, load_spec, time_value_year, validate_layers_dir, validate_spec  # noqa: F401
from .presentation import extra_categories_problems, icon_svg_problems, keywords_problems  # noqa: F401

__version__ = "0.4.0"
