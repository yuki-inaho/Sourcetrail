#include "IndexerCommandTemplate.h"

#include <iostream>
#include <stdexcept>

namespace
{
void require(bool condition, const char* message)
{
	if (!condition)
	{
		throw std::runtime_error(message);
	}
}
}

int main()
{
	try
	{
		using sourcetrail::core::expandIndexerArguments;
		using sourcetrail::core::expandIndexerTemplate;
		using sourcetrail::core::IndexerCommandContext;
		const IndexerCommandContext<std::string> context {
			"project 日本語.srctrlprj", "db with spaces.srctrldb", "25", "src/日本語.py"};
		require(
			expandIndexerTemplate(std::string("%{PROJECT_FILE_PATH}|%{DATABASE_FILE_PATH}|"
				"%{DATABASE_VERSION}|%{SOURCE_FILE_PATH}"), context) ==
				"project 日本語.srctrlprj|db with spaces.srctrldb|25|src/日本語.py",
			"UTF-8 values must remain byte-exact");
		const std::vector<std::string> arguments {
			"", "--source", "%{SOURCE_FILE_PATH}", "a b", "%{UNKNOWN}",
			"%{DATABASE_VERSION}%{DATABASE_VERSION}"};
		require(expandIndexerArguments(arguments, context) == std::vector<std::string> {
			"", "--source", "src/日本語.py", "a b", "%{UNKNOWN}", "2525"},
			"argument boundaries, empty arguments, unknown tokens and repeated values must survive");
		const IndexerCommandContext<std::string> ordered {
			"%{DATABASE_FILE_PATH}/project", "%{DATABASE_VERSION}/db", "%{SOURCE_FILE_PATH}/v", "src"};
		require(expandIndexerTemplate(std::string("%{PROJECT_FILE_PATH}"), ordered) == "src/v/db/project",
			"later introduced variables must be expanded in the historical pass order");
		const IndexerCommandContext<std::string> nonRecursive {
			"%{PROJECT_FILE_PATH}", "%{PROJECT_FILE_PATH}", "", "%{SOURCE_FILE_PATH}"};
		require(expandIndexerTemplate(std::string("%{PROJECT_FILE_PATH}|%{DATABASE_FILE_PATH}|"
			"%{DATABASE_VERSION}|%{SOURCE_FILE_PATH}"), nonRecursive) ==
			"%{PROJECT_FILE_PATH}|%{PROJECT_FILE_PATH}||%{SOURCE_FILE_PATH}",
			"same or earlier variables must not recursively expand");
		const IndexerCommandContext<std::wstring> wide {
			L"project 日本語", L"db space", L"25", L"src/Ω.py"};
		require(expandIndexerArguments(std::vector<std::wstring> {
			L"%{PROJECT_FILE_PATH}", L"%{DATABASE_FILE_PATH}", L"%{SOURCE_FILE_PATH}"}, wide) ==
			std::vector<std::wstring> {L"project 日本語", L"db space", L"src/Ω.py"},
			"legacy wide-string values must remain unchanged");
		std::cout << "COMMAND-001: 5 independent command-template scenarios passed\n";
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
