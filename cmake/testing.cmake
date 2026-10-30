# Keep the original Catch runner, while exposing independently selectable suites.
if(NOT BUILD_TESTING)
    return()
endif()

add_test(NAME legacy COMMAND ${TEST_PROJECT_NAME} "~[regression]~[e2e]" --warn NoTests)
set_tests_properties(legacy PROPERTIES
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/test"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
    LABELS "legacy;regression"
    TIMEOUT 600
)

if(BUILD_CXX_LANGUAGE_PACKAGE)
    target_compile_definitions(${TEST_PROJECT_NAME} PRIVATE
        SOURCETRAIL_TEST_APP_PATH="$<TARGET_FILE:${APP_PROJECT_NAME}>"
    )
    add_dependencies(${TEST_PROJECT_NAME} ${APP_PROJECT_NAME})
    foreach(suite regression e2e)
        add_test(NAME cpp-${suite}
            COMMAND ${TEST_PROJECT_NAME} "[cxx][${suite}]" --warn NoTests
        )
        set_tests_properties(cpp-${suite} PROPERTIES
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/test"
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
            LABELS "cpp;${suite}"
            TIMEOUT 600
        )
    endforeach()
endif()

if(BUILD_PYTHON_LANGUAGE_PACKAGE)
    find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
    foreach(suite regression e2e)
        add_test(NAME python-${suite}
            COMMAND "${Python3_EXECUTABLE}" -m pytest
                -c "${CMAKE_SOURCE_DIR}/tests/python/pytest.ini"
                "${CMAKE_SOURCE_DIR}/tests/python" -m ${suite}
        )
        set_tests_properties(python-${suite} PROPERTIES
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen;SOURCETRAIL_BINARY=$<TARGET_FILE:${APP_PROJECT_NAME}>;SOURCETRAIL_PYTHON_INDEXER=${CMAKE_SOURCE_DIR}/bin/app/data/python/SourcetrailPythonIndexer${CMAKE_EXECUTABLE_SUFFIX}"
            LABELS "python;${suite}"
            TIMEOUT 600
        )
    endforeach()
endif()
