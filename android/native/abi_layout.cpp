#include <hwbinder/IBinder.h>

// Emit the inherited vtable layout using the same patched headers as the composer.
class WaydroidBinderLayout : public android::hardware::IBinder {
public:
    ~WaydroidBinderLayout() override;
};

WaydroidBinderLayout::~WaydroidBinderLayout() = default;
