#ifndef SOURCETRAIL_CORE_INDEXER_COMMAND_TEMPLATE_H
#define SOURCETRAIL_CORE_INDEXER_COMMAND_TEMPLATE_H

#include <string>
#include <utility>
#include <vector>

namespace sourcetrail
{
namespace core
{
// Values only: path discovery, encoding conversion, process launch and serialization
// belong to adapters. Both UTF-8 std::string and legacy std::wstring are supported.
template <typename String>
struct IndexerCommandContext
{
	String projectFilePath;
	String databaseFilePath;
	String databaseVersion;
	String sourceFilePath;
};

namespace detail
{
template <typename String>
void replaceIndexerVariable(String& text, const char* variable, const String& value)
{
	String token;
	for (; *variable; ++variable)
	{
		token.push_back(static_cast<typename String::value_type>(*variable));
	}
	typename String::size_type position = 0;
	while ((position = text.find(token, position)) != String::npos)
	{
		text.replace(position, token.size(), value);
		position += value.size();
	}
}
}	 // namespace detail

// COMMAND-001: preserve the historical ordered, non-recursive passes. A value may
// introduce a later variable, but the same/earlier variable is not expanded again.
template <typename String>
String expandIndexerTemplate(String text, const IndexerCommandContext<String>& context)
{
	detail::replaceIndexerVariable(text, "%{PROJECT_FILE_PATH}", context.projectFilePath);
	detail::replaceIndexerVariable(text, "%{DATABASE_FILE_PATH}", context.databaseFilePath);
	detail::replaceIndexerVariable(text, "%{DATABASE_VERSION}", context.databaseVersion);
	detail::replaceIndexerVariable(text, "%{SOURCE_FILE_PATH}", context.sourceFilePath);
	return text;
}

template <typename String>
std::vector<String> expandIndexerArguments(
	const std::vector<String>& arguments, const IndexerCommandContext<String>& context)
{
	std::vector<String> expanded;
	expanded.reserve(arguments.size());
	for (const String& argument: arguments)
	{
		expanded.push_back(expandIndexerTemplate(argument, context));
	}
	return expanded;
}
}	 // namespace core
}	 // namespace sourcetrail

#endif
