#include "catch.hpp"

#include "utility.h"

#ifndef _WIN32
#	include <boost/filesystem.hpp>

#	include "ScopedFunctor.h"
#	include "utilityApp.h"
#	include "utilityString.h"
#endif

TEST_CASE("trim blank spaces of string")
{
	REQUIRE(utility::trim(" foo  ") == "foo");
}

TEST_CASE("trim blank spaces of wstring")
{
	REQUIRE(utility::trim(L" foo  ") == L"foo");
}

#ifndef _WIN32
TEST_CASE("process logging handles silent and newline terminated output", "[contract][execution][process]")
{
	std::wstring script;
	std::wstring expected;
	SECTION("silent child")
	{
		script = L":";
	}
	SECTION("EOF after a complete logged line")
	{
		script = L"printf 'finished\\n'";
		expected = L"finished";
	}
	const utility::ProcessOutput result = utility::executeProcess(
		L"/bin/sh", {L"-c", script}, FilePath(), false, 1000, true);
	REQUIRE(result.exitCode == 0);
	REQUIRE(result.error.empty());
	REQUIRE(result.output == expected);
}

TEST_CASE(
	"process preserves Unicode executable arguments and working directory",
	"[cxx][regression][process]")
{
	const boost::filesystem::path temporaryRoot = boost::filesystem::temp_directory_path() /
		boost::filesystem::unique_path("sourcetrail-process-%%%%-%%%%-%%%%");
	ScopedFunctor cleanup([&temporaryRoot]() { boost::filesystem::remove_all(temporaryRoot); });

	const boost::filesystem::path workingDirectory = temporaryRoot /
		utility::encodeToUtf8(L"日本語 with spaces");
	boost::filesystem::create_directories(workingDirectory);
	const boost::filesystem::path executable = workingDirectory /
		utility::encodeToUtf8(L"shell-日本語");
	boost::filesystem::create_symlink("/bin/sh", executable);

	const std::wstring argument = L"日本語 argument with spaces";
	const std::wstring script = L"printf 'cwd=%s\\nargc=%s\\narg=%s\\n' \"$PWD\" \"$#\" \"$1\"";
	const utility::ProcessOutput result = utility::executeProcess(
		utility::decodeFromUtf8(executable.generic_string()),
		{L"-c", script, L"sourcetrail-process-test", argument},
		FilePath(workingDirectory.generic_string()),
		false,
		10000);

	INFO(utility::encodeToUtf8(result.error));
	INFO(utility::encodeToUtf8(result.output));
	REQUIRE(result.error.empty());
	REQUIRE(result.exitCode == 0);
	REQUIRE(
		result.output ==
		L"cwd=" +
			utility::decodeFromUtf8(boost::filesystem::canonical(workingDirectory).generic_string()) +
			L"\nargc=1\narg=" + argument);
}
#endif
