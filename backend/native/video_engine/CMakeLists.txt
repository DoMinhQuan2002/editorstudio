cmake_minimum_required(VERSION 3.25)

project(MediaStudioVideoEngine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(FFMPEG REQUIRED)

add_library(mediastudio_video_engine SHARED
    src/video_engine.cpp
    src/video_render.cpp
)

target_include_directories(mediastudio_video_engine PRIVATE ${FFMPEG_INCLUDE_DIRS})
target_link_directories(mediastudio_video_engine PRIVATE ${FFMPEG_LIBRARY_DIRS})
target_link_libraries(mediastudio_video_engine PRIVATE ${FFMPEG_LIBRARIES})
target_compile_definitions(mediastudio_video_engine PRIVATE MEDIASTUDIO_VIDEO_ENGINE_BUILD)

if(MSVC)
    target_compile_options(mediastudio_video_engine PRIVATE /W4 /permissive- /EHsc)
else()
    target_compile_options(mediastudio_video_engine PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(mediastudio_video_engine PROPERTIES
    OUTPUT_NAME "mediastudio_video_engine"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIG>"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIG>"
)

# Keep the FFmpeg runtime libraries beside the engine DLL so Python can load it
# without changing the process-wide PATH.
if(WIN32 AND DEFINED VCPKG_INSTALLED_DIR AND DEFINED VCPKG_TARGET_TRIPLET)
    add_custom_command(TARGET mediastudio_video_engine POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/bin"
            "$<TARGET_FILE_DIR:mediastudio_video_engine>"
        VERBATIM
    )
endif()
