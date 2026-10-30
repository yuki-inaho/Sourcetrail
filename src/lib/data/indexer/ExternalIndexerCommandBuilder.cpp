#include "ExternalIndexerCommandBuilder.h"

#include "IndexerCommandCustom.h"
#include "ProjectSettings.h"
#include "SqliteIndexStorage.h"

std::vector<std::shared_ptr<IndexerCommand>> createExternalIndexerCommands(
	const ExternalIndexerCommandSpec& specification,
	const ProjectSettings* projectSettings,
	const std::set<FilePath>& sourceFiles,
	const std::set<FilePath>& filesToIndex)
{
	std::vector<std::shared_ptr<IndexerCommand>> commands;
	for (const FilePath& sourceFile: sourceFiles)
	{
		if (filesToIndex.find(sourceFile) != filesToIndex.end())
		{
			commands.push_back(std::make_shared<IndexerCommandCustom>(
				specification.type,
				specification.command,
				specification.arguments,
				projectSettings->getProjectFilePath(),
				projectSettings->getTempDBFilePath(),
				std::to_wstring(SqliteIndexStorage::getStorageVersion()),
				sourceFile,
				specification.runInParallel));
		}
	}
	return commands;
}
