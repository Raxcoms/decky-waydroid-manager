#pragma once

#include <algorithm>
#include <cmath>

namespace waydroid_manager {

inline int display_density(int base, double scale, int width, int height, int reference) {
    if (width <= 0 || height <= 0 || reference <= 0 || !std::isfinite(scale) || scale <= 0)
        return base;
    return std::max(1, int(std::lround(base * scale * std::min(width, height) / reference)));
}

}
