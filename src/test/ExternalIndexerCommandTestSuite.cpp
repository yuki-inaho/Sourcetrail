#include "catch.hpp"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include "ExternalIndexerCommandBuilder.h"
#include "IndexerCommandCustom.h"
#include "ProjectSettings.h"
#include "SqliteIndexStorage.h"

TEST_CASE("external command preserves raw templates and late database retargeting", "[contract][command]")
{
	// COMMAND-001: the wire representation contains templates, resolved at execution time.
	auto command = std::make_shared<IndexerCommandCustom>(
		L"tool %{DATABASE_FILE_PATH}",
		std::vector<std::wstring> {L"", L"%{SOURCE_FILE_PATH}", L"%{DATABASE_FILE_PATH}", L"%{UNKNOWN}"},
		FilePath(L"project 日本語.srctrlprj"), FilePath(L"before db.srctrldb"), L"25",
		FilePath(L"source 日本語.py"), false);
	const auto serializedBefore = IndexerCommand::serialize(command, true);
	const QJsonObject serialized = QJsonDocument::fromJson(
		QString::fromStdWString(serializedBefore).toUtf8()).object();
	REQUIRE(serialized["command"].toString() == "tool %{DATABASE_FILE_PATH}");
	REQUIRE(serialized["arguments"].toArray()[2].toString() == "%{DATABASE_FILE_PATH}");
	REQUIRE(serialized["type"].toString() == "indexer_command_custom");
	REQUIRE_FALSE(command->getRunInParallel());
	REQUIRE(command->getCommand() == L"tool before db.srctrldb");
	command->setDatabaseFilePath(FilePath(L"after db.srctrldb"));
	REQUIRE(command->getCommand() == L"tool after db.srctrldb");
	REQUIRE(command->getArguments() == std::vector<std::wstring> {
		L"", L"source 日本語.py", L"after db.srctrldb", L"%{UNKNOWN}"});
	REQUIRE(IndexerCommand::serialize(command, true) == serializedBefore);
}

TEST_CASE("external command expansion keeps the legacy ordered passes", "[contract][command]")
{
	const IndexerCommandCustom command(
		L"%{PROJECT_FILE_PATH}", {}, FilePath(L"%{DATABASE_FILE_PATH}"),
		FilePath(L"%{DATABASE_VERSION}"), L"%{SOURCE_FILE_PATH}", FilePath(L"final source"), true);
	REQUIRE(command.getCommand() == L"final source");
	REQUIRE(command.getArguments().empty());
	REQUIRE(command.getIndexerCommandType() == INDEXER_COMMAND_CUSTOM);
	REQUIRE(command.getRunInParallel());
}

TEST_CASE("external command builder selects owned sources in deterministic order", "[contract][command]")
{
	const ProjectSettings project(FilePath(L"command_contract.srctrlprj"));
	const FilePath first(L"a.py"), second(L"z.py"), unselected(L"middle.py"), foreign(L"foreign.py");
	const ExternalIndexerCommandSpec specification {
		INDEXER_COMMAND_CUSTOM, L"tool", {L"%{PROJECT_FILE_PATH}", L"%{DATABASE_FILE_PATH}",
		L"%{DATABASE_VERSION}", L"%{SOURCE_FILE_PATH}"}, false};
	const auto commands = createExternalIndexerCommands(
		specification, &project, {second, first, unselected}, {second, first, foreign});
	REQUIRE(commands.size() == 2);
	REQUIRE(commands[0]->getSourceFilePath().wstr() == first.wstr());
	REQUIRE(commands[1]->getSourceFilePath().wstr() == second.wstr());
	for (const auto& base: commands)
	{
		const auto command = std::dynamic_pointer_cast<IndexerCommandCustom>(base);
		REQUIRE(command);
		REQUIRE_FALSE(command->getRunInParallel());
		REQUIRE(command->getArguments() == std::vector<std::wstring> {
			project.getProjectFilePath().wstr(), project.getTempDBFilePath().wstr(),
			std::to_wstring(SqliteIndexStorage::getStorageVersion()), base->getSourceFilePath().wstr()});
	}
	REQUIRE(createExternalIndexerCommands(specification, &project, {first}, {foreign}).empty());
	REQUIRE(createExternalIndexerCommands(specification, &project, {}, {first}).empty());
	REQUIRE(createExternalIndexerCommands(specification, nullptr, {first}, {foreign}).empty());
	REQUIRE(createExternalIndexerCommands(specification, nullptr, {}, {first}).empty());
}
