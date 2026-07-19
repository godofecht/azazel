#!/usr/bin/env bash
# Quick start guide for building Danzig VST plugins

set -e

cd "$(dirname "$0")"

echo "🎵 Danzig VST Framework - Quick Start"
echo "======================================"
echo ""

# Check Zig is available
if ! command -v zig &> /dev/null; then
    echo "❌ Zig not found. Install from https://ziglang.org"
    exit 1
fi

# Check CUE is available for build generation
if ! command -v cue &> /dev/null; then
    echo "⚠️  CUE not found. Build spec will use cached version."
fi

echo "📦 Building Danzig VST Framework..."
echo ""

# Generate build spec from CUE
if command -v cue &> /dev/null; then
    echo "🔧 Generating build_spec.zig from CUE..."
    bash gen_build_spec.sh
fi

# Build all targets
echo "🏗️  Building..."
zig build

echo ""
echo "✅ Build Complete!"
echo ""
echo "📂 Artifacts:"
echo ""
echo "Library:"
echo "  • libdanzig.a         - Danzig framework (static library)"
echo ""
echo "Plugins:"
echo "  • libdanzig_gain.dylib - Gain effect plugin example"
echo ""
echo "Executables:"
echo "  • danzig_test         - Test linking danzig library"
echo "  • app                 - Original azazel app"
echo ""

echo "📖 Documentation:"
echo "  • DANZIG.md - Full framework documentation"
echo "  • examples/danzig-gain/root.zig - Gain plugin example"
echo ""

echo "🚀 Next Steps:"
echo "  1. Read DANZIG.md for detailed API documentation"
echo "  2. Examine examples/danzig-gain/root.zig for a complete plugin"
echo "  3. Create your own plugin in examples/your-plugin/"
echo "  4. Add to project.cue and export.cue"
echo "  5. Run 'zig build' to compile"
echo ""
