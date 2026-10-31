#include "catch.hpp"

#include <fstream>
#include <QTemporaryDir>

#include "IndexerCommandCustom.h"
#include "ProjectSettings.h"
#include "RefreshInfo.h"
#include "SourceGroupCustomCommand.h"
#include "SourceGroupSettingsCustomCommand.h"

namespace
{
void writeInput(const FilePath& path)
{
	std::ofstream stream(path.str());
	stream << "input\n";
}
}

TEST_CASE("modern source group observes explicit configuration and runs once", "[contract][modern]")
{
	QTemporaryDir temporary;
	REQUIRE(temporary.isValid());
	const FilePath directory(temporary.path().toStdWString());
	const FilePath first = directory.getConcatenated(L"first.py");
	const FilePath second = directory.getConcatenated(L"second.py");
	const FilePath configuration = directory.getConcatenated(L"project.srctrlcfg");
	writeInput(first);
	writeInput(second);
	writeInput(configuration);
	ProjectSettings project(directory.getConcatenated(L"project.srctrlprj"));
	auto settings = std::make_shared<SourceGroupSettingsCustomCommand>("modern", &project, SOURCE_GROUP_MODERN);
	settings->setSourcePaths({directory, configuration});
	settings->setSourceExtensions({L".py"});
	settings->setCustomCommand(L"adapter %{DATABASE_FILE_PATH} %{SOURCE_FILE_PATH}");
	settings->setRunInParallel(true); // Whole-project adapters always serialize one invocation.
	const SourceGroupCustomCommand group(settings);
	const auto sources = group.getAllSourceFilePaths();
	REQUIRE(sources.size() == 3);
	REQUIRE(sources.count(configuration) == 1);
	REQUIRE_FALSE(group.allowsPartialClearing());
	RefreshInfo info;
	info.filesToIndex = sources;
	const auto commands = group.getIndexerCommands(info);
	REQUIRE(commands.size() == 1);
	const auto command = std::dynamic_pointer_cast<IndexerCommandCustom>(commands.front());
	REQUIRE(command);
	REQUIRE_FALSE(command->getRunInParallel());
	info.filesToIndex.clear();
	REQUIRE(group.getIndexerCommands(info).empty());
}

TEST_CASE("modern source group type round trips through project settings", "[contract][modern]")
{
	QTemporaryDir temporary;
	REQUIRE(temporary.isValid());
	const FilePath projectPath(temporary.path().toStdWString() + L"/modern.srctrlprj");
	ProjectSettings project(projectPath);
	auto settings = std::make_shared<SourceGroupSettingsCustomCommand>("modern", &project, SOURCE_GROUP_MODERN);
	settings->setSourcePaths({FilePath(L"src"), FilePath(L"modern.srctrlcfg")});
	settings->setCustomCommand(L"adapter %{SOURCE_FILE_PATH}");
	project.setAllSourceGroupSettings({settings});
	const auto loaded = project.getAllSourceGroupSettings();
	REQUIRE(loaded.size() == 1);
	REQUIRE(loaded[0]->getType() == SOURCE_GROUP_MODERN);
	const auto custom = std::dynamic_pointer_cast<SourceGroupSettingsCustomCommand>(loaded[0]);
	REQUIRE(custom);
	REQUIRE(custom->getCustomCommand() == settings->getCustomCommand());
	REQUIRE(custom->getSourcePaths().size() == 2);
	REQUIRE(stringToSourceGroupType(sourceGroupTypeToString(SOURCE_GROUP_MODERN)) == SOURCE_GROUP_MODERN);
}
