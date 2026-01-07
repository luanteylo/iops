"""Unit tests for ReportGenerator color palette functionality."""

import pytest
from pathlib import Path
from typing import List

from iops.config.models import (
    ReportingConfig,
    ReportThemeConfig,
)
from iops.reporting.report_generator import ReportGenerator


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_workdir(tmp_path):
    """Create temporary workdir structure."""
    workdir = tmp_path / "run_001"
    workdir.mkdir(parents=True)
    return workdir


@pytest.fixture
def config_with_colors(temp_workdir):
    """Create ReportGenerator with custom theme colors."""
    custom_colors = ["#FF0000", "#00FF00", "#0000FF"]
    config = ReportingConfig(
        enabled=True,
        theme=ReportThemeConfig(colors=custom_colors),
    )
    return ReportGenerator(workdir=temp_workdir, report_config=config)


@pytest.fixture
def config_without_colors(temp_workdir):
    """Create ReportGenerator without custom theme colors."""
    config = ReportingConfig(
        enabled=True,
        theme=ReportThemeConfig(colors=None),
    )
    return ReportGenerator(workdir=temp_workdir, report_config=config)


@pytest.fixture
def generator_no_config(temp_workdir):
    """Create ReportGenerator without any config."""
    return ReportGenerator(workdir=temp_workdir, report_config=None)


# ============================================================================
# Test get_color_palette - Default Palette
# ============================================================================

class TestGetColorPaletteDefault:
    """Test get_color_palette with default palette (no user colors)."""

    def test_get_colors_within_palette_size(self):
        """Test requesting n colors where n <= 24 returns exact subset."""
        # Test various values within palette size
        for n in [1, 5, 10, 15, 24]:
            colors = ReportGenerator.get_color_palette(n)

            assert len(colors) == n
            assert colors == ReportGenerator.DEFAULT_COLOR_PALETTE[:n]
            # Verify all are valid hex colors
            for color in colors:
                assert color.startswith('#')
                assert len(color) == 7

    def test_get_single_color(self):
        """Test requesting just one color."""
        colors = ReportGenerator.get_color_palette(1)

        assert len(colors) == 1
        assert colors[0] == ReportGenerator.DEFAULT_COLOR_PALETTE[0]
        assert colors[0] == '#3498db'  # Blue

    def test_get_all_default_colors(self):
        """Test requesting exactly 24 colors (full default palette)."""
        colors = ReportGenerator.get_color_palette(24)

        assert len(colors) == 24
        assert colors == ReportGenerator.DEFAULT_COLOR_PALETTE
        # Verify no duplicates
        assert len(set(colors)) == 24

    def test_get_zero_colors(self):
        """Test requesting zero colors returns empty list."""
        colors = ReportGenerator.get_color_palette(0)

        assert len(colors) == 0
        assert colors == []

    def test_get_colors_exceeding_palette_size(self):
        """Test requesting n colors where n > 24 generates additional colors."""
        # Test with various values exceeding palette size
        for n in [25, 30, 50, 100]:
            colors = ReportGenerator.get_color_palette(n)

            assert len(colors) == n
            # First 24 should be from default palette
            assert colors[:24] == ReportGenerator.DEFAULT_COLOR_PALETTE
            # Remaining should be generated
            assert len(colors) > 24
            # All should be valid hex colors
            for color in colors:
                assert color.startswith('#')
                assert len(color) == 7

    def test_generated_colors_are_distinct(self):
        """Test that generated colors beyond 24 are variations of base colors."""
        colors = ReportGenerator.get_color_palette(30)

        # First 24 are base palette
        base_colors = colors[:24]
        # Next 6 should be variations
        generated_colors = colors[24:30]

        assert len(generated_colors) == 6
        # Generated colors should be different from base
        for i, gen_color in enumerate(generated_colors):
            base_color = base_colors[i]
            assert gen_color != base_color
            # But should be variations (lighter)
            assert gen_color.startswith('#')

    def test_cycling_through_palette(self):
        """Test that colors cycle through base palette with adjustments."""
        # Request 48 colors (2 full cycles)
        colors = ReportGenerator.get_color_palette(48)

        assert len(colors) == 48
        # First 24 are original palette
        assert colors[:24] == ReportGenerator.DEFAULT_COLOR_PALETTE
        # Next 24 should be adjusted versions cycling through base palette
        for i in range(24):
            # The (24+i)th color should be based on the i-th base color
            # but adjusted (we can't predict exact value but it should differ)
            assert colors[24 + i] != colors[i]


# ============================================================================
# Test get_color_palette - User Colors
# ============================================================================

class TestGetColorPaletteUserColors:
    """Test get_color_palette with user-provided colors."""

    def test_user_colors_within_provided_size(self):
        """Test requesting fewer colors than user provided."""
        user_colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00"]

        colors = ReportGenerator.get_color_palette(2, user_colors=user_colors)

        assert len(colors) == 2
        assert colors == ["#FF0000", "#00FF00"]

    def test_user_colors_exact_size(self):
        """Test requesting exactly as many colors as user provided."""
        user_colors = ["#FF0000", "#00FF00", "#0000FF"]

        colors = ReportGenerator.get_color_palette(3, user_colors=user_colors)

        assert len(colors) == 3
        assert colors == user_colors

    def test_user_colors_exceeding_provided_size(self):
        """Test requesting more colors than user provided cycles and generates."""
        user_colors = ["#FF0000", "#00FF00"]

        colors = ReportGenerator.get_color_palette(5, user_colors=user_colors)

        assert len(colors) == 5
        # First 2 are original user colors
        assert colors[:2] == user_colors
        # Next colors should be variations
        assert colors[2] != colors[0]  # Should be adjusted version
        assert colors[3] != colors[1]  # Should be adjusted version
        assert colors[4] != colors[0]  # Should be adjusted version

    def test_single_user_color_cycling(self):
        """Test that a single user color is cycled with variations."""
        user_colors = ["#808080"]  # Gray

        colors = ReportGenerator.get_color_palette(4, user_colors=user_colors)

        assert len(colors) == 4
        assert colors[0] == "#808080"
        # Remaining should be variations of gray
        for color in colors[1:]:
            assert color != "#808080"
            assert color.startswith('#')
            assert len(color) == 7

    def test_user_colors_with_hash_prefix(self):
        """Test user colors work correctly with # prefix."""
        user_colors = ["#FF0000", "#00FF00", "#0000FF"]

        colors = ReportGenerator.get_color_palette(2, user_colors=user_colors)

        assert colors == ["#FF0000", "#00FF00"]

    def test_empty_user_colors_falls_back_to_default(self):
        """Test that empty user colors list falls back to default palette."""
        user_colors = []

        colors = ReportGenerator.get_color_palette(5, user_colors=user_colors)

        # Empty list is falsy, so it falls back to default palette
        # This is correct behavior - empty user colors means "use defaults"
        assert len(colors) == 5
        assert colors == ReportGenerator.DEFAULT_COLOR_PALETTE[:5]


# ============================================================================
# Test _adjust_color_lightness
# ============================================================================

class TestAdjustColorLightness:
    """Test _adjust_color_lightness static method."""

    def test_lighten_color_positive_factor(self):
        """Test making a color lighter with positive factor."""
        # Start with a medium gray
        base_color = "#808080"  # RGB(128, 128, 128)

        lighter = ReportGenerator._adjust_color_lightness(base_color, 0.5)

        # Should move halfway towards white (255, 255, 255)
        # New value: 128 + (255 - 128) * 0.5 = 128 + 63.5 = 191.5 -> 191
        assert lighter == "#bfbfbf"  # RGB(191, 191, 191)

    def test_darken_color_negative_factor(self):
        """Test making a color darker with negative factor."""
        # Start with a medium gray
        base_color = "#808080"  # RGB(128, 128, 128)

        darker = ReportGenerator._adjust_color_lightness(base_color, -0.5)

        # Should multiply by (1 + -0.5) = 0.5
        # New value: 128 * 0.5 = 64
        assert darker == "#404040"  # RGB(64, 64, 64)

    def test_lighten_pure_red(self):
        """Test lightening pure red."""
        base_color = "#ff0000"  # RGB(255, 0, 0)

        lighter = ReportGenerator._adjust_color_lightness(base_color, 0.3)

        # Red already at 255, stays 255
        # Green: 0 + (255 - 0) * 0.3 = 76.5 -> 76
        # Blue: same as green
        assert lighter == "#ff4c4c"  # RGB(255, 76, 76)

    def test_darken_pure_blue(self):
        """Test darkening pure blue."""
        base_color = "#0000ff"  # RGB(0, 0, 255)

        darker = ReportGenerator._adjust_color_lightness(base_color, -0.4)

        # Red: 0 * 0.6 = 0
        # Green: 0 * 0.6 = 0
        # Blue: 255 * 0.6 = 153
        assert darker == "#000099"  # RGB(0, 0, 153)

    def test_zero_factor_returns_same_color(self):
        """Test that factor of 0 returns the same color."""
        base_color = "#3498db"

        result = ReportGenerator._adjust_color_lightness(base_color, 0.0)

        assert result == base_color

    def test_color_without_hash_prefix(self):
        """Test that colors without # prefix are handled correctly."""
        base_color = "808080"  # No # prefix

        lighter = ReportGenerator._adjust_color_lightness(base_color, 0.5)

        assert lighter == "#bfbfbf"
        assert lighter.startswith('#')

    def test_already_white_stays_white(self):
        """Test that white color stays white when lightened."""
        base_color = "#ffffff"  # RGB(255, 255, 255)

        result = ReportGenerator._adjust_color_lightness(base_color, 0.5)

        assert result == "#ffffff"

    def test_already_black_stays_black(self):
        """Test that black color stays black when darkened."""
        base_color = "#000000"  # RGB(0, 0, 0)

        result = ReportGenerator._adjust_color_lightness(base_color, -0.5)

        assert result == "#000000"

    def test_near_white_clamped_at_255(self):
        """Test that lightening near-white colors clamps at 255."""
        base_color = "#f0f0f0"  # RGB(240, 240, 240)

        # Large positive factor should still clamp at 255
        result = ReportGenerator._adjust_color_lightness(base_color, 1.0)

        assert result == "#ffffff"

    def test_near_black_clamped_at_0(self):
        """Test that darkening near-black colors clamps at 0."""
        base_color = "#0a0a0a"  # RGB(10, 10, 10)

        # Large negative factor should still clamp at 0
        result = ReportGenerator._adjust_color_lightness(base_color, -1.0)

        assert result == "#000000"

    def test_mixed_color_lighten(self):
        """Test lightening a mixed RGB color."""
        base_color = "#3498db"  # RGB(52, 152, 219) - Nice blue

        lighter = ReportGenerator._adjust_color_lightness(base_color, 0.15)

        # Red: 52 + (255 - 52) * 0.15 = 52 + 30.45 = 82
        # Green: 152 + (255 - 152) * 0.15 = 152 + 15.45 = 167
        # Blue: 219 + (255 - 219) * 0.15 = 219 + 5.4 = 224
        assert lighter == "#52a7e0"

    def test_mixed_color_darken(self):
        """Test darkening a mixed RGB color."""
        base_color = "#3498db"  # RGB(52, 152, 219)

        darker = ReportGenerator._adjust_color_lightness(base_color, -0.2)

        # Red: 52 * 0.8 = 41.6 -> 41
        # Green: 152 * 0.8 = 121.6 -> 121
        # Blue: 219 * 0.8 = 175.2 -> 175
        assert darker == "#2979af"

    def test_large_positive_factor(self):
        """Test that large positive factor approaches white."""
        base_color = "#404040"  # Dark gray

        result = ReportGenerator._adjust_color_lightness(base_color, 0.9)

        # Should be very close to white
        # 64 + (255 - 64) * 0.9 = 64 + 171.9 = 235.9 -> 235
        assert result == "#ebebeb"

    def test_large_negative_factor(self):
        """Test that large negative factor approaches black."""
        base_color = "#c0c0c0"  # Light gray

        result = ReportGenerator._adjust_color_lightness(base_color, -0.9)

        # 192 * 0.1 = 19.2 -> 19
        assert result == "#131313"


# ============================================================================
# Test _get_user_colors
# ============================================================================

class TestGetUserColors:
    """Test _get_user_colors instance method."""

    def test_get_user_colors_with_config_and_colors(self, config_with_colors):
        """Test retrieving user colors when config has theme colors."""
        colors = config_with_colors._get_user_colors()

        assert colors is not None
        assert colors == ["#FF0000", "#00FF00", "#0000FF"]

    def test_get_user_colors_with_config_no_colors(self, config_without_colors):
        """Test when config exists but theme.colors is None."""
        colors = config_without_colors._get_user_colors()

        assert colors is None

    def test_get_user_colors_no_config(self, generator_no_config):
        """Test when report_config is None."""
        colors = generator_no_config._get_user_colors()

        assert colors is None

    def test_get_user_colors_no_theme(self, temp_workdir):
        """Test when config exists but theme is None."""
        config = ReportingConfig(enabled=True, theme=None)
        generator = ReportGenerator(workdir=temp_workdir, report_config=config)

        colors = generator._get_user_colors()

        assert colors is None

    def test_get_user_colors_theme_with_empty_colors_list(self, temp_workdir):
        """Test when theme.colors is an empty list."""
        config = ReportingConfig(
            enabled=True,
            theme=ReportThemeConfig(colors=[]),
        )
        generator = ReportGenerator(workdir=temp_workdir, report_config=config)

        colors = generator._get_user_colors()

        # Empty list is falsy, so should return None
        assert colors is None

    def test_get_user_colors_returns_same_list(self, config_with_colors):
        """Test that _get_user_colors returns the exact same list."""
        colors1 = config_with_colors._get_user_colors()
        colors2 = config_with_colors._get_user_colors()

        assert colors1 == colors2
        assert colors1 is config_with_colors.report_config.theme.colors


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestColorPaletteIntegration:
    """Test integration scenarios combining multiple color palette methods."""

    def test_generator_uses_user_colors_from_config(self, config_with_colors):
        """Test that ReportGenerator can use its own config colors."""
        user_colors = config_with_colors._get_user_colors()

        # Use these colors to get a palette
        palette = ReportGenerator.get_color_palette(5, user_colors=user_colors)

        assert len(palette) == 5
        # First 3 should be user colors
        assert palette[:3] == ["#FF0000", "#00FF00", "#0000FF"]

    def test_default_palette_has_24_unique_colors(self):
        """Test that DEFAULT_COLOR_PALETTE has exactly 24 unique colors."""
        palette = ReportGenerator.DEFAULT_COLOR_PALETTE

        assert len(palette) == 24
        assert len(set(palette)) == 24  # All unique

        # All should be valid hex colors
        for color in palette:
            assert color.startswith('#')
            assert len(color) == 7
            # Verify valid hex digits
            int(color[1:], 16)  # Should not raise ValueError

    def test_sequential_lightening_produces_distinct_colors(self):
        """Test that sequential lightening cycles produce visibly different colors."""
        base_color = "#3498db"

        # Generate multiple cycles of lightening
        colors = [base_color]
        for cycle in range(1, 5):
            adjusted = ReportGenerator._adjust_color_lightness(base_color, 0.15 * cycle)
            colors.append(adjusted)

        # All should be different
        assert len(set(colors)) == 5

        # Each should be progressively lighter
        for i in range(len(colors) - 1):
            # Convert to RGB and verify getting lighter
            r1 = int(colors[i][1:3], 16)
            r2 = int(colors[i+1][1:3], 16)
            assert r2 >= r1  # Should be lighter or same (if already at max)

    def test_palette_generation_with_many_colors(self):
        """Test generating a very large palette (100+ colors)."""
        palette = ReportGenerator.get_color_palette(150)

        assert len(palette) == 150
        # All should be valid hex colors
        for color in palette:
            assert color.startswith('#')
            assert len(color) == 7

        # First 24 should match default palette
        assert palette[:24] == ReportGenerator.DEFAULT_COLOR_PALETTE

    def test_user_colors_override_default_completely(self):
        """Test that providing user colors completely overrides default palette."""
        user_colors = ["#000000", "#ffffff"]  # Black and white only

        # Request more than user provided
        palette = ReportGenerator.get_color_palette(6, user_colors=user_colors)

        assert len(palette) == 6
        # First 2 are user colors
        assert palette[0] == "#000000"
        assert palette[1] == "#ffffff"
        # Rest should be variations of black and white
        # Not from default palette
        for color in palette[2:]:
            assert color not in ReportGenerator.DEFAULT_COLOR_PALETTE[:4]


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestColorPaletteEdgeCases:
    """Test edge cases and error conditions."""

    def test_negative_n_colors(self):
        """Test requesting negative number of colors.

        Note: Python slicing with negative index returns 'all except last n'.
        With n=-5 and 24 base colors, returns first 19 colors.
        This documents current behavior - edge case unlikely in practice.
        """
        colors = ReportGenerator.get_color_palette(-5)

        # Python slice [:(-5)] returns all but last 5 elements
        assert len(colors) == 19
        assert colors == ReportGenerator.DEFAULT_COLOR_PALETTE[:-5]

    def test_very_large_n_colors(self):
        """Test requesting extremely large number of colors."""
        colors = ReportGenerator.get_color_palette(1000)

        assert len(colors) == 1000
        # Should still generate valid colors
        assert all(c.startswith('#') and len(c) == 7 for c in colors)

    def test_color_lightness_with_extreme_positive_factor(self):
        """Test adjust_color_lightness with very large positive factor."""
        base_color = "#404040"

        # Factor > 1.0 should still work and clamp to white
        result = ReportGenerator._adjust_color_lightness(base_color, 5.0)

        assert result == "#ffffff"

    def test_color_lightness_with_extreme_negative_factor(self):
        """Test adjust_color_lightness with very large negative factor."""
        base_color = "#c0c0c0"

        # Factor < -1.0 should still work and clamp to black
        result = ReportGenerator._adjust_color_lightness(base_color, -5.0)

        assert result == "#000000"

    def test_lowercase_hex_color(self):
        """Test that lowercase hex colors are handled correctly."""
        base_color = "#3498db"

        result = ReportGenerator._adjust_color_lightness(base_color, 0.2)

        # Result should be lowercase hex
        assert result.startswith('#')
        assert result == result.lower()

    def test_uppercase_hex_color(self):
        """Test that uppercase hex colors are handled correctly."""
        base_color = "#FF00FF"

        result = ReportGenerator._adjust_color_lightness(base_color, 0.1)

        # Implementation converts to lowercase
        assert result.startswith('#')
        assert result == result.lower()
