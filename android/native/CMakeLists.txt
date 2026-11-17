cmake_minimum_required(VERSION 3.22)
project(waydroid_external_display LANGUAGES C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_compile_options("-ffile-prefix-map=${NATIVE_DEPS_DIR}=upstream")

if(NOT ANDROID OR NOT DEFINED NATIVE_DEPS_DIR OR NOT DEFINED VNDK_ARCH)
    message(FATAL_ERROR "Use the Android NDK toolchain and provide NATIVE_DEPS_DIR and VNDK_ARCH")
endif()

set(vndk "${NATIVE_DEPS_DIR}/vndk")
set(waydroid "${NATIVE_DEPS_DIR}/hardware/waydroid/hwcomposer")
set(wayland "${NATIVE_DEPS_DIR}/external/wayland")
set(ffi "${NATIVE_DEPS_DIR}/external/libffi")
set(xkb "${NATIVE_DEPS_DIR}/external/libxkbcommon")
set(generated "${CMAKE_BINARY_DIR}/generated")

file(STRINGS "${generated}/includes.txt" platform_includes)
add_library(android_platform INTERFACE)
target_include_directories(android_platform SYSTEM INTERFACE ${platform_includes})
target_compile_options(android_platform INTERFACE "$<$<COMPILE_LANGUAGE:CXX>:-nostdinc++;-fno-rtti>")
target_compile_definitions(android_platform INTERFACE __ANDROID_VNDK__)
target_link_options(android_platform INTERFACE -nostdlib++)
foreach(library IN ITEMS utils cutils log hardware hidlbase ui EGL GLESv2 c++)
    find_library(platform_${library} NAMES "lib${library}.so"
        PATHS "${vndk}/${VNDK_ARCH}/shared/vndk-core" "${vndk}/${VNDK_ARCH}/shared/vndk-sp"
              "${vndk}/${VNDK_ARCH}/shared/llndk-stub" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH REQUIRED)
    target_link_libraries(android_platform INTERFACE "${platform_${library}}")
endforeach()

add_library(sync_client STATIC "${NATIVE_DEPS_DIR}/system/core/libsync/sync.c")
target_include_directories(sync_client PUBLIC "${NATIVE_DEPS_DIR}/system/core")
target_link_libraries(sync_client PRIVATE android_platform)

add_library(ffi_client STATIC
    "${ffi}/src/closures.c" "${ffi}/src/debug.c" "${ffi}/src/java_raw_api.c"
    "${ffi}/src/prep_cif.c" "${ffi}/src/raw_api.c" "${ffi}/src/types.c"
    "${ffi}/src/${FFI_ARCH}/ffi.c" "${ffi}/src/${FFI_ARCH}/sysv.S")
target_include_directories(ffi_client PUBLIC "${ffi}/linux-${FFI_CONFIG}" "${generated}" PRIVATE "${ffi}/include")

add_library(wayland_client STATIC
    "${wayland}/src/connection.c" "${wayland}/src/wayland-client.c"
    "${wayland}/src/wayland-os.c" "${wayland}/src/wayland-util.c"
    "${generated}/wayland-protocol.c")
target_include_directories(wayland_client PUBLIC "${wayland}/src" "${wayland}/egl" "${generated}"
    PRIVATE "${wayland}")
target_link_libraries(wayland_client PUBLIC ffi_client)

file(GLOB xkb_sources "${xkb}/src/*.c" "${xkb}/src/xkbcomp/*.c" "${xkb}/src/compose/*.c")
list(REMOVE_ITEM xkb_sources "${xkb}/src/registry.c")
add_library(xkbcommon STATIC ${xkb_sources} "${xkb}/config/libxkbcommon.so.0.0.0.p/parser.c")
target_include_directories(xkbcommon PUBLIC "${xkb}/include"
    PRIVATE "${xkb}/src" "${xkb}/config" "${xkb}/config/libxkbcommon.so.0.0.0.p")
target_compile_definitions(xkbcommon PRIVATE _GNU_SOURCE)
target_compile_options(xkbcommon PRIVATE -fno-strict-aliasing)

file(GLOB_RECURSE hidl_sources "${generated}/vendor/*.cpp")
add_library(waydroid_interfaces STATIC ${hidl_sources})
target_include_directories(waydroid_interfaces PUBLIC "${generated}")
target_link_libraries(waydroid_interfaces PUBLIC android_platform)

include("${generated}/protocols.cmake")
file(GLOB composer_sources "${waydroid}/*.cpp" "${waydroid}/modes/*.cpp")
add_library(hwcomposer.waydroid SHARED ${composer_sources} ${wayland_protocol_sources})
set_target_properties(hwcomposer.waydroid PROPERTIES PREFIX "")
target_include_directories(hwcomposer.waydroid PRIVATE "${waydroid}" "${CMAKE_CURRENT_SOURCE_DIR}"
    "${NATIVE_DEPS_DIR}/external/minigbm" "${NATIVE_DEPS_DIR}/external/libdrm/include/drm"
    "${NATIVE_DEPS_DIR}/external/libdrm/android")
target_compile_definitions(hwcomposer.waydroid PRIVATE LOG_TAG="hwcomposer" EGL_EGLEXT_PROTOTYPES)
target_link_libraries(hwcomposer.waydroid PRIVATE android_platform waydroid_interfaces wayland_client xkbcommon sync_client)
target_link_options(hwcomposer.waydroid PRIVATE -Wl,--exclude-libs,ALL)

set(adapter "${NATIVE_DEPS_DIR}/hardware/interfaces/graphics/composer/2.1/utils/hwc2on1adapter")
add_library(hwc2on1adapter SHARED "${adapter}/HWC2On1Adapter.cpp" "${adapter}/MiniFence.cpp")
target_include_directories(hwc2on1adapter PRIVATE "${adapter}/include")
target_link_libraries(hwc2on1adapter PRIVATE android_platform)
target_link_options(hwc2on1adapter PRIVATE -Wl,--no-undefined)

install(TARGETS hwcomposer.waydroid hwc2on1adapter LIBRARY DESTINATION .)

add_library(abi_layout OBJECT abi_layout.cpp)
target_link_libraries(abi_layout PRIVATE android_platform)
