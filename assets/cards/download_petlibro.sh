#!/bin/bash
# Run this script to download Petlibro Granary 2 X images
# Usage: bash assets/cards/download_petlibro.sh

DEST="/Users/kimminsoo/Dev/shorts-studio/assets/cards"

echo "Downloading petlibro_granary2x_hero.jpg (TechCrunch editorial - cat at feeder)..."
curl -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -o "$DEST/petlibro_granary2x_hero.jpg" \
  "https://techcrunch.com/wp-content/uploads/2026/09/Granary2-feeder.png"

if [ $? -ne 0 ] || [ ! -s "$DEST/petlibro_granary2x_hero.jpg" ]; then
  echo "  TechCrunch failed, trying PR Newswire fallback..."
  curl -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
    -o "$DEST/petlibro_granary2x_hero.jpg" \
    "https://mmx.prnewswire.com/media/MS1868275/Petlibro-Granary_2_Series.jpg"
fi

echo ""
echo "Downloading petlibro_granary2x_detail.jpg (Official product shot - AF305)..."
curl -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -o "$DEST/petlibro_granary2x_detail.jpg" \
  "https://petlibro.com/cdn/shop/files/PDP-AF305-Carousel-01_1.png?v=1787019533"

if [ $? -ne 0 ] || [ ! -s "$DEST/petlibro_granary2x_detail.jpg" ]; then
  echo "  Petlibro CDN failed, trying allthethings.best fallback..."
  curl -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
    -o "$DEST/petlibro_granary2x_detail.jpg" \
    "https://www.allthethings.best/wp-content/uploads/2026/06/Petlibro-Debuts-Granary-2-Smart-Feeders-With-Biggest-Upgrade-Yet-for-Automated-Pet-Care.jpg"
fi

echo ""
echo "--- Results ---"
ls -lh "$DEST/petlibro_granary2x_hero.jpg" 2>/dev/null || echo "MISSING: petlibro_granary2x_hero.jpg"
ls -lh "$DEST/petlibro_granary2x_detail.jpg" 2>/dev/null || echo "MISSING: petlibro_granary2x_detail.jpg"
