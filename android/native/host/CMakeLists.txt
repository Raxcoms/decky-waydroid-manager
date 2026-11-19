cmake_minimum_required(VERSION 3.22)
project(waydroid_native_tools LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)

find_package(BISON REQUIRED)
find_package(FLEX REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(JSONCPP REQUIRED IMPORTED_TARGET jsoncpp)
find_path(ANDROID_BASE_INCLUDE android-base/logging.h PATH_SUFFIXES android REQUIRED)
find_library(ANDROID_BASE_LIBRARY base PATH_SUFFIXES android REQUIRED)
find_library(ANDROID_LOG_LIBRARY log PATH_SUFFIXES android REQUIRED)

set(hidl "${NATIVE_DEPS_DIR}/system/tools/hidl")
set(vndk "${NATIVE_DEPS_DIR}/vndk/include")
bison_target(hidl_parser "${hidl}/hidl-gen_y.yy" "${CMAKE_CURRENT_BINARY_DIR}/hidl-gen_y.cpp"
    DEFINES_FILE "${CMAKE_CURRENT_BINARY_DIR}/hidl-gen_y.h")
flex_target(hidl_lexer "${hidl}/hidl-gen_l.ll" "${CMAKE_CURRENT_BINARY_DIR}/hidl-gen_l.cpp")
add_flex_bison_dependency(hidl_lexer hidl_parser)

file(GLOB sources "${hidl}/*.cpp" "${hidl}/host_utils/*.cpp" "${hidl}/hashing/*.cpp" "${hidl}/utils/*.cpp")
add_executable(hidl-gen ${sources} "${NATIVE_DEPS_DIR}/system/libbase/hex.cpp"
    ${BISON_hidl_parser_OUTPUTS} ${FLEX_hidl_lexer_OUTPUTS})
target_include_directories(hidl-gen PRIVATE "${hidl}" "${CMAKE_CURRENT_BINARY_DIR}"
    "${hidl}/host_utils/include" "${hidl}/host_utils/include/hidl-util"
    "${hidl}/hashing/include" "${hidl}/utils/include" "${hidl}/utils/include/hidl-util"
    "${ANDROID_BASE_INCLUDE}" "${NATIVE_DEPS_DIR}/system/libbase/include" "${vndk}/system/libhwbinder/include"
    "${vndk}/system/core/libutils/include" "${vndk}/system/logging/liblog/include")
target_link_libraries(hidl-gen PRIVATE "${ANDROID_BASE_LIBRARY}" "${ANDROID_LOG_LIBRARY}"
    OpenSSL::Crypto PkgConfig::JSONCPP)
