cmake_minimum_required(VERSION 3.8)

# Configure this directory on its own to check the core without application dependencies.
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(SourcetrailCore LANGUAGES CXX)
    include(CTest)
endif()

add_library(Sourcetrail_core INTERFACE)
target_compile_features(Sourcetrail_core INTERFACE cxx_std_17)
target_include_directories(Sourcetrail_core INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}")

if(BUILD_TESTING)
    foreach(contract input location)
        if(contract STREQUAL "input")
            set(contract_source source_change_test.cpp)
        else()
            set(contract_source utf8_source_location_test.cpp)
        endif()
        add_executable(core-${contract}-contracts "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/core/${contract_source}")
        target_link_libraries(core-${contract}-contracts PRIVATE Sourcetrail_core)
        add_test(NAME core-${contract}-contracts COMMAND core-${contract}-contracts)
        set_tests_properties(core-${contract}-contracts PROPERTIES LABELS "cpp;contract;portability" TIMEOUT 60)
    endforeach()
    add_executable(core-refresh-driver
        "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/portability/refresh_driver.cpp"
    )
    target_link_libraries(core-refresh-driver PRIVATE Sourcetrail_core)
    add_executable(core-refresh-contracts
        "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/core/refresh_planner_test.cpp"
    )
    target_link_libraries(core-refresh-contracts PRIVATE Sourcetrail_core)
    add_test(NAME core-refresh-contracts COMMAND core-refresh-contracts)
    set_tests_properties(core-refresh-contracts PROPERTIES
        LABELS "cpp;contract;portability"
        TIMEOUT 60
    )
    add_executable(core-command-contracts
        "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/core/indexer_command_template_test.cpp"
    )
    target_link_libraries(core-command-contracts PRIVATE Sourcetrail_core)
    add_test(NAME core-command-contracts COMMAND core-command-contracts)
    set_tests_properties(core-command-contracts PROPERTIES
        LABELS "cpp;contract;portability"
        TIMEOUT 60
    )
    add_executable(core-execution-contracts
        "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/core/external_indexer_outcome_test.cpp"
    )
    target_link_libraries(core-execution-contracts PRIVATE Sourcetrail_core)
    add_test(NAME core-execution-contracts COMMAND core-execution-contracts)
    set_tests_properties(core-execution-contracts PROPERTIES
        LABELS "cpp;contract;portability"
        TIMEOUT 60
    )
endif()
